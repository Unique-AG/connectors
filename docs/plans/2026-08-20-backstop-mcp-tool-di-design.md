# Design: backstop-mcp feature-owned tools and FastMCP dependency injection

## Problem

Three coupled problems in `services/backstop-mcp`:

1. **Tools live away from the features they call.** `server/tools/get_accounts_for_party.py` is
   the presentation half of `features/accounts`, but sits in a different package. Reading a
   feature end to end means opening two trees.

2. **The tool list is hand-maintained.** `server/tools/registry.py` names every tool by hand, so
   adding one is two edits and forgetting the second silently ships a tool nobody can call.
   *Deferred* — automatic discovery is designed separately in
   `2026-08-20-backstop-mcp-tool-discovery-design.md`, which builds on this one. Here the
   registry stays and a layering-test rule closes the "forgot the second edit" gap.

3. **Tools reach their collaborators through a process-wide global.** `server/runtime.py` holds
   one `Services` dataclass installed by `configure_services()` at startup, because FastMCP was
   assumed to call tool functions with a plain signature. That assumption is stale — FastMCP
   3.4.5 has a real dependency-injection engine. The global costs a `reset_services()` teardown
   hook, an autouse fixture in `tests/conftest.py`, and — most expensively — it forces every
   tool test to stand up a Postgres container and store a real credential just so
   `for_current_caller()` has something to find.

## Solution

### Overview

Tools move into `features/<feature>/tools/` and receive their collaborators as `Depends(...)`
parameters instead of reaching for a global. `server/runtime.py` is deleted;
`server/tools/registry.py` stays as it is, with only its import paths updated.

