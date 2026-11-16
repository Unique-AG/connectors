# Semgrep MCP (semgrep/semgrep, `semgrep mcp`)

| Field | Value |
|---|---|
| Vendor | Semgrep; official |
| Category | dev-platform |
| Tier | 3 |
| Source | open (https://github.com/semgrep/semgrep @ 06d9993, `cli/src/semgrep/mcp/`) |
| Language / SDK | Python, `mcp==1.29.0` (built-in `mcp.server.fastmcp.FastMCP`) |
| Hosted endpoint | https://mcp.semgrep.ai/sse (README install badge; `SEMGREP_IS_HOSTED` enables `semgrep_scan_remote`) |
| Uses elicitation | yes (behind an env flag that is off by default) |
| Mechanism | legacy `elicitation/create` request |
| Evidence type | code |

## Elicitation usages

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| `semgrep_scan`, `semgrep_scan_remote` (both through `semgrep_scan_core`, then the CLI or RPC path) and `semgrep_scan_with_custom_rule`, after the scan, **once per finding**, only when `SEMGREP_FINDINGS_ELICITATION_ENABLED=true` | form | `other (finding triage: label each finding true / false positive for telemetry)` | "🔍 Semgrep Finding Detected: [`<severity>`] `<rule_id>` (`<path>:<line>:<col>`)". Three required booleans: `true_positive`, `false_positive`, `skip` (not mutually exclusive; the first true one wins) | The finding is left out of all three buckets. The scan result returned to the model is the same either way; the answers only feed span attributes / `add_mcp_findings_metrics` | [server.py#L508](https://github.com/semgrep/semgrep/blob/06d9993409f6698f78f6956cd39d968e7f4d7b6a/cli/src/semgrep/mcp/server.py#L508), [server.py#L539](https://github.com/semgrep/semgrep/blob/06d9993409f6698f78f6956cd39d968e7f4d7b6a/cli/src/semgrep/mcp/server.py#L539), [models.py#L22](https://github.com/semgrep/semgrep/blob/06d9993409f6698f78f6956cd39d968e7f4d7b6a/cli/src/semgrep/mcp/models.py#L22), callers [#L887](https://github.com/semgrep/semgrep/blob/06d9993409f6698f78f6956cd39d968e7f4d7b6a/cli/src/semgrep/mcp/server.py#L887), [#L1087](https://github.com/semgrep/semgrep/blob/06d9993409f6698f78f6956cd39d968e7f4d7b6a/cli/src/semgrep/mcp/server.py#L1087), [#L1136](https://github.com/semgrep/semgrep/blob/06d9993409f6698f78f6956cd39d968e7f4d7b6a/cli/src/semgrep/mcp/server.py#L1136) |

## Fallback without client elicitation support

The only gate is the server-side env flag `SEMGREP_FINDINGS_ELICITATION_ENABLED`
([utils.py#L104](https://github.com/semgrep/semgrep/blob/06d9993409f6698f78f6956cd39d968e7f4d7b6a/cli/src/semgrep/mcp/utilities/utils.py#L104)),
which defaults to `false`. When it is off, the scans skip elicitation and log "Findings elicitation
is not enabled, skipping."

When the flag is on, the code never checks the client's `elicitation` capability. A client that
rejects `elicitation/create` produces an `McpError`, which the scan tools re-raise unchanged
(`except McpError as e: raise e`), so the whole scan fails. Read statically, not run.

## Other human-in-the-loop mechanisms

None for writes. The server only reads: it scans code and returns findings, and writes nothing
upstream. No `readOnlyHint` / `destructiveHint` annotations are set. Opt-in env flags gate risky
behaviour, for example `ALLOW_SCAN_OUTSIDE_WORKSPACE`.

## Notes

- This is the only usage in the batch where elicitation collects **product feedback /
  labelled data** (TP/FP triage) rather than gating an action. The answers change nothing the model
  sees.
- One prompt per finding can mean dozens of sequential dialogs on a noisy scan, with no batching
  and no cap.
- The flag is server-wide and set by env var. There is no per-user or per-call opt-in, so it reads
  like an internal or experimental data-collection feature.
- A boolean triple is used where an enum would have suited better. Accepting with all three false
  silently drops the finding.
