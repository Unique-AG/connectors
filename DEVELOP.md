## Quick Start

**Option A: Nix (recommended)**

```bash
nix develop  # or: direnv allow (.envrc is committed)
```

Provides all required tools (Node.js 24, pnpm, terraform, kubectl, helm, etc.) with pinned versions.

**Option B: Manual**

- Node.js >= 24
- pnpm (version in `package.json` `packageManager` field)

```bash
pnpm install
docker-compose up -d  # third-party dependencies
```

## Key Scripts

```bash
pnpm build            # build all
pnpm test             # unit tests
pnpm test:e2e         # e2e tests
pnpm style            # lint/format (Biome)
pnpm style:fix        # auto-fix
pnpm check-types      # type checking
pnpm check-all        # style + types + tests + syncpack
pnpm fix-all          # auto-fix style + syncpack
pnpm quality          # Helm chart linting
```

## Python Services

Services that carry a `pyproject.toml` (`services/office-mcp`, ...) sit outside the pnpm/turbo
workspace and are driven by [uv](https://docs.astral.sh/uv/). `Python CI` runs exactly this:

```bash
cd services/<service>
uv sync --frozen
uv run ruff format --check . && uv run ruff check .
uv run basedpyright
uv run pytest
```

### Trap: basedpyright in a git worktree

`[tool.basedpyright]` pins `venvPath = "."` and `venv = ".venv"`, so basedpyright resolves imports
against `services/<service>/.venv` — the environment `uv sync` creates. A fresh `git worktree` has
no `.venv`, and basedpyright then resolves no third-party package. It does not fail; it reports
thousands of phantom `reportUnknown*` and `reportMissingImports` errors, which reads like the branch
is broken.

Run `uv sync` inside the worktree — that is what CI does, and it makes every command above work
unchanged. To reuse another checkout's environment instead, invoke its basedpyright and hand it that
environment:

```bash
OTHER=/path/to/other/checkout/services/<service>
"$OTHER/.venv/bin/basedpyright" --venvpath "$OTHER"
```

`--venvpath` names the directory that *contains* `.venv`, not `.venv` itself, and the command line
overrides the `pyproject.toml` value. Do not reach for `uv run` here: it syncs a `.venv` into the
worktree, which is the first option, not this one.

The config stays as it is on purpose. basedpyright performs no variable expansion on `venvPath`, so
there is no env-var-driven path to move it to, and deleting the setting would hand import resolution
to whichever `python` comes first on `PATH` — silently wrong when it picks the wrong one, which is a
poor trade for a local-only inconvenience.

## Contributing

1. `pnpm install`
2. `docker-compose up -d`
3. Make changes, run `pnpm check-all`
4. Open a PR — releases are automated via [release-please](https://github.com/googleapis/release-please)
