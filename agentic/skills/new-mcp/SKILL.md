---
name: new-mcp
description: Starts a new Python MCP server in this repo with packages/mcp-scaffold. Use whenever the user asks to create, scaffold, bootstrap or add a new MCP, MCP server or connector service in Python. Asks whether the MCP talks to an upstream (an OpenAPI spec, or one the agent writes a client for with the user, or none) what it stores (Postgres, Redis or nothing) and whether users sign in with their own upstream credentials, runs the scaffold, then writes the upstream client, the auth, the persistence and the first tool.
metadata:
  internal: true
---

# Start a new MCP

`mcp-scaffold` (in `packages/mcp-scaffold`) generates the service. It has the layers, the
architecture contracts, the server with its host and origin guard, the telemetry, the
Dockerfile, the Helm chart, and the release and commit-scope registration. It is a command-line
tool: never import from it. Your job is to find out what the MCP needs before running it, and to
write what the scaffold cannot know afterwards: the upstream client when there is no OpenAPI
spec, the auth, the persistence and the tools. Read `packages/mcp-architecture/ARCHITECTURE.md`
first: it is the contract the new service is checked against. Its "Use what exists before writing
code" section applies to every step below: look in FastMCP and the shared packages before you
write anything of your own.

## 1. Ask

Never guess these. Ask them in one round, with the AskUserQuestion tool when you have it:

| Question | Becomes |
|---|---|
| Name, kebab-case, ending in `-mcp` (the scaffold refuses any other) | `<name>`, the first argument: the service folder, package, chart and commit scope |
| One or two sentences on what it does for the user | `--description`, the server instructions and the pyproject description |
| Does it call an upstream, a system of its own such as a vendor API? If so, does it publish an OpenAPI 3.0 spec we can use? | `--upstream openapi` with `--spec`, `--upstream custom`, or no `--upstream` at all |
| What does it store? Nothing, or any of Postgres and Redis (multi-select) | no `--persistence`, or every store chosen: `--persistence postgres redis` |
| Do users sign in with their own username and password for the upstream, so each call acts as them? | `--auth credentials`, which needs an upstream and Postgres; otherwise no `--auth`, and step 4 settles the auth |
| Will it be released and deployed, or is it an example or experiment? | nothing, or `--no-release`, which skips release-please and the release re-run list |

Then ask the follow-ups for what they chose, again in one round:

- **OpenAPI**: where the spec is, a URL or a file; it becomes `--spec`. Only OpenAPI 3.0 is
  read. Pass a URL as it is. Save a file you download outside the repository, such as in
  `/tmp`, since the scaffold refuses to run beside an untracked file. mcp-openapi's `OperationClient` is the typed client, so there is no client to write.
- **No usable spec**: work out the client with the user before you write it. Ask what protocol
  it speaks (REST without a spec, GraphQL, SOAP, gRPC, a vendor SDK), the Python library to use
  if it is not plain HTTP (for example `zeep` for SOAP), where its contract lives (docs, a WSDL,
  a proto file), the base URL, the endpoints the first tools need and what each returns, and
  its rate limits. The client's auth is covered in step 4.
- **No upstream**: nothing to ask. The MCP works over its own storage or logic alone, and
  `upstream/` stays an empty layer until it needs one.
- **Postgres or Redis**: what is stored, for how long, and who reads it.

`--auth credentials` is the one sign-in the scaffold writes: the MCP is the OAuth server its
clients use, each user signs in on its `/sign-in` page with their credentials for the upstream,
which the upstream checks, and every call reaches the upstream as that user. Any other auth, such
as Zitadel or a machine token, step 4 settles with the user. Without `--auth`, `run_server`
refuses to serve beyond loopback until the server has an auth provider.

## 2. Scaffold

From the repository root:

```bash
uv run --project packages/mcp-scaffold mcp-scaffold <name> \
    --description "<description>" [--upstream openapi|custom] [--spec <path or URL>] \
    [--persistence postgres|redis ...] [--auth credentials] [--no-release]
```

