#!/usr/bin/env python3
"""Generate a deterministic corpus of realistic synthetic production incidents."""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path


SERVICES = ["checkout-api", "payments-worker", "catalog-api", "user-service", "order-db-proxy"]
SCENARIOS = [
    {
        "category": "oom_kill",
        "symptom": "container memory climbed steadily until the kernel killed the process",
        "causes": ["unbounded in-memory response cache", "large batch payload retained between queue acknowledgements", "streaming export buffered the full result set"],
        "log": "kernel: Memory cgroup out of memory: Killed process {pid} ({proc}) total-vm:{vm}kB, anon-rss:{rss}kB, oom_score_adj:0",
        "steps": ["Rolled back the last memory-heavy release and restarted affected replicas.", "Reduced batch size and bounded the response cache with an eviction limit.", "Added a memory limit alert at 75% and a load test for large payloads."],
        "runbooks": ["RB-017 Container OOM and memory pressure", "RB-031 Worker backlog and batch sizing"],
        "metrics": {"memory_pct": [91, 99], "restart_count": [2, 18]},
    },
    {
        "category": "db_pool_exhaustion",
        "symptom": "requests stalled while all database connections remained checked out",
        "causes": ["connection leak on exception path", "pool size below peak worker concurrency", "slow transaction held connections during downstream calls"],
        "log": "{svc} ERROR db.pool: checkout timed out after {wait:.1f}s (pool_size={pool}, checked_out={used}, overflow=0)",
        "steps": ["Raised the pool checkout timeout briefly to drain the queue and restarted leaking workers.", "Fixed connection cleanup with a context manager and capped concurrent database work.", "Added pool saturation and checkout-wait alerts; reviewed slow query traces."],
        "runbooks": ["RB-004 Database connection pool exhaustion", "RB-022 Slow query and lock investigation"],
        "metrics": {"pool_used_pct": [95, 100], "db_wait_ms": [2400, 12000]},
    },
    {
        "category": "latency_spike",
        "symptom": "p95 request latency rose sharply while upstream calls accumulated retries",
        "causes": ["retry amplification against a degraded dependency", "missing cache caused a database read surge", "one hot shard increased query and lock duration"],
        "log": "{svc} WARN http.server: request_id={rid} route={route} status={status} duration_ms={duration} upstream={upstream}",
        "steps": ["Disabled the aggressive retry policy and shed non-critical traffic.", "Restored the affected cache path and invalidated stale entries safely.", "Moved traffic away from the hot shard and added a latency budget alert."],
        "runbooks": ["RB-009 Elevated API latency", "RB-026 Dependency timeout and retry storm"],
        "metrics": {"p95_ms": [1800, 9500], "error_rate_pct": [4, 38]},
    },
    {
        "category": "disk_pressure",
        "symptom": "nodes became unhealthy after application and container logs filled the filesystem",
        "causes": ["log rotation was disabled after an image change", "temporary exports were not removed", "container runtime retained old image layers"],
        "log": "{ts} {host} kubelet[822]: eviction manager: nodefs.available below threshold; available={avail}Mi, threshold={threshold}Mi",
        "steps": ["Freed space from rotated logs and stale container layers.", "Restored size-based log rotation and cleaned temporary export files.", "Added a node filesystem alert and a retention policy for generated artifacts."],
        "runbooks": ["RB-013 Node disk pressure and eviction", "RB-035 Log retention and rotation"],
        "metrics": {"disk_used_pct": [93, 100], "evicted_pods": [1, 12]},
    },
    {
        "category": "queue_backlog",
        "symptom": "consumer lag grew continuously and order processing missed its SLO",
        "causes": ["consumer throughput fell after a downstream timeout change", "poison messages retried without a dead-letter limit", "consumer deployment reduced concurrency unexpectedly"],
        "log": "{svc} ERROR consumer: partition={partition} lag={lag} oldest_message_age={age}m delivery_attempt={attempt} error=upstream_timeout",
        "steps": ["Paused the poison-message partition and replayed valid messages from the last checkpoint.", "Restored safe consumer concurrency and rate-limited retries with backoff.", "Added lag and oldest-message-age alerts plus a bounded dead-letter queue."],
        "runbooks": ["RB-031 Worker backlog and batch sizing", "RB-028 Queue poison message recovery"],
        "metrics": {"consumer_lag": [12000, 240000], "oldest_age_min": [8, 190]},
    },
]


def build_incidents(count: int = 50, seed: int = 20261107) -> list[dict]:
    rng = random.Random(seed)
    start = datetime(2025, 1, 5, 0, 0, tzinfo=timezone.utc)
    incidents = []
    for index in range(count):
        scenario = SCENARIOS[index % len(SCENARIOS)]
        service = rng.choice(SERVICES)
        started = start + timedelta(days=index * 5 + rng.randrange(0, 4), hours=rng.randrange(0, 24))
        host = f"ip-10-{rng.randrange(0, 255)}-{rng.randrange(1, 255)}"
        values = {
            "pid": rng.randrange(100, 65000), "proc": service.split("-")[0],
            "vm": rng.randrange(900000, 8000000), "rss": rng.randrange(700000, 4000000),
            "svc": service, "wait": rng.uniform(2.0, 15.0), "pool": rng.choice([20, 30, 40]),
            "used": rng.choice([20, 30, 40]), "rid": f"{rng.getrandbits(64):016x}",
            "route": rng.choice(["/v1/orders", "/v1/checkout", "/v2/items"]),
            "status": rng.choice([200, 503, 504]), "duration": rng.randrange(1800, 12000),
            "upstream": rng.choice(["postgres-primary", "inventory", "redis-cache"]),
            "ts": started.isoformat(), "host": host, "avail": rng.randrange(120, 900),
            "threshold": 1024, "partition": rng.randrange(0, 24), "lag": rng.randrange(12000, 240000),
            "age": rng.randrange(8, 190), "attempt": rng.randrange(3, 12),
        }
        log = scenario["log"].format(**values)
        metrics = {key: rng.randint(*bounds) for key, bounds in scenario["metrics"].items()}
        duration_min = rng.randrange(12, 96)
        incidents.append({
            "incident_id": f"INC-{started:%Y%m%d}-{index + 1:03d}",
            "started_at": started.isoformat(), "service": service,
            "severity": rng.choice(["SEV-1", "SEV-2", "SEV-2", "SEV-3"]),
            "category": scenario["category"], "summary": scenario["symptom"],
            "impact": f"{rng.randrange(8, 72)}% of {service} requests were degraded for approximately {duration_min} minutes.",
            "error_logs": [log, f"{started:%Y-%m-%dT%H:%M:%S.%fZ} {service} ERROR incident signal: {scenario['category']} threshold exceeded; trace_id={values['rid']}"],
            "root_cause": rng.choice(scenario["causes"]),
            "resolution_steps": scenario["steps"],
            "runbooks_that_worked": scenario["runbooks"],
            "metrics_at_peak": metrics,
            "resolved_at": (started + timedelta(minutes=duration_min)).isoformat(),
            "follow_up": "Owner assigned to add regression coverage, alerting, and a documented rollback check.",
        })
    return incidents


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=50, help="number of incidents (default: 50)")
    parser.add_argument("--seed", type=int, default=20261107)
    parser.add_argument("--output", type=Path, default=Path("data/past_incidents.json"))
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count must be at least 1")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(build_incidents(args.count, args.seed), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.count} synthetic incidents to {args.output}")


if __name__ == "__main__":
    main()
