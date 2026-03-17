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
pnpm quality          # Helm chart linting
```

## Contributing

1. `pnpm install`
2. `docker-compose up -d`
3. Make changes, run `pnpm test`, `pnpm style`, `pnpm check-types`
4. Open a PR — releases are automated via [release-please](https://github.com/googleapis/release-please)
