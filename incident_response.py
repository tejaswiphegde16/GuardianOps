#!/usr/bin/env python3
"""Terminal incident loop with a persistent, Hindsight-shaped mock memory client.

Replace ``LocalHindsightClient`` with the Hindsight SDK/REST adapter when its
endpoint and authentication details are available. The agent loop only depends
on ``recall`` and ``retain`` so that integration stays isolated.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


DEFAULT_MEMORY = Path("data/hindsight_memory.json")
STOP_WORDS = {"the", "and", "for", "with", "that", "from", "this", "into", "after", "were", "when", "while", "was", "are", "has", "have", "incident", "error"}


class MemoryError(RuntimeError):
    """Raised when the mock memory store cannot be read or updated."""


class LocalHindsightClient:
    """Small local stand-in for Hindsight recall/retain operations.

    The JSON shape is intentionally plain so a real Hindsight adapter can map
    these calls to its API without changing the execution loop.
    """

    def __init__(self, path: Path):
        self.path = path

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"memories": []}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MemoryError(f"cannot read memory store {self.path}: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("memories"), list):
            raise MemoryError(f"invalid memory store format in {self.path}")
        return payload

    def _save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, delete=False) as handle:
                temp_name = handle.name
                json.dump(payload, handle, indent=2)
                handle.write("\n")
            os.replace(temp_name, self.path)
        except OSError as exc:
            if temp_name:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass
            raise MemoryError(f"cannot write memory store {self.path}: {exc}") from exc

    def retain(self, memory: dict[str, Any]) -> None:
        if not isinstance(memory, dict) or not memory.get("text"):
            raise ValueError("memory must be an object containing non-empty text")
        payload = self._load()
        # Make seeding repeatable and let a corrected postmortem replace its
        # previous version instead of accumulating duplicate memories.
        identity = (memory.get("source"), memory.get("incident_id"))
        payload["memories"] = [
            existing for existing in payload["memories"]
            if (existing.get("source"), existing.get("incident_id")) != identity
        ]
        payload["memories"].append(memory)
        self._save(payload)

    def recall(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Return lexical relevance ranking; production adapter should use Hindsight retrieval."""
        payload = self._load()
        query_tokens = _tokens(query)
        ranked = []
        for memory in payload["memories"]:
            text = str(memory.get("text", ""))
            tokens = _tokens(text)
            overlap = len(query_tokens & tokens)
            category_match = bool(memory.get("category") and memory["category"].lower() in query.lower())
            score = overlap + (4 if category_match else 0)
            if score:
                ranked.append((score, memory))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return [dict(item, _score=score) for score, item in ranked[:max(0, limit)]]


