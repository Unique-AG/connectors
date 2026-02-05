# Project Instructions

## General

- Don't write coauthoring or mention claude
- Use pnpm scripts from the root with filters

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

## Code Comments

- Only add comments for complex algorithms, unexpected behavior, or non-obvious business logic
- Add JSDoc comments only for complex methods with multiple parameters or intricate logic
- Avoid obvious comments that just restate what the code does

## Code Style

- Avoid the use of `any`. Always use proper types or `unknown` with a type guard.
- When `any` is absolutely necessary (e.g., testing private methods, untyped third-party libraries), add a biome-ignore comment with explanation:
  ```typescript
  // biome-ignore lint/suspicious/noExplicitAny: Mock override private method
  vi.spyOn(service as any, 'validatePKCE').mockReturnValue(true);
  ```
- Add export only when what you are exporting is actually used in another file

## Import Ordering

- Follow this import order:
  1. Node.js built-in modules (e.g., `import { createHmac } from 'node:crypto'`)
  2. External packages (e.g., `import { UnauthorizedException } from '@nestjs/common'`)
  3. Testing utilities (e.g., `import { TestBed } from '@suites/unit'`)
  4. Internal modules and types
- Group related imports together
- Order imports alphabetically within each group when practical

## Generated Files

- Don't create README files for generated code

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

### Title

PR titles must follow conventional commits format. This becomes the squash commit message.

```
<type>(<scope>): <description>
```

### Description

Keep concise - ends up in commit history. No "Test plan" sections.

```
<summary of changes>

- bullet points of what changed
- keep it brief
```

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

## Change Checklist

Before creating a PR, verify:

- [ ] **Tests pass** - `pnpm test --filter=@unique-ag/<package>`
- [ ] **Types check** - `pnpm check-types`
- [ ] **Style passes** - `pnpm style` (or `pnpm style:fix`)

If applicable:

- [ ] **Docs updated** - Update `services/<name>/docs/` for user-facing changes
- [ ] **Helm values.schema.json** - Update when changing helm chart values
- [ ] **Syncpack** - Run `pnpm syncpack lint` after dependency changes
- [ ] **.env.example** - Update when adding/changing env vars
- [ ] **Terraform outputs** - Keep outputs.tf in sync with main.tf changes
- [ ] **CHANGELOG.md** - Don't edit manually (managed by release-please)