Long-lived collaborators become `@lru_cache(maxsize=1)` provider functions — the pattern from
`q-bridge-mcp` (PR #747). `create_app` keeps only ASGI assembly: routes, middleware, lifespan.

No CQRS query/handler layer. Feature functions (`resolve_party`, `fetch_activities_page`,
`fetch_opportunities`) already take their collaborators as explicit arguments — they are handlers
already. A dispatcher would re-implement, one layer lower, what `Depends` does at the tool
boundary.

### Why `lru_cache` and not `Shared`

FastMCP exports `Shared(...)` for app-scoped singletons. **It does not work in this service.**
FastMCP only opens a `SharedContext` at lifespan scope when `pydocket` is installed; without it,
`fastmcp/server/context.py:290` opens a fresh one per `Context`, so every request re-resolves.
Measured with three calls to one tool:

```
pool#1 shared_calls=1
pool#2 shared_calls=2      # three calls, three "singletons"
pool#3 shared_calls=3
```

A `Shared` `BackstopClientFactory` would build a new httpx connection pool per request.
`@lru_cache(maxsize=1)` gives the same app-scoped singleton with no extra dependency.

### Architecture

#### Dependency providers

**Root — `backstop_mcp/dependencies.py`.** Cross-cutting providers. Cannot live under `server/`:
`features/` may not import `server/` (layering rule 1), and feature tools need these.

```python
@lru_cache(maxsize=1)
def get_backstop_config() -> BackstopConfig: return BackstopConfig()
# ... one cached provider per config class: app, backstop, database, encryption, auth,
#     activity_history. One reader each, so nothing can re-read the environment behind you.

@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine: ...
@lru_cache(maxsize=1)
def get_session_factory() -> async_sessionmaker[AsyncSession]: ...
@lru_cache(maxsize=1)
def get_encryption_key() -> bytes: ...

@lru_cache(maxsize=1)
def get_backstop_client_factory() -> BackstopClientFactory:
    factory = BackstopClientFactory(
        transport_settings(get_backstop_config()), retry_settings(get_backstop_config())
    )
    factory.attach_auth(BackstopAuthContext(
        session_factory=get_session_factory(),
        encryption_key=get_encryption_key(),
        revoke_tokens_for_subject=_revoke_subject_tokens,   # deferred — see below
    ))
    return factory

async def _revoke_subject_tokens(subject: str) -> None:
    await get_auth_provider().revoke_all_tokens_for_subject(subject)

@lru_cache(maxsize=1)
def get_auth_provider() -> BackstopOAuthProvider:
    return BackstopOAuthProvider(..., backstop_clients=get_backstop_client_factory(), ...)

async def get_backstop_client(                                  # per-call, not cached
    factory: BackstopClientFactory = Depends(get_backstop_client_factory),
) -> BackstopClient:
    return await factory.for_current_caller()
```

`transport_settings` / `retry_settings` move here from `app.py`, bodies unchanged. They cannot
live in `backstop_client/` — layering rule 3 forbids the transport from seeing config — and
`dependencies.py` cannot import `app.py`.

**The `attach_auth` cycle.** The auth context needs the OAuth provider's revocation hook; the
provider needs the factory to verify credentials at login (`factory.py:124-131`). Two cached
providers cannot express that directly — `lru_cache` does not populate until the call *returns*,
so a mutual reference recurses forever. It is broken by deferring the hook: nothing invokes
`revoke_tokens_for_subject` until a mid-session 401 actually fires, long after both caches are
warm. So `get_auth_provider()` → `get_backstop_client_factory()` → returns. No cycle, no new
types.

**Per-feature — `features/<feature>/dependencies.py`**, exported through the feature's
`__init__` so layering rule 4 still holds: `custom_fields.get_custom_fields_service`,
`opportunities.get_opportunity_stages_service`, `data_hygiene.get_employment_index_factory`,
`activity_history.get_activity_history_settings` (which performs the `Config → Settings`
translation `create_app` does today).

**Teardown — `backstop_mcp/teardown.py`** (amended during implementation; the design had
`close_singletons()` in `dependencies.py`). Clearing the feature-owned caches means naming those
features, and `features/<f>/dependencies.py` imports `backstop_mcp.dependencies` — so putting the
teardown there is an import cycle, function-local imports or not, and `basedpyright` reports it
as one. A separate module imports both sides at the top level and nothing imports it back. Its
`PROVIDERS` tuple is the whole of what a teardown clears, and `tests/test_teardown.py` fails when
a cached provider is missing from it — the same two-edit gap rule 7 closes for tools.

**Nothing in `backstop_client/` changes.** No edits to `client.py`, `factory.py`,
`credential.py`. `for_current_caller()` already resolves the in-flight caller's credential
through the injected `CallerAuthContext` and wires the 401→revoke hook; it is kept verbatim.
Only *who calls the constructor* changes. `attach_auth` is kept as-is; the deferred hook would
now allow one-shot construction via the `auth=` constructor parameter, but removing the method
is a separate, optional change.

#### How dependencies compose

A tool declares only what it uses. Everything beneath resolves itself, verified by probe:

```
tool schema:  {'party_id': {'type': 'string'}}     # Depends params are invisible to the model
call 1        built: [pool, caller, client, settings, resolver]
call 2        built: [caller, client, resolver]    # pool, settings are process-wide
diamond       one instance per call when two collaborators ask for the same dependency
direct call   overriding the top of the chain builds nothing beneath it
```

The per-call cache means a tool reaching for the Backstop client twice resolves the caller's
credential once — today each `runtime.get_backstop_client()` hits the database again.

#### Tool layout

```
features/accounts/
  __init__.py  api_responses.py  internal_dto.py  responses.py
  fetch_accounts_for_party.py  fetch_product_positions.py  …
  dependencies.py                    # only where the feature owns a service
  tools/
    __init__.py
    get_accounts_for_party.py        # exactly one FunctionTool, bound to `get_accounts_for_party`
    get_product_positions.py
```

| Tool | Home | Assigned by |
|---|---|---|
| `get_accounts_for_party` | `accounts` | `fetch_accounts_for_party` |
| `get_product_positions` | `accounts` | `fetch_accounts_for_product`, `fetch_product_positions` |
| `get_activity_history` | `activity_history` | `fetch_activities_page` |
| `get_activity_detail` | `activity_history` | `fetch_activity_detail` |
| `get_opportunities` | `opportunities` | `fetch_opportunities` |
| `list_custom_fields` | `custom_fields` | `CustomFieldsService` |
| `get_people_for_party` | `org_people` | `fetch_people_for_organization` |
| `get_person` | `org_people` | extracted `fetch_person` |
| `get_organization` | `org_people` | extracted `fetch_organization` |
| `get_system_info` | *deleted* | no practical use |

`get_person` and `get_organization` call no feature fetch function today — both inline
`client.get(path, schema=BackstopApiResourceDocument[…])`. That fetch is extracted into
`org_people/fetch_person.py` and `org_people/fetch_organization.py` first, which is what places
the tools. `server/tools/utils/activity_history.py` becomes
`features/activity_history/tools/_page_input.py` (rule 6 already allows `_`-prefixed private
shared modules).

Tool modules keep declaring their own input and output models — a tool's models are that tool's
wire contract, and keeping them beside it means one file to read. A per-tool `responses.py` is
available later if one grows too large.

Deleting `get_system_info` removes only the tool. The `/system-info` endpoint stays in use as
the credential-verification probe (`backstop_client/factory.py:40`).

#### Registration

`server/tools/registry.py` keeps naming every tool by hand, and `create_app` keeps registering
from `TOOLS`. Only the import lines change, to the new `features/<f>/tools/` paths. The
`server/tools/` package therefore ends up holding just `registry.py` and its `__init__`.

Automatic discovery is deliberately out of this change and has its own design doc,
`2026-08-20-backstop-mcp-tool-discovery-design.md`. It depends on the tool move landing first,
and is worth deciding on its own rather than inside a DI swap.

New rule 7 in `test_layering.py` covers the gap the registry leaves in the meantime: every tool
module under `features/<f>/tools/` must appear in `TOOLS`, so forgetting the second edit fails
the suite rather than shipping an unreachable tool.

#### `create_app`

Loses all six config parameters and all collaborator construction. Keeps: `configure_logging`,
`configure_metrics`, the `FastMCP` instance, registration from `TOOLS`, `setup_ops`,
the `/ready` `/login` routes, middleware, and a lifespan whose `finally` calls
`close_singletons()`.

### Error Handling

**Registration is unchanged.** A tool missing from `registry.py` is caught by rule 7 in the test
suite rather than at runtime, and an unimportable tool module still fails at import of the
registry — that is, at startup, as today.

**Resolution-time exceptions.** Verified by probe: a `ToolError` subclass raised inside a
provider reaches the MCP client identically to one raised in the tool body, message intact.
`NotConnectedError` (`features/auth/context.py:14`) is a `ToolError`, so moving it from the tool
body into `get_backstop_client` resolution changes nothing for the caller. Any *non*-`ToolError`
raised during resolution is wrapped by FastMCP as `RuntimeError: Failed to resolve dependency
'<name>' for <tool>` — so a database outage during credential lookup surfaces as that rather
than the raw SQLAlchemy error. Both already reach the client as an opaque tool error. The rule
this implies: providers raise `ToolError` subclasses for anything the caller must act on.

**Tool-body errors are unchanged.** `BackstopApiError`, `BackstopAuthError`,
`BackstopRateLimitError` are raised from inside the tool exactly as today.

**Teardown ordering is preserved.** `close_singletons()` runs the client factory's `aclose()`,
then `engine.dispose()`, then `cache_clear()` on every cached provider. The lifespan still stops
the auth sweep task before the engine goes, as `create_app`'s current comment requires.

### Testing Strategy

**Tool tests stop needing Postgres.** Today `tests/server/tools/conftest.py`'s `connect_user`
exists only so `for_current_caller()` can find a stored credential, which drags a testcontainer
and a Fernet key into every tool test. Under DI the test passes the client directly:

```python
result = await get_person(party_id="p1", client=fake_client, employment_index=factory)
```

Overriding at the top of the chain builds nothing beneath it, so ~3,900 lines of tool tests lose
the `db` fixture, `connect_user`, and `install_services`.

**Moves.** `tests/server/tools/test_get_*.py` → `tests/features/<feature>/tools/`. Assertions are
unchanged; only fixture setup changes. `test_output_descriptions.py` and `test_models.py` stay
at `tests/server/`, still driven by `TOOLS`.

**Deletions.** `tests/server/tools/test_get_system_info.py` goes with its tool. Its
`NotConnectedError` and revoke-on-401 cases are already covered at `tests/test_app.py:129`,
`tests/features/auth/test_context.py:67-92`, and `tests/test_backstop_client.py:99-131`.

**New.** Rule 7 in `tests/test_layering.py` (below) is the only addition: it asserts every tool
module on disk appears in `TOOLS`, so a tool file that never gets registered fails the suite.

**Amended.** `tests/conftest.py`'s autouse `_reset_runtime` becomes `close_singletons()`, for the
same event-loop reason as today. In `tests/test_app.py`, the three config-injection tests
(lines 135-187) convert to `monkeypatch.setenv` + `cache_clear()`, and `get_services().x`
assertions become provider calls. In `tests/test_layering.py`: rule 4 notes that `tools/` modules
may be imported directly by their own tests and by `registry.py`, as `server/tools/*` is today;
rule 5 exempts `tools/`, which declare their own models; and a new rule 7 asserts every tool
lives at `features/<f>/tools/<name>.py`, defines exactly one `FunctionTool` bound to `<name>`,
and appears in `TOOLS`. `backstop_mcp.server.tools` stays in `_PUBLIC_SURFACE_PACKAGES`.

## Out of Scope

- A CQRS query/handler bus or dispatcher.
- Automatic tool discovery — its own design doc,
  `2026-08-20-backstop-mcp-tool-discovery-design.md`, to be decided separately.
- Collapsing the now single-module `server/tools/` package into `server/tools.py`.
- `pydocket` / FastMCP `Shared` dependencies.
- Any change to `backstop_client/` internals.
- Removing `attach_auth` in favour of the `auth=` constructor parameter.
- Any change to tool names, descriptions, parameters, or output schemas. This is a pure
  refactor; the only MCP surface change is `get_system_info`'s removal.
- Re-homing features beyond the tool moves listed above.

## Tasks

1. **Delete `get_system_info`** - Remove the tool module, its registry entry, and
   `tests/server/tools/test_get_system_info.py`. Leave `/system-info` in
   `backstop_client/factory.py`, which uses it as the credential-verification probe.

2. **Add `backstop_mcp/dependencies.py`** - Cached providers for the six configs, engine,
   session factory, encryption key, client factory and auth provider, plus the per-call
   `get_backstop_client` and `close_singletons()`. Move `transport_settings` / `retry_settings`
   here from `app.py`. `create_app` builds from these providers and drops its config parameters,
   still feeding `configure_services` so `runtime.py` keeps working meanwhile.

3. **Add per-feature `dependencies.py`** - Cached providers for `CustomFieldsService`,
   `OpportunityStagesService`, `EmploymentIndexFactory` and `ActivityHistorySettings`, each
   exported through its feature's `__init__`.

4. **Extract `fetch_person` and `fetch_organization`** - Move the inline `client.get` from
   `get_person` / `get_organization` into `org_people`, alongside the record models they need.

5. **Move tool modules and their tests into features** - Mechanical move of nine tool modules to
   `features/<f>/tools/` and their tests to `tests/features/<f>/tools/`, plus
   `tools/utils/activity_history.py` → `activity_history/tools/_page_input.py`. Update the
   import lines in `server/tools/registry.py`, and `test_layering.py` rules 4, 5 and 7, in the
   same pass.

6. **Add rule 7 to `test_layering.py`** - Assert every tool module under `features/<f>/tools/`
   defines one `FunctionTool` named after its file and appears in `TOOLS`, so the registry can
   stay hand-written without a tool going unregistered.

7. **Convert tools to `Depends`, one feature at a time** - Replace each
   `runtime.get_*()` call with a `Depends(...)` parameter, and rewrite that tool's tests to pass
   collaborators explicitly and drop the `db` / `connect_user` fixtures.

8. **Delete `server/runtime.py`** - Once no tool references it: remove the module,
   `install_services` and the `Services` construction in `tests/helpers.py`, and swap
   `tests/conftest.py`'s autouse `_reset_runtime` for `close_singletons()`.

9. **Update the layering and package documentation** - `features/__init__.py`,
   `server/__init__.py`, `app.py` and `test_layering.py` docstrings all describe the runtime
   holder and the old `server/tools/` location; rewrite them to describe providers and
   feature-owned tools.

10. **Rewrite `services/backstop-mcp/README.md` as the path for the next feature** - Its Layout
    block still lists `runtime.py` and `server/tools/`, both deleted here, and its `features/`
    list already omits `accounts/`, `opportunities/`, `org_people/` and `includes/`. Replace it
    with the post-refactor tree, and add an **Adding a feature or tool** section that walks the
    actual sequence: create `features/<name>/` with the `api_responses` → `internal_dto` →
    `responses` model layers; put the fetch in a module named after the function it defines; add
    `dependencies.py` with an `@lru_cache(maxsize=1)` provider only if the feature owns a
    long-lived service, exported through `__init__`; add `tools/<tool_name>.py` defining exactly
    one `FunctionTool` bound to a symbol matching the filename; declare collaborators as
    `Depends(...)` parameters, which stay out of the published schema; and write the test under
    `tests/features/<name>/tools/`, passing collaborators as kwargs rather than standing up a
    database. State the two rules an agent will otherwise break — a tool is registered by being
    added to `server/tools/registry.py` as well as written, and nothing under `features/` may
    import `server/` — and point at `tests/test_layering.py` as the enforcement of both.
