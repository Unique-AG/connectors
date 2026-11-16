# Monarch Money MCP Server

| Field | Value |
|---|---|
| Vendor | Rob Cerda (community; not affiliated with Monarch Money) |
| Category | banking (personal finance aggregation) |
| Tier | 2 |
| Source | open (https://github.com/robcerda/monarch-mcp-server @ 60051e3) |
| Language / SDK | Python, `mcp[cli]>=1.30.0,<3` (uv.lock pins `mcp` 1.30.0; imports `mcp.server.mcpserver` first so it also runs on `mcp` 2.x) |
| Hosted endpoint | none (stdio, or self-hosted streamable HTTP) |
| Uses elicitation | yes |
| Mechanism | legacy `elicitation/create` request (via FastMCP `ctx.elicit`) |
| Evidence type | code |

## Elicitation usages

Permalink base: `https://github.com/robcerda/monarch-mcp-server/blob/60051e35c9e8e86147575db1d2bdc157291d925b/`

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| `monarch_login` | form | secret-input | "Sign in to Monarch Money." Schema `LoginForm {email: str, password: str}` | `action != "accept"` -> tool returns text "Login cancelled.", nothing stored | [auth.py#L60-L70](https://github.com/robcerda/monarch-mcp-server/blob/60051e35c9e8e86147575db1d2bdc157291d925b/src/monarch_mcp_server/auth.py#L60-L70), [tools/auth.py#L40](https://github.com/robcerda/monarch-mcp-server/blob/60051e35c9e8e86147575db1d2bdc157291d925b/src/monarch_mcp_server/tools/auth.py#L40) |
| `monarch_login`, second round when Monarch raises `RequireMFAException` | form | secret-input (MFA code) | "Enter your Monarch Money MFA code." Schema `MFAForm {mfa_code: str}` | "Login cancelled." | [auth.py#L81-L94](https://github.com/robcerda/monarch-mcp-server/blob/60051e35c9e8e86147575db1d2bdc157291d925b/src/monarch_mcp_server/auth.py#L81-L94) |
| `monarch_login_with_token` | form | secret-input | "Paste your Monarch Money session token." Schema `TokenForm {token: str}` (description tells the user to copy it from browser DevTools -> Local Storage) | "Login cancelled."; blank token -> "Empty token — aborting." | [auth.py#L105-L121](https://github.com/robcerda/monarch-mcp-server/blob/60051e35c9e8e86147575db1d2bdc157291d925b/src/monarch_mcp_server/auth.py#L105-L121), [tools/auth.py#L51](https://github.com/robcerda/monarch-mcp-server/blob/60051e35c9e8e86147575db1d2bdc157291d925b/src/monarch_mcp_server/tools/auth.py#L51) |

Stated rationale (module docstring and tool descriptions): credentials go client UI -> server over the protocol and never appear in tool arguments or the model's context ([auth.py#L1-L5](https://github.com/robcerda/monarch-mcp-server/blob/60051e35c9e8e86147575db1d2bdc157291d925b/src/monarch_mcp_server/auth.py#L1-L5)). The resulting session is saved to the OS keyring.

## Fallback without client elicitation support

- No capability check. The server does not read the client's declared `elicitation` capability; it sends the request and inspects the failure.
- If the installed SDK has no `Context.elicit` (`mcp` < 1.10), the tool returns an upgrade hint that also points to the terminal script `python login_setup.py` ([auth.py#L20-L27](https://github.com/robcerda/monarch-mcp-server/blob/60051e35c9e8e86147575db1d2bdc157291d925b/src/monarch_mcp_server/auth.py#L20-L27), [#L38](https://github.com/robcerda/monarch-mcp-server/blob/60051e35c9e8e86147575db1d2bdc157291d925b/src/monarch_mcp_server/auth.py#L38)).
- If the client answers `-32601 Method not found` (matched by substring on the exception text), the tool returns a text result telling the user to use `monarch_login_with_token` and paste a DevTools token ([auth.py#L29-L35](https://github.com/robcerda/monarch-mcp-server/blob/60051e35c9e8e86147575db1d2bdc157291d925b/src/monarch_mcp_server/auth.py#L29-L35), [#L65-L68](https://github.com/robcerda/monarch-mcp-server/blob/60051e35c9e8e86147575db1d2bdc157291d925b/src/monarch_mcp_server/auth.py#L65-L68)). Any other exception is re-raised.
- The real out-of-band fallback is the terminal script `login_setup.py` (email/password, email OTP, MFA, or browser cookies), advertised by `setup_authentication` ([tools/auth.py#L17-L37](https://github.com/robcerda/monarch-mcp-server/blob/60051e35c9e8e86147575db1d2bdc157291d925b/src/monarch_mcp_server/tools/auth.py#L17-L37)). Credentials never become tool arguments on any path.

## Other human-in-the-loop mechanisms

- `MONARCH_MCP_READ_ONLY` env var: an explicit `MUTATING_TOOLS` set (33 tools, including the three login/logout tools and `refresh_accounts`) is never registered ([read_only.py#L27-L74](https://github.com/robcerda/monarch-mcp-server/blob/60051e35c9e8e86147575db1d2bdc157291d925b/src/monarch_mcp_server/read_only.py#L27-L74), [#L92-L110](https://github.com/robcerda/monarch-mcp-server/blob/60051e35c9e8e86147575db1d2bdc157291d925b/src/monarch_mcp_server/read_only.py#L92-L110)). Off by default.
- `dry_run: bool = False` on bulk/structural writes (`bulk_update_transactions`, `bulk_categorize_transactions`, `update_account`, `upload_account_balance_history`, `update_category`) returns planned changes without writing ([accounts.py#L186](https://github.com/robcerda/monarch-mcp-server/blob/60051e35c9e8e86147575db1d2bdc157291d925b/src/monarch_mcp_server/tools/accounts.py#L186)).
- `confirm_rollover_reset: bool` argument on `update_category`: a rollover reset without it (and without `dry_run`) returns an error asking for the flag ([categories.py#L327](https://github.com/robcerda/monarch-mcp-server/blob/60051e35c9e8e86147575db1d2bdc157291d925b/src/monarch_mcp_server/tools/categories.py#L327)).
- README "Recommended: require approval for mutating tools" tells users to keep client-side approval prompts on, citing prompt injection via merchant names and memos read back from transactions.
- No `readOnlyHint` / `destructiveHint` annotations on any tool. `delete_transaction`, `delete_transaction_rule`, `merge_merchants` have no confirm argument.

## Notes

- Elicitation is used only for credential capture, never for confirming the many financial write tools, which rely on dry-run/confirm arguments and client approval instead.
- The "client lacks elicitation" message sends the user to `monarch_login_with_token`, which also elicits, so in such a client that advice loops; only `login_setup.py` works.
- The SDK range allows `mcp` 2.x. In `mcp` 2.3.0 a connection with no back-channel (2026-07-28 stateless) raises `NoBackChannelError` (serialised as `INVALID_REQUEST`), which the substring match on "Method not found" / "-32601" does not catch, so the login tools would surface a raw error there. Not migrated to `InputRequiredResult`.
- Tests cover accept, decline, MFA and the missing-`elicit` path; none exercises the `-32601` branch ([tests/test_auth.py#L258](https://github.com/robcerda/monarch-mcp-server/blob/60051e35c9e8e86147575db1d2bdc157291d925b/tests/test_auth.py#L258)).
