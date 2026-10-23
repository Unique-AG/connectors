# mcp-scaffold

Generates a new Python MCP service, once: the shared skeleton, the layers it asks for, its
Dockerfile and Helm chart, and its commit scope, release and pnpm registration. The `new-mcp`
skill asks what the MCP needs and runs it. From the repository root, with no uncommitted or
untracked changes, so git can undo a failed run:

```bash
uv run --project packages/mcp-scaffold mcp-scaffold weather-mcp \
    --description "Current weather and forecasts for any city." \
    --upstream openapi --spec https://api.example.com/openapi.yml
```

A run that fails partway leaves what it wrote. From the repository root, this undoes it, the
`.venv` and caches git ignores included:

```bash
git checkout . && git clean -fdx services/weather-mcp
```

It is a command-line tool for agents and people, never a library: nothing imports
`mcp_scaffold`, and no MCP depends on it. What MCPs share at run time comes from the packages
listed under [After it runs](#after-it-runs).

With `--spec`, the MCP starts from the spec's first JSON operation, a GET if there is one. It is
served as a tool straight from the spec, and typed through `mcp-openapi`'s codegen for when a
tool of our own replaces it. A spec given as a URL is recorded as `spec-source`, so
`mcp-openapi-codegen --refresh-spec` can fetch it again.

| Option | Choices |
|---|---|
| `--upstream` | `openapi` (mcp-openapi's typed client and codegen), `custom` (a small HTTP client to start from, which the agent shapes to the upstream with the user). Leave it out for an MCP without an upstream client: `upstream/` stays an empty layer |
| `--spec` | The vendor's OpenAPI 3.0 spec, a path or an http(s) URL, JSON or YAML. `openapi` needs it |
| `--persistence` | One or more of `postgres` (SQLAlchemy, asyncpg, Alembic, the chart's database) and `redis`, e.g. `--persistence postgres redis`. Leave it out for an MCP that stores nothing |
| `--auth` | `credentials`: each user signs in on the MCP's `/sign-in` page with their own credentials for the upstream, kept encrypted in Postgres, and every call reaches the upstream as them. Needs an `--upstream` and `--persistence postgres`. Leave it out for an MCP that starts without sign-in |
| `--no-release` | skip release-please and the release re-run list |

A `custom` upstream starts as `upstream/client.py`: one `request(method, path, adapter)` that
parses every body into a pydantic model, retried by mcp-openapi's `RetryAfterPolicy` built from
`RetrySettings`. An upstream with a status or header of its own gets another `RetryPolicy`.

There is no auth option. Every MCP starts without auth, and `run_server` refuses to serve beyond
loopback until the server has an auth provider. The `new-mcp` skill works out the auth with the
user and has the agent write it.

## The stamp

Every file the scaffold writes starts with the same comment, in the file's own syntax:

```
# mcp-scaffold-commit: 3f2a9c1e5b7d, timestamp: 2026-10-21T09:30:00+00:00
```

The commit is the one the scaffold ran from, which the clean tree it requires makes exact, and
the timestamp the moment the run started, the same in every file of one run, so a file tells
which scaffold wrote it. A Dockerfile's `# syntax=` line and a
shebang stay first, and a JSON schema takes it as `"$comment"`. What a tool writes is not
stamped: `uv.lock`, the codegen's `upstream/generated/` modules, the tool surface
snapshot and the chart's `values.schema.json`, which `scripts/render-values-schema.sh`
regenerates. Nor is an Alembic migration: the stamp in `script.py.mako` is a Mako comment,
which the revisions it renders leave out. Only the run stamps, so a file an agent or a person
writes afterwards has none, and must not be given one by hand. A file type without a known
comment syntax fails the run, so a new kind of skeleton file needs an entry in `stamp.py`.

## After it runs

The MCP owns every file the scaffold wrote, and edits them freely. Nothing regenerates them. What
every MCP shares comes from the packages it depends on, so a fix reaches an MCP with a version
bump rather than a copy:

- `packages/mcp-configs`: the settings with their defaults.
- `packages/mcp-architecture`: `ARCHITECTURE.md`, which the generated `AGENTS.md` points to, the
  code style and import contracts its commands check, the type check its `[tool.basedpyright]`
  extends, and `poe architecture`, which checks what a client sees of the server
  `tests/offline_server.py` builds.
- `packages/mcp-openapi`, for an OpenAPI upstream: the client and the codegen.

The server with its host and origin guard (`mcp/http.py`, `mcp/middleware.py`) and the
telemetry setup (`telemetry/setup.py`) are the MCP's own code, not a package's. A change to the
skeleton reaches the next MCP the scaffold makes, not the ones it made. When something every MCP
needs belongs in their code, put it in one of those packages instead.

## Versions

- The `service*` dependency groups here are the versions a new MCP pins from PyPI, one group
  per choice. They are not installed with the scaffold. Dependabot bumps them with every service
  in one pull request per dependency, so the next MCP starts current.
- A shared package from `packages/` is pinned at the version in its own `pyproject.toml`.

## Where things live

- `src/mcp_scaffold/files/skeleton/`: what every MCP gets, written for the placeholder package
  `mcp_skeleton`.
- `src/mcp_scaffold/files/layers/`: one folder per `--upstream` and `--persistence` choice, and
  `auth/` for `--auth credentials`, laid over the `mcp`, `persistence`, `shared` and `upstream`
  layers.
- `src/mcp_scaffold/files/root/`: files outside the package a choice brings, such as `alembic.ini`
  or a custom upstream's `tests/test_upstream.py`.
- A file under `files/` named `*.jinja` depends on the combination of choices. Once every layer
  is copied, `render_templates` in `skeleton.py` renders each and drops the suffix, with the
  `Options` as `options`, the `VendorSpec` as `spec`, the upstream's `api_url` and the
  `Dependencies` from `pyproject.py` as `dependencies`.
- `src/mcp_scaffold/cli.py`: the `new` command.
- `src/mcp_scaffold/scaffold.py`: `scaffold()`, the steps in order. Each step is a module named
  for what it copies, writes or edits: `upstream.py`, `persistence.py` and `auth.py` (the layer
  folders),
  `openapi.py` (the spec, its first operation, the codegen), `pyproject.py` (the dependencies,
  with `pins.py`), `repository.py` and `stamp.py`. `skeleton.py` copies, renders and renames the
  skeleton, `commands.py` runs uv in the new service, and `options.py` holds what a new MCP
  asks for.

The architecture, its explanation and the checks the skeleton's tests run are in
`packages/mcp-architecture`, not copied into each MCP. The skeleton's `AGENTS.md` only points to
it, and says what the MCP chose.

None of the files under `files/` is linted or type-checked here. They are checked where they
land:

- `tests/test_scaffold.py` generates one MCP per choice and runs every check `commands.check`
  runs on a new MCP: ruff, the codegen's drift check, basedpyright, `lint-imports`,
  `poe architecture` and pytest.
