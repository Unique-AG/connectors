# Connectors repo instructions

## PR titles

Before creating or updating a PR title, read `.gitcommitizen` to verify the scope matches all changed files. The pattern is `scope = last path segment` (e.g. `packages/logger` → `logger`), with one exception: `pnpm-lock.yaml` and root `package.json` require scope `deps`.
