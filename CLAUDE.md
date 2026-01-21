# Claude Code Instructions

## General

- Don't write coauthoring or mention claude
- Use pnpm scripts from the root with filters
- Use `nix develop` to enter the development environment

## Project Structure

This is a pnpm monorepo with turbo for build orchestration.

```
services/           # Deployable services
  factset-mcp/
  outlook-mcp/
  sharepoint-connector/
  teams-mcp/

packages/           # Shared libraries
  aes-gcm-encryption/
  instrumentation/
  logger/
  mcp-oauth/
  mcp-server-module/
  probe/
```

## Common Commands

```bash
# Development
pnpm install                              # Install all dependencies
pnpm dev --filter=@unique-ag/<service>    # Start service in dev mode
pnpm build --filter=@unique-ag/<package>  # Build specific package

# Testing
pnpm test --filter=@unique-ag/<package>   # Run tests
pnpm test:e2e --filter=@unique-ag/<svc>   # Run e2e tests

# Code quality
pnpm style                                # Check with biome
pnpm style:fix                            # Fix with biome
pnpm check-types                          # TypeScript check
```

## Pull Requests

### Title (Conventional Commits)

PR titles must follow conventional commits format with strict scope validation. This becomes the squash commit message.

```
<type>(<scope>): <description>
```

### Description

Write PR descriptions naturally. No "Test plan" sections.

### Allowed Types

`feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `build`, `revert`

### Valid Scopes

| Scope | Files |
|-------|-------|
| `factset-mcp` | `services/factset-mcp/**` |
| `outlook-mcp` | `services/outlook-mcp/**` |
| `sharepoint-connector` | `services/sharepoint-connector/**` |
| `teams-mcp` | `services/teams-mcp/**` |
| `aes-gcm-encryption` | `packages/aes-gcm-encryption/**` |
| `instrumentation` | `packages/instrumentation/**` |
| `logger` | `packages/logger/**` |
| `mcp-oauth` | `packages/mcp-oauth/**` |
| `mcp-server-module` | `packages/mcp-server-module/**` |
| `probe` | `packages/probe/**` |
| `ci` | `.github/**` |
| `main` | Root files (`*`, `.*`) |
| `deps` | `**/package.json`, `pnpm-lock.yaml` |

### Multi-Scope

When changing files in multiple services/packages, use comma-separated scopes:

```
feat(teams-mcp,mcp-oauth): add shared auth feature
```

### Breaking Changes

Breaking changes require BOTH:
1. `!` after the scope: `feat(teams-mcp)!: remove API`
2. `BREAKING CHANGE:` footer in PR body

## Infrastructure

Deploy folders contain:
- `terraform/` - Azure infrastructure (Entra apps, secrets)
- `helm-charts/` - Kubernetes deployments
- `Dockerfile` - Container builds
