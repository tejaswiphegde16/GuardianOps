# Incident Response Agent

A terminal incident-response prototype that stores and retrieves incident
memories with Vectorize Hindsight Cloud, then uses Gemini to generate incident
analysis grounded in those memories. An optional local JSON mock supports
offline memory development.

## Requirements

- Python 3.9 or newer
- No third-party packages

Run all commands from this project directory. The scripts do not need a virtual
environment or dependency installation.

## Quick start

Create a memory bank in Hindsight Cloud and put its bank ID and API key in
`.env` as described below. Then seed the synthetic incident corpus and query
the included alert:

```bash
python3 incident_response.py seed
python3 incident_response.py respond alert.json
```

The response uses Hindsight recall to return similar incidents, likely causes,
runbooks, and suggested actions. The agent does not execute remediation actions.

For Gemini to analyze the alert and the memories recalled from Hindsight, pass
`--llm`:

```bash
python3 incident_response.py respond alert.json --llm
```

The alert and recalled memories are sent to Gemini. Remove secrets and sensitive
customer data before submitting them. Gemini's response is advisory and does not
execute infrastructure changes.

After an incident, review and edit `postmortem.json`, then persist its verified
root cause and resolution:

```bash
python3 incident_response.py learn postmortem.json
python3 incident_response.py respond alert.json
```

With Hindsight configured, memory is stored in your Hindsight Cloud bank and
persists across runs. With `--local`, it is stored in
`data/hindsight_memory.json`; local entries with matching source and incident ID
are replaced when learned again.

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
python3 incident_response.py [--memory PATH] respond ALERT_JSON --llm
python3 incident_response.py [--memory PATH] learn POSTMORTEM_JSON
```

`--memory` selects an alternate local memory file. `respond --limit 0` is useful
for checking the alert output shape without returning matches.

## API configuration

Open the [Hindsight Cloud console](https://ui.hindsight.vectorize.io) to create
or manage your memory bank and Hindsight API key. Create a Gemini API key in
[Google AI Studio](https://aistudio.google.com) as well. Put both providers'
credentials and settings in the project-root `.env` file:

```env
HINDSIGHT_API_KEY=your-hindsight-api-key
HINDSIGHT_API_URL=https://api.hindsight.vectorize.io
HINDSIGHT_BANK_ID=your-memory-bank-id
GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=gemini-3.8-flash
```

The script reads `.env` using Python's standard library; no dotenv package is
needed. Hindsight's key authenticates memory retain and recall requests;
Gemini's key is used only for language generation when `--llm` is passed. Keep
`.env` out of version control. `HINDSIGHT_API_URL` is optional for a dedicated
deployment. `GEMINI_MODEL` is optional and defaults to `gemini-3.8-flash`.
Gemini's free-tier quota is limited, and Google may use free-tier prompts to
improve its products. Use synthetic or redacted incident data.

When `HINDSIGHT_API_KEY` is configured, commands use Hindsight Cloud. Without
it, they use a local JSON mock. Use `--local` before the subcommand to force the
mock, for example `python3 incident_response.py --local seed`.

`HindsightRESTClient` calls Hindsight Cloud's retain and recall endpoints with
the configured API key and bank ID. `ask_gemini` sends the current alert and
recalled memories to Gemini's Interactions API using Python's standard-library
HTTP client. [Gemini API keys](https://ai.google.dev/gemini-api/docs/api-key),
[Gemini Interactions API](https://ai.google.dev/gemini-api/docs/interactions-overview),
and [Hindsight API
Integration](https://docs.hindsight.vectorize.io/cloud/api-integration/),
[Hindsight Recall](https://docs.hindsight.vectorize.io/cloud/recall/).

Historical incidents and postmortems are retained as text plus context metadata.
Hindsight performs semantic, keyword, entity, and temporal retrieval. The local
mock remains available for offline development; it ranks by token overlap and
is not a substitute for Hindsight retrieval.

The local mock memory format is:

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
