# Recorded Polixis data

Polixis's answers, recorded once so the MCP can be developed and tested without spending the API
key's quota, or without a Polixis API key at all: replay answers from these recordings and sends
nothing to Polixis. Everything here but this README is gitignored: it is licensed Polixis content about
real people and real companies, and this repository is public. Never commit it, paste it into a
ticket or pull request, or upload it anywhere but the place below.

## Download

The archive is in the team's 1Password:
https://start.1password.com/open/i?a=3LI3FEGI2JFDFPO75NUVVF6ED4&v=z734ohz7wq5ngzkuw6nemx3kh4&i=obxy7w2sgt3ozjoeuxkhhocxci&h=unique-team.1password.com

Download it and unpack it by hand here, in `services/polixis-mcp/.mock-server-data/`, so that `cassettes/` sits beside
this README. To make a new archive, zip this folder whole: everything lives in its subfolders.

## What it holds

| Path | |
|---|---|
| `cassettes/` | One JSON file per Polixis request: the request (method, path, query, body) and Polixis's answer. No header, token or secret is saved |
| `cassettes/ledger.jsonl` | One line per request sent to Polixis while recording, across every run: its time, route and status. Its line count is what the recordings have cost the API key's quota |
| `cassettes/HALT` | Present only after a recording run got a quota 429; nothing is sent until it is deleted |
| `cassettes-superseded/` | Recordings replaced by a newer answer to the same request, kept for comparison |
| `cases/` | Case lists: the tool calls a recording run makes, naming the real entities they screen |
| `runner/record_cases.py` | Runs a case list through the MCP's tools in process, and prints what each call cost in Polixis requests and returned in bytes |
| `tool-results/` | What each tool returned in the last run of a case list, for review |
| `research/` | The exploration of the live API: raw responses, probe scripts, Polixis's PDF, `FINDINGS.md` and `QUESTIONS.md` |

## Use it

Run from `services/polixis-mcp`. Replay answers from `cassettes/` and sends nothing to Polixis:

```bash
MCP_AUTH_MODE=none UPSTREAM_RECORDING_MODE=replay uv run polixis-mcp
MCP_AUTH_MODE=none UPSTREAM_RECORDING_MODE=replay \
  uv run python .mock-server-data/runner/record_cases.py .mock-server-data/cases/cases.yaml
```

A request with no recording fails, saying which. To record it, run in `record` mode with a
budget, the most requests the ledger may hold, here 10 more than it holds now:

```bash
MCP_AUTH_MODE=none UPSTREAM_RECORDING_MODE=record UPSTREAM_RETRY_MAX_ATTEMPTS=1 \
  UPSTREAM_RECORDING_BUDGET=$(( $(wc -l < .mock-server-data/cassettes/ledger.jsonl) + 10 )) \
  uv run python .mock-server-data/runner/record_cases.py .mock-server-data/cases/cases.yaml
```

Record mode answers a recorded request from its recording and sends only the others, waits two
seconds between two, and stops at the budget and at the first quota 429. "Record Polixis once,
replay it after" in the service's `README.md` describes every setting.

After recording, upload a new archive to the place above, so the others replay the same answers.
