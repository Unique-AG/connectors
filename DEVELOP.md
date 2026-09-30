## Quick Start

**Option A: Nix (recommended)**

```bash
nix develop  # or: direnv allow (.envrc is committed)
```

Provides all required tools (Node.js 26, pnpm, terraform, kubectl, helm, etc.) with pinned versions.

**Option B: Manual**

- Node.js 26
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
```

## Helm Chart Tests

Charts keep [helm-unittest](https://github.com/helm-unittest/helm-unittest) suites in a `tests/` directory. CI runs `helm lint . --strict` and `helm unittest .` in the chart directory, after `helm dependency update`. If the chart has a `ci-values.yaml` file, the lint command also gets `--values ci-values.yaml`.

To run the same commands on your machine, use Helm v3.19.0. This is the version that CI uses, and a newer version can report more problems. Install the plugin once with `helm plugin install https://github.com/helm-unittest/helm-unittest`. Then run the commands in the chart directory, as CI does.

## Release Workflows

release-please opens one release pull request for each service. Merge it to start `[Release] Please`. The workflow handles each released service that has a Helm chart. It builds the image from the release tag and signs it. It also pushes the chart, scans the image, and publishes the docs in `services/<service>/docs` to Confluence.

If a release stops halfway, do not use "Re-run failed jobs" on the `release-please` job. That job finds no release the second time. Run `[Release] Manual Re-Run` instead. Start it from `main`, choose the service, and type the version without a leading v.

The re-run builds from the release tag and reuses an image that exists. If only one registry has the image, it copies the image to the other registry. It never overwrites a released tag. It does not publish docs. Use it as a last resort.

To publish docs before a release, run `[Docs] Publish to Confluence` from `main` and choose the docs directory. Use it also when the docs job of a release failed.

Both manual workflows list the services in a dropdown. When you add a service, add it to `release-rerun.yaml`, and to `docs-confluence.yaml` if it has docs.

## Runners

Jobs run on `ubuntu-24.04`, not on `ubuntu-latest`. A change of the default image by GitHub cannot change a build.

Short jobs that need no Docker run on `ubuntu-slim`. This runner has one vCPU and stops a job after 15 minutes. It has no Docker daemon. GitHub gives it no version label, so GitHub can update its image.

Jobs that build images, scan images, or run Docker stay on `ubuntu-24.04`.

## Python Services

Services that carry a `pyproject.toml` (`services/office-365-mcp`, ...) sit outside the pnpm/turbo
workspace and are driven by [uv](https://docs.astral.sh/uv/). For each selected service, the `[CI] Python` workflow runs:

```bash
pnpm install --frozen-lockfile          # from the repo root, for biome
cd services/<service>
uv sync --locked
uv run ruff format --check . && uv run ruff check .
pnpm exec biome check .
uv run basedpyright
uv run pytest
```

Changes under `packages/mcp-credential-auth` run the same uv formatting, linting, type-checking,
and test sequence in that package. They also add its consuming services to the service matrix.
Directly changed Python services are included in the same matrix rather than being replaced by
the shared-package consumers.

`ruff` owns `.py`. The biome step covers the JSON a Python service also ships, mostly its Helm
chart inputs, on the same terms as a TypeScript service. See `AGENTS.md` for what biome excludes.

biome arrives through `pnpm install --frozen-lockfile` rather than `npx`, so the binary that runs is
the one `pnpm-lock.yaml` pins. `--frozen-lockfile` also fails if `package.json` and the lockfile
disagree on the version, which a runtime `npx` fetch would silently ignore. It is the same
acquisition path the TypeScript CI uses, so there is one mechanism to understand rather than two.

No workflow caches the pnpm store with `actions/cache`. No workflow that installs packages runs on
`main`, so a store cache can never land on `refs/heads/main`, which means every PR misses on its
first job and then writes a 177 MB entry of its own. The repo's Actions cache already sits above its
10 GB limit, so those entries evict the `setup-uv` caches this same job depends on. A cold
`pnpm install` costs about 8s; the restore-plus-save round trip cost 13s and made things worse.
The Node workflow had the same cache until it was removed. It hit in 7 of 67 jobs and saved under one
second.

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

## Releases

Release-please owns every version. Two root settings in `release-please-config.json` exist only to
make a **new service's first release** come out right:

- `initial-version` — the version a service gets when it has no prior release. Seed a new service at
  `0.0.0` in `.release-please-manifest.json` (and in `pyproject.toml`/`package.json`, the Helm
  `version`/`appVersion`, and the image `tag`). Release-please treats `0.0.0` as "never released" and
  takes the first version straight from `initial-version`. Seeding `0.1.0` instead makes release-please
  read it as *already shipped* and propose `0.2.0`.
- `bootstrap-sha` — where the commit scan stops while any service is still unreleased. It points at
  `2f56700`, an **empty** commit (no files) that carries a repo-wide `BREAKING-CHANGE:` footer for the
  tag-format change. Release-please attributes file-less commits to *every* package, so without this
  boundary that footer lands in each new service's first changelog. It only takes effect while some
  service lacks a release, and is ignored once they all have one.

Do not move `bootstrap-sha` forward: it must stay **older** than every service's last release, or
services whose last release falls outside the scan window start re-listing already-released commits.
