---
name: new-mcp
description: Starts a new Python MCP server in this repo with packages/mcp-scaffold. Use whenever the user asks to create, scaffold, bootstrap or add a new MCP, MCP server or connector service in Python. Asks what the MCP talks to (OpenAPI, plain HTTP, or another protocol such as SOAP), what it stores (Postgres, Redis or nothing) and whether it needs Unique auth, runs the scaffold, then fills in the upstream, the persistence and the first tool.
metadata:
  internal: true
---

# Start a new MCP

`mcp-scaffold` (in `packages/mcp-scaffold`) generates the service. It has the layers, the
architecture contracts, the Dockerfile, the Helm chart, and the release and commit-scope
registration. Your job is to find out what the MCP needs before running it, and to fill in what
the scaffold cannot know afterwards. Read `packages/mcp-architecture/ARCHITECTURE.md` first: it
is the contract the new service is checked against, and `services/architecture-demo-mcp` holds
every example it names.

## 1. Ask

Never guess these. Ask them in one round, with the AskUserQuestion tool when you have it:

| Question | Becomes |
|---|---|
| Name, kebab-case, ending in `-mcp` | `--name`, the service folder, package, chart and commit scope |
| One or two sentences on what it does for the user | `--description`, the server instructions and the pyproject description |
| What does it talk to? OpenAPI / plain HTTP without a spec / something else | `--upstream openapi\|http\|custom` |
| What does it store? Nothing, or any of Postgres and Redis (multi-select) | `--persistence none`, or every store chosen: `--persistence postgres redis` |
| Does it need the Unique auth package? | `--auth unique\|none` |

Then ask the follow-ups for what they chose, again in one round:

- **OpenAPI**: where the spec is, a URL or a file; it becomes `--spec`. Only OpenAPI 3.0 is
  read. Ask how it authenticates (bearer token, API key header, OAuth client credentials).
- **Plain HTTP**: the base URL, how it authenticates, and the endpoints the first tools need.
- **Something else**: the protocol, the Python library to use (for example `zeep` for SOAP),
  where its contract lives (a WSDL, a proto file), and how it authenticates.
- **Postgres or Redis**: what is stored, for how long, and who reads it.
- **Auth**: the Unique auth package does not exist yet. The scaffold records the choice in the
  new `AGENTS.md`; say so, and do not build auth yourself.

## 2. Scaffold

From the repository root:

```bash
uv run --project packages/mcp-scaffold mcp-scaffold new <name> \
    --description "<description>" --upstream <kind> [--spec <path or URL>] \
    --persistence <kind>... --auth <kind>
```

It refuses to start unless `git status` is clean, untracked files included. Ask the user to
commit or stash their changes; never do it for them. It ends by running `uv sync`, ruff,
basedpyright and pytest in the new service, and fails loudly if any of them does. Since it
started from a clean tree, everything it wrote is its own: undo a failed run with
`git checkout -- . && git clean -fd`.

It records the first `tests/tool_surface.generated.json`. Prefer a spec URL over a downloaded
file: it becomes `spec-source`, so `uv run mcp-openapi-codegen --refresh-spec` can fetch the
vendor's next version. The scaffold runs once: every file it wrote is the service's own from
here on, `mcp/server.py` and its middleware included.

## 3. Fill in the upstream

Everything here stays in `upstream/`, behind `Upstream`, `UpstreamSettings`, `open_upstream`
and `UpstreamError`.

- **OpenAPI**: the scaffold vendored the spec and started from its first JSON operation, a
  GET if there is one: served as a tool (`EXPOSED` in `upstream/routes.py`) and typed through
  the codegen (`operation-ids`). Tell the user which one. Then list the spec's operations as a
  table (operationId, method, path, summary) and ask which to serve as well. Add those to
  `EXPOSED`; that is the first version, with no code. If the API does not take a bearer token,
  change the header in `upstream/client.py` and the fields in `upstream/settings.py`.
- **Plain HTTP**: fix the auth header in `upstream/client.py`. Add pydantic models for the
  responses, so contexts never parse raw JSON.
- **Something else**: `uv add` the library. Implement the four names in `upstream/`, following
  the docstring in `upstream/__init__.py`. Then open it in the lifespan in `mcp/server.py` and
  add `get_upstream` to `mcp/dependencies.py`, mirroring how persistence is wired there.

Settings that every MCP shares (server, Postgres, Redis, Zitadel, retries, logging, elicitation)
come from `packages/mcp-runtime`. Use those classes and their defaults; never copy one into the
service. If every MCP needs something new, add it there rather than to one service.

Keep `.env.example` and the `env` block in `deploy/helm-charts/<name>/values.yaml` in step with
the settings. Secrets go only in `.env.example`, with a comment in `values.yaml` that the overlay
provides them.

## 4. Fill in the persistence

Each store is a field of `Persistence`: `persistence.database` for Postgres, `persistence.store`
for Redis.

- **Postgres**: add the models to `persistence/models.py`, then the functions the contexts call
  to `persistence/__init__.py`. `uv run alembic revision --autogenerate -m "<what>"` needs a
  database at `DATABASE_URL`. Start one locally with Docker, or write the first migration by
  hand into `persistence/migrations/versions/`.
- **Redis**: add the functions the contexts call, with the collection and TTL each entry uses.

## 5. Build the first feature and tool

For OpenAPI, this is promoting a served operation, when the user asks for a tool the spec
cannot give as it is: trimmed, renamed, with a rule, or merged from several operations.
Follow `packages/mcp-architecture/ARCHITECTURE.md`, using `services/architecture-demo-mcp` as the
model:
1. Write a feature under `contexts/<plural noun>/` with its queries and commands.
2. Write a tool under `mcp/tools/` that calls it.
3. Write a test in the style of the demo's `tests/test_tools.py`, with a fake upstream
   behind `httpx2.MockTransport` or a stub of the custom client.

Replace the 404-only `upstream_transport` fixture in `tests/conftest.py` with that fake.

## 6. Finish

- Write `README.md`: what the MCP does, its env variables, how to run it locally. The scaffold
  does not write one.
- If you changed `values.additional.schema.json`, run `scripts/render-values-schema.sh`.
- Each tool you added or served changes the tool surface. Read the snapshot test's diff, then
  accept it with `uv run pytest --regen-all`.
- Run `uv run pytest`, `uv run ruff format . && uv run ruff check .` and `uv run basedpyright`
  in the service.
- Tell the user what is registered and what is still theirs to do:
  - Registered: release-please, release-rerun and the `<name>` commit scope. Commit with that
    scope, e.g. `feat(<name>): ...`.
  - Still to do: the Argo overlay with the hostname, `MCP_BASE_URL` and the secrets, and auth
    if they asked for it.
