# PR Proposal

## Title
`refactor(backstop-mcp): give tools to their features and wire collaborators with FastMCP DI`

## Description
- Move all nine tool modules from `server/tools/` into `features/<feature>/tools/`, assigned by
  the fetch function each one calls; extract `fetch_person` / `fetch_organization` into
  `org_people` so `get_person` and `get_organization` have a home by the same rule.
- Keep `server/tools/registry.py` hand-written — only its import paths change. A new
  `test_layering.py` rule asserts every tool module on disk appears in `TOOLS`, closing the
  "forgot to register it" gap. Automatic discovery is a follow-up with its own proposal.
- Delete `server/runtime.py` and its process-wide `Services` holder. Long-lived collaborators
  become `@lru_cache(maxsize=1)` providers (the `q-bridge-mcp` pattern from #747, since FastMCP's
  `Shared` resolves per-request without `pydocket`), and tools receive them as `Depends(...)`
  parameters, which stay out of the published tool schema.
- No changes to `backstop_client/`: `BackstopClientFactory.for_current_caller()` is kept
  verbatim, and the `attach_auth` cycle is broken by deferring the token-revocation hook rather
  than by restructuring the client.
- `create_app` drops its six config parameters and keeps only ASGI assembly; each config class
  gets one cached reader.
- Delete the `get_system_info` tool, which has no practical use. The `/system-info` endpoint
  stays as the credential-verification probe.
- Tool tests stop needing a Postgres container: injecting the client directly removes the
  `connect_user` / `install_services` scaffolding from ~3,900 lines of tests.
- Rewrite the service README around the new layout, with an "Adding a feature or tool" walkthrough
  so the next agent has one path to follow — the current Layout block describes two things this PR
  deletes and already omits four existing features.