It refuses to start unless `git status` is clean, untracked files included. Ask the user to
commit or stash their changes; never do it for them. It ends by running `uv sync`, ruff, the
codegen's drift check for an OpenAPI upstream, basedpyright, import-linter,
`poe architecture` and pytest in the new service, and fails loudly if any of them does. Since it
started from a clean tree, everything it wrote is its own: a failed run prints the command that
undoes it, `git checkout . && git clean -fdx services/<name>`, to run from the repository root. It
also removes the service's ignored `.venv` and caches, which would otherwise stop the next run.

When a check fails, here or in any later change, fix the code. Never loosen a rule in
`pyproject.toml`, a contract or a file-wide comment to make it pass: CI checks only what that
configuration says, so loosening it hides the failure instead of fixing it. If no fix works, stop
and ask the user.

Every file it writes starts with a `mcp-scaffold-commit: <commit>, timestamp: <when>` comment,
the same in every file of the run. Leave it in place on a file you edit. Never add one to a file
you write, not even when you copy a stamped file as a starting point, and drop it from a
scaffold file you rewrite from scratch: the stamp marks what the scaffold wrote, not what you
did.

It records the first `tests/tool_surface.generated.json`. Prefer a spec URL over a downloaded
file: it becomes `spec-source`, so `uv run poe codegen --refresh-spec` can fetch the
vendor's next version. The scaffold runs once: every file it wrote is the service's own from
here on, `mcp/server.py`, `mcp/http.py`, `mcp/middleware.py` and `telemetry/setup.py` included.

## 3. Write the upstream client

Skip this step for an MCP without an upstream. To add one later, scaffold a throwaway MCP with
the same options plus `--upstream custom` (or `openapi`) on a branch, diff it against this one,
and carry over what differs:

- the client by these rules into the empty `upstream/`, opened in the lifespan in
  `mcp/server.py`, and `get_upstream` in `mcp/dependencies.py`;
- the `mcp-openapi` dependency and its `[tool.uv.sources]` entry in `pyproject.toml`, since
  every client retries with its `RetryAfterPolicy`;
- `COPY packages/mcp-openapi` in `deploy/Dockerfile`, or the image's `uv sync --frozen` fails;
- the fake upstream in `tests/conftest.py` and `tests/offline_server.py`;
- the `UPSTREAM_*` variables in `.env.example`.

Everything here stays in `upstream/`, behind `Upstream`, `UpstreamSettings`, `open_upstream`
and `UpstreamError`.

- **OpenAPI**: the scaffold vendored the spec and started from its first JSON operation, a
  GET if there is one: served as a tool (`EXPOSED` in `upstream/routes.py`) and typed through
  the codegen (`operation-ids`). Tell the user which one. Then list the spec's operations as a
  table (operationId, method, path, summary) and ask which to serve as well. Add those to
  `EXPOSED`; that is the first version, with no code. Retries are `RetryAfterPolicy`, set up in
  `open_upstream`. If the API does not take a bearer token, change the header in
  `upstream/client.py` and the fields in `upstream/settings.py`.
- **Custom**: `upstream/client.py` is a starting point, not a finished client: `Upstream` with
  one `request(method, path, adapter, params=..., json=...)`, retries on `RetrySettings`, and
  `tests/test_upstream.py` covering it. Shape it to what you worked out with the user in step 1,
  or replace it for a protocol that is not HTTP, keeping the four names. `uv add` any library it
  needs.

### Rules for coding a client

1. **Auth.** Find out how the upstream takes credentials: a bearer token, an API key header or
   query parameter, basic auth, OAuth client credentials, a signed request, or the signed-in
   user's own token. A credential of the MCP's own is a `SecretStr` in `UpstreamSettings`, set
   once on the client. A credential of the user's reaches the client as step 4 describes, never
   from a global.
