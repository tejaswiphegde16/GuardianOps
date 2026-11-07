# Incident Response Agent

A small Python command-line prototype that recalls prior incident resolutions,
suggests relevant runbooks, and learns from reviewed postmortems. It uses only
the Python standard library and stores its mock memory in a local JSON file.

## Requirements

- Python 3.9 or newer
- No third-party packages

Run all commands from this project directory. The scripts do not need a virtual
environment or dependency installation.

## Quick start

The synthetic corpus and example alert/postmortem are included. Seed memory,
then query it with the included alert:

```bash
python3 incident_response.py seed
python3 incident_response.py respond alert.json
```

The response is JSON with similar incidents, likely root causes, runbooks that
worked, and suggested actions. The agent does not execute remediation actions.

After an incident, review and edit `postmortem.json`, then persist its verified
root cause and resolution:

```bash
python3 incident_response.py learn postmortem.json
python3 incident_response.py respond alert.json
```

Memory is stored in `data/hindsight_memory.json` and survives process restarts.
Seeding the same incident corpus repeatedly replaces matching seeded entries
instead of adding duplicates. Learning a postmortem with the same ID replaces
its prior learned entry.

## Generate synthetic incident history

Regenerate the default 50 incidents:

```bash
python3 generate_incidents.py
```

Customize the count, deterministic random seed, and output path:

```bash
python3 generate_incidents.py --count 50 --seed 7 --output data/past_incidents.json
python3 incident_response.py seed data/past_incidents.json
```

The dataset covers container OOM kills, database pool exhaustion, API latency
spikes, node disk pressure, and queue backlogs. Each record contains timestamped
logs, impact, metrics, root cause, resolution steps, working runbooks, and
follow-up work. The records are synthetic and intended for demonstration.

## Input formats

An alert needs at least one searchable field (`summary`, `service`, `category`,
`error`, or `logs`). The sample `alert.json` shows a complete example.

A postmortem must include a non-empty `root_cause` and a `resolution_steps`
array of non-empty strings. It can also include `incident_id`, `service`,
`category`, `summary`, `error_logs`, and `runbooks_that_worked`. The `runbooks`
key is accepted as an alias for `runbooks_that_worked`.

## Commands

```text
python3 incident_response.py [--memory PATH] seed [INCIDENTS_JSON]
python3 incident_response.py [--memory PATH] respond ALERT_JSON [--limit N]
python3 incident_response.py [--memory PATH] learn POSTMORTEM_JSON
```

`--memory` selects an alternate local memory file. `respond --limit 0` is useful
for checking the alert output shape without returning matches.

## Hindsight integration boundary

`LocalHindsightClient` provides `recall(query, limit)` and `retain(memory)` as a
local stand-in. Recall currently ranks memories using token overlap and a
category match; it is not semantic vector search. Replace this adapter's two
methods with the Vectorize Hindsight SDK or REST calls to connect real Hindsight
memory, while keeping the incident loop and postmortem-learning flow intact.
The Hindsight endpoint, credentials, and exact SDK calls are intentionally not
assumed in this self-contained mock.

The local memory format is:

```json
{
  "memories": [
    {
      "source": "historical_incident",
      "incident_id": "INC-20250105-001",
      "category": "oom_kill",
      "service": "checkout-api",
      "text": "searchable incident summary and resolution",
      "root_cause": "...",
      "resolution_steps": ["..."],
      "runbooks_that_worked": ["RB-017 ..."]
    }
  ]
}
```

# GuardianOps