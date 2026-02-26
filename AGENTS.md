# Project Instructions

## General

- Don't write coauthoring or mention claude
- Use pnpm scripts from the root with filters for TypeScript services
- Python services are excluded from the pnpm workspace and turbo; use `uv` directly inside the service directory

## Project Structure

This is a pnpm monorepo with turbo for build orchestration (TypeScript) and uv-managed Python services.

```
services/                  # Deployable services
  factset-mcp/             # TypeScript (NestJS)
  outlook-mcp/             # TypeScript (NestJS)
  sharepoint-connector/    # TypeScript (NestJS)
  teams-mcp/               # TypeScript (NestJS)
  edgar-mcp/               # Python (FastMCP)

packages/                  # Shared TypeScript libraries
  aes-gcm-encryption/
  instrumentation/
  logger/
  mcp-oauth/
  mcp-server-module/
  probe/
```

## General Code Guidelines

- Only add comments for complex algorithms, unexpected behavior, or non-obvious business logic
- Avoid obvious comments that just restate what the code does
- Add export only when what you are exporting is actually used in another file
- Don't create README files for generated code

## TypeScript Code Style

- Add JSDoc comments only for complex methods with multiple parameters or intricate logic
- Avoid the use of `any`. Always use proper types or `unknown` with a type guard.
- When `any` is absolutely necessary (e.g., testing private methods, untyped third-party libraries), add a biome-ignore comment with explanation:
  ```typescript
  // biome-ignore lint/suspicious/noExplicitAny: Mock override private method
  vi.spyOn(service as any, 'validatePKCE').mockReturnValue(true);
  ```
- Follow this import order:
  1. Node.js built-in modules (e.g., `import { createHmac } from 'node:crypto'`)
  2. External packages (e.g., `import { UnauthorizedException } from '@nestjs/common'`)
  3. Testing utilities (e.g., `import { TestBed } from '@suites/unit'`)
  4. Internal modules and types
- Group related imports together
- Order imports alphabetically within each group when practical

## Python Code Style

- Follow ruff defaults for linting and formatting (configured in `pyproject.toml`)
- Use type hints for function signatures; the project must pass `basedpyright` with zero warnings
- Type checking is configured via `pyproject.toml` in each Python service root
- Follow this import order (enforced by ruff `I` rules):
  1. Standard library modules
  2. Third-party packages
  3. Local modules

## Common Commands

### TypeScript Services

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

### Python Services

Run commands from within the service directory (e.g. `services/edgar-mcp`).

```bash
# Setup
uv sync                                 # Create venv and install dependencies

# Development
uv run python -m edgar_mcp.main         # Start service

# Testing
uv run pytest                           # Run tests

# Code quality
uv run ruff check                       # Lint
uv run ruff check --fix                 # Lint and fix
uv run ruff format                      # Format
uv run basedpyright                     # Type check (zero warnings)
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
| `edgar-mcp` | `services/edgar-mcp/**` |
| `aes-gcm-encryption` | `packages/aes-gcm-encryption/**` |
| `instrumentation` | `packages/instrumentation/**` |
| `logger` | `packages/logger/**` |
| `mcp-oauth` | `packages/mcp-oauth/**` |
| `mcp-server-module` | `packages/mcp-server-module/**` |
| `probe` | `packages/probe/**` |
| `ci` | `.github/**` |
| `main` | Root files (`*`, `.*`) |
| `deps` | `**/package.json`, `pnpm-lock.yaml`, `**/pyproject.toml`, `**/uv.lock` |

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

### TypeScript

- [ ] **Tests pass** - `pnpm test --filter=@unique-ag/<package>`
- [ ] **Types check** - `pnpm check-types`
- [ ] **Style passes** - `pnpm style` (or `pnpm style:fix`)

### Python

- [ ] **Tests pass** - `uv run pytest`
- [ ] **Types check** - `uv run basedpyright` (must produce zero warnings)
- [ ] **Style passes** - `uv run ruff check` and `uv run ruff format --check`

### General (if applicable)

- [ ] **Docs updated** - Update `services/<name>/docs/` for user-facing changes
- [ ] **Helm values.schema.json** - Update when changing helm chart values
- [ ] **Syncpack** - Run `pnpm syncpack lint` after dependency changes
- [ ] **.env.example** - Update when adding/changing env vars
- [ ] **Terraform outputs** - Keep outputs.tf in sync with main.tf changes
- [ ] **CHANGELOG.md** - Don't edit manually (managed by release-please)