2. **Typed.** Every method the contexts call returns a pydantic model, validated before it is
   returned: `request` parses the body with the `TypeAdapter` it is given, and a body that does
   not fit is an `UpstreamError`. No `dict`, `Any` or raw JSON leaves `upstream/`. Put the models
   in `upstream/` (for example `upstream/responses.py`) and export what contexts need from
   `upstream/__init__.py`. Map vendor field names to snake_case in the contexts, as
   ARCHITECTURE.md says.
3. **Retries.** The custom client retries with mcp-openapi's `RetryAfterPolicy`
   (`packages/mcp-openapi/src/mcp_openapi/retry.py`), built from `RetrySettings` in
   `open_upstream`: a status in `statuses` after its `Retry-After` (seconds or an HTTP-date) or
   an exponential backoff with jitter, never past `max_wait_seconds`, at most `max_attempts`,
   any request on a 429 and only an idempotent one on another status. Keep it when you change
   the client. Check the upstream's docs for a status or header it adds, such as a 502 or
   `X-RateLimit-Reset`: a new status goes in `statuses`, and a new header needs a `RetryPolicy`
   of its own, passed to `Upstream` in place of `RetryAfterPolicy`.
4. **Concurrency.** Check whether the upstream limits concurrent requests, per key or per user.
   If it does, base the limit on mcp-openapi's `LockConfig` and `RequestLock`
   (`packages/mcp-openapi/src/mcp_openapi/lock.py`, used in `OperationClient._attempt`): hold the
   lock around each attempt, release it while a retry waits, time only acquiring it, and turn a
   timeout into an `UpstreamError`. An `asyncio.Semaphore` suits one pod; a Postgres advisory
   lock or a Redis lock suits several.
5. **Boundary.** The client lives in `upstream/`. Everything outside imports it from
   `<package>.upstream` only; mcp-architecture's `protected` contract fails on
   `from <package>.upstream.client import Upstream`. `upstream/` imports neither `mcp` nor
   `contexts`, and nothing from auth.
6. **Tests.** Cover each rule above against `httpx2.MockTransport`, as
   `tests/test_upstream.py` does.

Settings that every MCP shares (server, Postgres, Redis, Zitadel, retries, logging, elicitation)
come from `packages/mcp-configs`. Use those classes and their defaults; never copy one into the
service. If every MCP needs a new setting, add it there rather than to one service.

Keep `.env.example` and the `env` block in `deploy/helm-charts/<name>/values.yaml` in step with
the settings. Secrets go only in `.env.example`, with a comment in `values.yaml` that the overlay
provides them.

## 4. Settle the auth

**Scaffolded with `--auth credentials`**: the sign-in works as it is, with HTTP Basic auth and a
username and password. Shape three things to the upstream, and nothing in `mcp/auth/` or
`persistence/auth/` unless the user asks:

- `auth_for` in `upstream/credentials.py`: how a request is signed with a user's credentials,
  such as a header of the vendor's own in place of Basic auth. The sign-in check and every call
  go through it.
- `UpstreamCredentials` in `shared/contracts/auth.py`: what the upstream needs per user. A field
  added there needs a column in `persistence/auth/` and a field on the sign-in form.
- `UPSTREAM_VERIFY_PATH`, which has no default: a GET the upstream answers 2xx to right
  credentials and 401 or 403 to wrong ones, such as the vendor's "current user" endpoint. Never a
  public page: anything that answers 2xx to wrong credentials signs anyone in as anyone.

`guides/auth.md` in `packages/mcp-architecture` says which layer owns what, and how a request
takes credentials of its own. Set `MCP_AUTH_ENCRYPTION_KEY` in the overlay's secrets.

**Otherwise**, ask the user, in one round: who uses the MCP and how they sign in (Unique's Zitadel, another
OIDC or OAuth provider, a static token for a machine client, or nobody because it stays local),
and whether the upstream needs the signed-in user's own credentials or only the MCP's.

If it stays local, leave it: `run_server` keeps it on loopback. Otherwise write it.

### Rules for coding auth

