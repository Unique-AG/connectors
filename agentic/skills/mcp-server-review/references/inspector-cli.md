# Inspector CLI cheat sheet (v2)

Invoke with `pnpm --silent dlx "$INSPECTOR" --cli ...`, where `INSPECTOR` is
`MCP_INSPECTOR_PKG` if set, else the pinned default on the `INSPECTOR=` line of
`scripts/mcp-snapshot.sh`. The pin lives only there.
One invocation = one request. Flags first, stdio command last. Add `--format json`
for parsing; stdout is the result, stderr is diagnostics (last stderr line on failure
is a JSON error envelope).

## Methods

`initialize` (connect probe: serverInfo, protocolVersion, capabilities, instructions),
`tools/list`, `tools/call`, `resources/list`, `resources/read`, `resources/templates/list`,
`prompts/list`, `prompts/get`, `logging/setLevel`. Streaming/session-only methods
(`logging/tail`) are rejected.

## Useful flags

| Need | Flag |
|------|------|
| Remote | `--transport http\|sse --server-url <url>` (a `/mcp` or `/sse` URL path infers transport) |
| Named server from file | `--config <file> --server <name>` (read-only) |
| Protocol era | `--protocol-era legacy\|auto\|modern` |
| Schema portability | `--strict` on `tools/list` (exit 6 on errors; findings under `schemaFindings`) |
| Call a tool | `--method tools/call --tool-name <n> --tool-args-json '{"id":"123"}'` |
| Read resource | `--method resources/read --uri <uri>` |
| Get prompt | `--method prompts/get --prompt-name <n> --prompt-args k=v` |
| Save raw result | `--output <file>` (`--output-format raw` for text/bytes) |
| Connect timeout | `--connect-timeout <ms>` (default 15000) |

`--tool-arg k=v` JSON-coerces values (`zip=10001` becomes a number); use
`--tool-args-json` for ids and zip codes.

## Exit codes

0 ok, 1 usage/unexpected, 3 auth failed/required, 4 unreachable, 5 tool error
(`isError:true`) or tool not found, 6 `--strict` schema error, 11 rate limited (429),
12 OAuth destination guard refused a URL. Capture with `cmd || status=$?`, and before
piping to `jq`.

## Auth, non-interactive

- Static: `--header "Authorization: Bearer $MCP_TOKEN"`.
- OAuth stored token: `--stored-auth-only` (exit 3 instead of opening a browser),
  `--use-stored-auth`, `--list-stored-auth` (preflight). If OAuth is required and no
  token is stored, ask the user to authenticate interactively once, or supply a header.
- Do not set `MCP_AUTO_OPEN_ENABLED=true`.

## Probe patterns

Error semantics (expect exit 5 and an actionable message, not a stack trace):

```bash
pnpm --silent dlx "$INSPECTOR" --cli --method tools/call \
  --tool-name <tool> --tool-args-json '{}' --format json <target flags> || echo "exit=$?"
```

Result size (bytes) of a read-only list tool:

```bash
... --method tools/call --tool-name <tool> --tool-args-json '<args>' --format json | wc -c
```

Negative auth (non-prod only): re-run `initialize` with a wrong-audience or expired
token; expect exit 3, never a successful list.

Load testing (`--load*`) exists; do not run it from this skill.
