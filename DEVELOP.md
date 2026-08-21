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