1. **FastMCP first.** Read the installed FastMCP before writing anything
   (`.venv/lib/python3.14/site-packages/fastmcp/server/auth/`): `JWTVerifier`,
   `StaticTokenVerifier`, the introspection verifier, `OAuthProxy`, `OIDCProxy`, and the
   providers under `fastmcp.server.auth.providers`. For Zitadel, use
   `unique_mcp.auth.zitadel.create_zitadel_oidc_proxy`, configured by the environment
   `ZitadelSettings` in `mcp-configs` reads; the scaffold does not add `unique-mcp`, so add it
   with the version `architecture-demo-mcp` pins. If one of them does the job, pass it to
   `FastMCP(auth=...)` in `create_server` and write nothing else.
2. **Our code in `mcp/auth/`.** Only what FastMCP and `unique_mcp` lack goes there, exported
   from `mcp/auth/__init__.py`. Its settings are built on `shared_config` and passed in from
   `main.py`, so tests pass their own.
3. **The client reads it through a `Depends` function.** As the OpenAPI client gets its
   `Upstream` from `get_upstream`, a client that needs the caller's credentials gets them in
   `get_upstream` in `mcp/dependencies.py`, for example from
   `fastmcp.server.dependencies.get_access_token()`.
4. **Clear boundaries.** No auth detail reaches a context or `upstream/`. The client receives,
   through its constructor, either the details themselves or a function that returns them,
   whichever suits the case: the details when they are fixed for the request, a function when
   they can change during it, such as a token that is refreshed.
5. **Tests.** Test that a request without credentials is refused and one with them reaches the
   tool, and that the upstream receives the caller's credential. `run_server` serving beyond
   loopback is already covered in `tests/test_server.py`.

## 5. Fill in the persistence

Each store is a field of `Persistence`: `persistence.database` for Postgres, `persistence.store`
for Redis.

- **Postgres**: add the models to `persistence/models.py`, then the functions the contexts call
  to `persistence/__init__.py`. `uv run alembic revision --autogenerate -m "<what>"` needs a
  database at `DATABASE_URL`. Start one locally with Docker, or write the first migration by
  hand into `persistence/migrations/versions/`. Alembic runs ruff over each revision it writes.
- **Redis**: add the functions the contexts call, with the collection and TTL each entry uses.

The tests need neither store running: the `persistence` fixture in `tests/conftest.py` opens
SQLite and a `MemoryStore` in their place, and every client a test opens shares it. Seed it
through the functions in `persistence/__init__.py`.

## 6. Build the first feature and tool

For OpenAPI, this is promoting a served operation, when the user asks for a tool the spec
cannot give as it is: trimmed, renamed, with a rule, or merged from several operations.
Follow `packages/mcp-architecture/ARCHITECTURE.md` and its guides `guides/contexts.md` and
`guides/mcp.md`:
1. Write a feature under `contexts/<plural noun>/`, and re-export what the tool calls from
   `contexts/__init__.py`.
2. Write a tool under `mcp/tools/` that calls it, imported from `<package>.contexts`.
3. Write a test that calls the tool through a real FastMCP `Client`, with a fake upstream
   behind `httpx2.MockTransport`.

Replace the 404-only `upstream_transport` fixture in `tests/conftest.py` with that fake.

## 7. Finish

- Write `README.md`: what the MCP does, its env variables, how to run it locally. The scaffold
  does not write one.
- If you changed `values.additional.schema.json`, run `scripts/render-values-schema.sh`.
- Each tool you added or served changes the tool surface. Read the diff
  `uv run poe architecture` prints, then accept it with `uv run poe surface`.
- Run `uv run poe ci` in `services/<name>`: every check CI runs, in its order.
- Tell the user what is registered and what is still theirs to do:
  - Registered: the `<name>` commit scope, and release-please and release-rerun unless it ran
    with `--no-release`. Commit with that scope, e.g. `feat(<name>): ...`.
  - Still to do: the Argo overlay with the hostname, `MCP_BASE_URL` and the secrets, and auth
    if it was left for later.