def _tokens(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9_/-]+", text.lower()) if len(word) > 2 and word not in STOP_WORDS}


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON input {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return value


def _incident_memory(incident: dict[str, Any], source: str = "historical_incident") -> dict[str, Any]:
    return {
        "source": source,
        "incident_id": incident.get("incident_id", "unknown"),
        "category": incident.get("category", "unknown"),
        "service": incident.get("service", "unknown"),
        "text": " ".join(str(part) for part in (
            incident.get("summary", ""), incident.get("category", ""), incident.get("service", ""),
            " ".join(incident.get("error_logs", [])) if isinstance(incident.get("error_logs", []), list) else incident.get("error_logs", ""),
            incident.get("root_cause", ""), " ".join(incident.get("resolution_steps", [])) if isinstance(incident.get("resolution_steps", []), list) else "",
            " ".join(incident.get("runbooks_that_worked", [])) if isinstance(incident.get("runbooks_that_worked", []), list) else "",
        ) if part),
        "root_cause": incident.get("root_cause"),
        "resolution_steps": incident.get("resolution_steps", []),
        "runbooks_that_worked": incident.get("runbooks_that_worked", []),
    }


def seed_memory(client: LocalHindsightClient, incidents_path: Path) -> int:
    try:
        incidents = json.loads(incidents_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read incident corpus {incidents_path}: {exc}") from exc
    if not isinstance(incidents, list):
        raise ValueError("incident corpus must be a JSON array")
    count = 0
    for incident in incidents:
        if not isinstance(incident, dict):
            continue
        client.retain(_incident_memory(incident))
        count += 1
    return count


def respond_to_alert(alert: dict[str, Any], client: LocalHindsightClient, limit: int = 5) -> dict[str, Any]:
    """Recall comparable incidents and produce a cautious, operator-facing plan."""
    description = " ".join(str(alert.get(key, "")) for key in ("summary", "service", "category", "error", "logs"))
    if not description.strip():
        raise ValueError("alert needs at least one of summary, service, category, error, or logs")
    memories = client.recall(description, limit=limit)
    recommendations = []
    seen_steps = set()
    for memory in memories:
        for step in memory.get("resolution_steps", []):
            if step not in seen_steps:
                recommendations.append(step)
                seen_steps.add(step)
    result = {
        "alert_id": alert.get("alert_id", "unassigned"),
        "service": alert.get("service", "unknown"),
        "matches": memories,
        "suggested_root_causes": list(dict.fromkeys(m.get("root_cause") for m in memories if m.get("root_cause"))),
        "suggested_runbooks": list(dict.fromkeys(book for m in memories for book in m.get("runbooks_that_worked", []))),
        "suggested_actions": recommendations[:8],
        "operator_note": "Treat recalled actions as guidance. Confirm current blast radius and rollback safety before execution.",
    }
    return result


def learn_from_postmortem(postmortem: dict[str, Any], client: LocalHindsightClient) -> dict[str, Any]:
    """Persist the reviewed root cause and effective resolution for future recall."""
    required = ("root_cause", "resolution_steps")
    missing = [key for key in required if not postmortem.get(key)]
    if missing:
        raise ValueError("postmortem missing required field(s): " + ", ".join(missing))
    steps = postmortem["resolution_steps"]
    if not isinstance(steps, list) or not all(isinstance(step, str) and step.strip() for step in steps):
        raise ValueError("resolution_steps must be a list of non-empty strings")
    memory = _incident_memory(postmortem, source="postmortem_learning")
    # Postmortems may use a different field for verified runbooks.
    books = postmortem.get("runbooks_that_worked", postmortem.get("runbooks", []))
    if not isinstance(books, list) or not all(isinstance(book, str) for book in books):
        raise ValueError("runbooks_that_worked must be a list of strings")
    memory["runbooks_that_worked"] = books
    memory["text"] += " " + " ".join(books)
    client.retain(memory)
    return {"stored": True, "incident_id": memory["incident_id"], "category": memory["category"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory", type=Path, default=DEFAULT_MEMORY, help=f"local mock memory file (default: {DEFAULT_MEMORY})")
    commands = parser.add_subparsers(dest="command", required=True)
    seed = commands.add_parser("seed", help="load generated historical incidents into memory")
    seed.add_argument("incidents", type=Path, nargs="?", default=Path("data/past_incidents.json"))
    respond = commands.add_parser("respond", help="recall relevant history for an alert JSON object")
    respond.add_argument("alert", type=Path, help="path to alert JSON")
    respond.add_argument("--limit", type=int, default=5)
    learn = commands.add_parser("learn", help="store a reviewed postmortem JSON object")
    learn.add_argument("postmortem", type=Path)
    args = parser.parse_args()
    client = LocalHindsightClient(args.memory)
    try:
        if args.command == "seed":
            print(json.dumps({"stored_incidents": seed_memory(client, args.incidents), "memory_file": str(args.memory)}, indent=2))
        elif args.command == "respond":
            if args.limit < 0:
                raise ValueError("--limit must be zero or greater")
            print(json.dumps(respond_to_alert(_read_object(args.alert), client, args.limit), indent=2))
        elif args.command == "learn":
            print(json.dumps(learn_from_postmortem(_read_object(args.postmortem), client), indent=2))
    except (MemoryError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
