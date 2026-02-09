## Start Third-Party Dependencies

```bash
docker-compose up -d
```

## TypeScript Services

### Prerequisites

- Node.js >= 22
- pnpm (specified version in `package.json` `packageManager` field)

TypeScript services and shared packages are managed via pnpm and turbo.

### Installation

```bash
pnpm install
```

### Package Management

```bash
# Add dependency to specific package
pnpm add <package> --filter=@unique-ag/<package-name>

# Remove dependency from specific package
pnpm remove <package> --filter=@unique-ag/<package-name>
```

### Development

```bash
# Start development server for a specific service
pnpm dev -- --filter=@unique-ag/<service-name>

# Examples:
pnpm dev -- --filter=@unique-ag/factset-mcp
pnpm dev -- --filter=@unique-ag/outlook-mcp
```

### Building

```bash
# Build all packages and services
pnpm build

# Build specific package/service
pnpm build --filter=@unique-ag/<package-name>
```

### Docker

You can test the Docker build and a production deployment by running:

```bash
docker-compose -f docker-compose.prod.yaml --env-file .env up
```

### Testing

```bash
# Run unit tests
pnpm test

# Run unit tests in watch mode
pnpm test:watch

# Run end-to-end tests
pnpm test:e2e

# Run e2e tests in watch mode
pnpm test:e2e:watch

# Generate coverage report and update README badges
pnpm test:coverage
```

### Code Quality

```bash
# Lint and format
pnpm style
pnpm style:fix

# Type checking
pnpm check-types
```

### Release

Releases are handled by [release-please](https://github.com/googleapis/release-please).

## Python Services

### Prerequisites

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/)

Python services live under `services/` but are **excluded from the pnpm workspace and turbo**. Each service is self-contained and managed with uv.

### IDE Setup

Open `connectors.code-workspace` instead of the root folder when working on Python services. This is a VS Code/Cursor multi-root workspace that adds each Python service as a separate workspace folder. Without it, basedpyright (Pylance) looks for `pyrightconfig.json` / `pyproject.toml` at the repository root and fails to resolve Python imports and virtual environments correctly. Each Python service folder needs to be a workspace root so the type checker picks up its own config.

When adding a new Python service, add it as a folder entry in `connectors.code-workspace`.

### Installation

```bash
cd services/<service-name>
uv sync --all-extras       # Create venv and install dependencies
cp .env.example .env
```

### Development

```bash
cd services/<service-name>
uv run python -m edgar_mcp.main
```

### Testing

```bash
cd services/<service-name>
uv run pytest
```

### Code Quality

```bash
cd services/<service-name>
uv run ruff check       # Lint
uv run ruff check --fix # Lint and fix
uv run ruff format      # Format
uv run basedpyright     # Type checking (must produce zero warnings)
```

### Adding Dependencies

```bash
cd services/edgar-mcp
uv add <package>           # Add runtime dependency
uv add --group dev <pkg>   # Add dev dependency
```

## Creating a New Service

### Service Directory

Create `services/<service-name>/` with:

- `.env.example` - documented environment variables
- `deploy/Dockerfile` - multi-stage production build
- `deploy/helm-charts/<service-name>/` - Helm chart (`Chart.yaml`, `values.yaml`, `values.schema.json`, templates)
- `deploy/terraform/` - Azure infrastructure (Entra apps, secrets)
- Tests

#### TypeScript

- `package.json` with name `@unique-ag/<service-name>`
- `tsconfig.json` and `tsconfig.build.json`
- `turbo.json` extending the root config (`"extends": ["//"]`)

#### Python

- `pyproject.toml` with basedpyright, ruff, and pytest config
- Exclude from pnpm workspace in `pnpm-workspace.yaml` (`!services/<service-name>`)
- Exclude from biome formatting in `biome.json`
- Add as a folder in `connectors.code-workspace` (for basedpyright IDE support)

### Monorepo Registration Checklist

These files must be updated when adding a new service:

- [ ] `AGENTS.md` - add scope to **Valid Scopes** table
- [ ] `DEVELOP.md` - add to **Project Structure** listing
- [ ] `.github/workflows/<service-name>.ci.yaml` - create CI workflow (use `_template-ci.yaml` for TypeScript, or a standalone workflow for Python)
- [ ] `.github/workflows/release-please.yaml` - add output variables and a `release-<service-name>` job
- [ ] `release-please-config.json` - add package entry with `release-type` (`node` for TypeScript, `python` for Python)
- [ ] `.release-please-manifest.json` - add initial version entry (e.g. `"services/<service-name>": "0.1.0"`)
- [ ] `.github/dependabot.yml` - add `uv` ecosystem entry for Python services (Docker/Helm/Terraform use wildcards, but `uv` requires an explicit directory)

These files use wildcards and **don't** need per-service updates:

- `.github/CODEOWNERS` - covers all files
- `docker-compose.yaml` - shared infrastructure only
- Root `turbo.json` - global config

## Project Structure

### TypeScript Services

- **[factset-mcp](./services/factset-mcp/)** - FactSet MCP server
- **[outlook-mcp](./services/outlook-mcp/)** - Outlook MCP server
- **[sharepoint-connector](./services/sharepoint-connector/)** - SharePoint connector
- **[teams-mcp](./services/teams-mcp/)** - Teams MCP server

### Shared Packages (TypeScript)

- **[aes-gcm-encryption](./packages/aes-gcm-encryption/)** - AES-GCM encryption utilities
- **[instrumentation](./packages/instrumentation/)** - OpenTelemetry instrumentation setup
- **[logger](./packages/logger/)** - Logging utilities
- **[mcp-oauth](./packages/mcp-oauth/README.md)** - OAuth 2.1 Authorization Code + PKCE flow for MCP servers
- **[mcp-server-module](./packages/mcp-server-module/README.md)** - NestJS module for creating MCP servers
- **[probe](./packages/probe/)** - Health check and monitoring utilities

### Python Services

- **[edgar-mcp](./services/edgar-mcp/)** - SEC EDGAR MCP server

## Contributing

### TypeScript

1. Install dependencies: `pnpm install`
2. Start dependencies: `docker-compose up -d`
3. Make your changes
4. Run tests: `pnpm test`
5. Check code quality: `pnpm style` and `pnpm check-types`
6. Create a pull request

### Python

1. Install dependencies: `cd services/<service-name> && uv sync`
2. Start dependencies: `docker-compose up -d`
3. Make your changes
4. Run tests: `uv run pytest`
5. Check there are no typing warnings: `uv run basedpyright`
6. Format the files: `uv run ruff format`
7. Check code quality: `uv run ruff check`
8. Create a pull request
