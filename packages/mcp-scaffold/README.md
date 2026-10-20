# mcp-scaffold

Generates a new Python MCP service, once: the shared skeleton, the layers it asks for, its
Dockerfile and Helm chart, and its commit scope, release and pnpm registration. The `new-mcp`
skill asks what the MCP needs and runs it. From the repository root, with no uncommitted or
untracked changes, so git can undo a failed run:

```bash
uv run --project packages/mcp-scaffold mcp-scaffold new weather-mcp \
    --description "Current weather and forecasts for any city." \
    --upstream openapi --spec https://api.example.com/openapi.yml --persistence none --auth none
```

With `--spec`, the MCP starts from the spec's first JSON operation, a GET if there is one. It is
served as a tool straight from the spec, and typed through `mcp-openapi`'s codegen for when a
tool of our own replaces it. A spec given as a URL is recorded as `spec-source`, so
`mcp-openapi-codegen --refresh-spec` can fetch it again.

| Option | Choices |
|---|---|
| `--upstream` | `openapi` (mcp-openapi and codegen), `http` (an httpx2 client with retries), `custom` (written by hand) |
| `--spec` | The vendor's OpenAPI 3.0 spec, a path or an http(s) URL, JSON or YAML. `openapi` needs it |
| `--persistence` | `none`, or one or more of `postgres` (SQLAlchemy, asyncpg, Alembic, the chart's database) and `redis`, e.g. `--persistence postgres redis` |
| `--auth` | `none`, `unique` (recorded as pending until the Unique auth package exists) |
| `--no-release` | skip release-please and the release re-run list |

## After it runs

The MCP owns every file the scaffold wrote, and edits them freely. Nothing regenerates them. What
every MCP shares comes from the packages it depends on, so a fix reaches an MCP with a version
bump rather than a copy:

- `packages/mcp-runtime`: the settings with their defaults, the HTTP server with its host and
  origin guard (`run_server`, `http_app`), the telemetry setup (`init_telemetry`, `instrument`)
  and the retrying transport of a plain HTTP upstream (`RetryingTransport`).
- `packages/mcp-architecture`: `ARCHITECTURE.md`, which the generated `AGENTS.md` points to, the
  type check the MCP's `[tool.basedpyright]` extends, and the pytest plugin that checks the
  layers, the contracts, the folder rules, the code style and the type check on every
  `uv run pytest`.
- `packages/mcp-openapi`, for an OpenAPI upstream: the client and the codegen.

A change to the skeleton reaches the next MCP the scaffold makes, not the ones it made. When
something every MCP needs belongs in their code, put it in one of those packages instead.

## Versions

- The `service*` dependency groups here are the versions a new MCP pins from PyPI, one group
  per choice. They are not installed with the scaffold. Dependabot bumps them with every service
  in one pull request per dependency, so the next MCP starts current.
- A shared package from `packages/` is pinned at the version in its own `pyproject.toml`.

## Where things live

- `src/mcp_scaffold/files/skeleton/`: what every MCP gets, written for the placeholder package
  `mcp_skeleton`.
- `src/mcp_scaffold/files/layers/`: one folder per `--upstream` and `--persistence` choice.
- `src/mcp_scaffold/files/root/`: files outside the package a choice brings, such as `alembic.ini`.
- A file under `files/` named `*.jinja` depends on the combination of choices: the server,
  `tests/conftest.py`, `.env.example`, the Dockerfile, the chart's `values.yaml` and the
  persistence layer's `__init__.py` and `persistence.py`. Once every layer is copied,
  `render_templates` in `skeleton.py` renders each with the `Options` as `options` and drops
  the suffix.
- `src/mcp_scaffold/cli.py`: the `new` command.
- `src/mcp_scaffold/scaffold.py`: `scaffold()`, the steps in order. Each step is a module named
  for what it copies, writes or edits: `upstream.py` and `persistence.py` (the layer folders),
  `openapi.py` (the spec, its first operation, the codegen), `pyproject.py` (with `pins.py`),
  `agents.py` and `repository.py`. `skeleton.py` copies, renders and renames the
  skeleton, `commands.py` runs uv in the new service, and `options.py` holds what a new MCP
  asks for.

The architecture, its explanation and the checks the skeleton's tests run are in
`packages/mcp-architecture`, not copied into each MCP. The skeleton's `AGENTS.md` only points to
it, and `agents.py` adds what the MCP chose.

None of the files under `files/` is linted or type-checked here. They are checked where they
land:

- `tests/test_scaffold.py` generates one MCP per choice and runs its ruff, basedpyright and
  pytest.
