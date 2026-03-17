## Quick Start

### Prerequisites

**Option A: Nix (recommended)**

If you have [Nix](https://nixos.org/) with flakes enabled:

```bash
nix develop
```

This provides all required tools (Node.js, pnpm, terraform, kubectl, helm, etc.) with pinned versions.

**Option B: Manual setup**

- Node.js >= 24
- pnpm (specified version in `package.json` `packageManager` field)

### Installation

```bash
pnpm install
```

### Start Third-Party Dependencies

```bash
docker-compose up -d
```

## Development Scripts

### Package Management

```bash
# Install dependencies for all packages
pnpm install

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
pnpm dev -- --filter=@unique-ag/confluence-connector
pnpm dev -- --filter=@unique-ag/outlook-semantic-mcp
pnpm dev -- --filter=@unique-ag/sharepoint-connector
pnpm dev -- --filter=@unique-ag/teams-mcp
```

### Building

```bash
# Build all packages and services
pnpm build

# Build specific package/service
pnpm build --filter=@unique-ag/<package-name>
```

### Docker

Each service has its own `docker-compose.prod.yaml`. To test a production deployment, run from the service directory:
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
# Lint / format (Biome)
pnpm style

# Auto-fix lint and formatting
pnpm style:fix

# Type checking
pnpm check-types

# Helm chart linting
pnpm quality
```

### Release

Releases are handled by [release-please](https://github.com/googleapis/release-please).

## Project Structure

### Packages

Shared packages used across services:

- **[aes-gcm-encryption](./packages/aes-gcm-encryption/)** - AES-GCM encryption utilities
- **[instrumentation](./packages/instrumentation/)** - OpenTelemetry instrumentation setup
- **[logger](./packages/logger/)** - Logging utilities
- **[mcp-oauth](./packages/mcp-oauth/README.md)** - OAuth 2.1 Authorization Code + PKCE flow for MCP servers
- **[mcp-server-module](./packages/mcp-server-module/README.md)** - NestJS module for creating MCP servers
- **[probe](./packages/probe/)** - Health check and monitoring utilities
- **[unique-api](./packages/unique-api/)** - Shared NestJS module for Unique platform API integration
- **[utils](./packages/utils/)** - Shared utility modules for the connectors monorepo

## Nix Development Environment

The repository includes a Nix flake (`flake.nix`) that provides a reproducible development environment.

### Usage

```bash
# Enter the development shell
nix develop

# Or use direnv for automatic activation (`.envrc` is already committed)
```

### Included Tools

| Category | Tools |
|----------|-------|
| Node.js | Node.js 24.x, pnpm (via corepack) |
| Infrastructure | terraform, kubectl, helm, azure-cli, devtunnel |
| Utilities | jq, yq, zsh |

> **Note:** `turbo` and `biome` are installed via pnpm (`node_modules/.bin`).

### Extending for New Languages

The flake uses a single devShell by design. When adding new language support (e.g., Python):

1. Add the language packages to the appropriate category in `flake.nix`
2. The shared tools (infrastructure, utilities) remain available to all services

This approach keeps the development experience consistent across the monorepo while allowing services to use different languages.

### Multiple DevShells (Optional)

If isolated environments become necessary (e.g., conflicting tool versions or reducing shell startup time), the flake can expose multiple devShells:

```nix
devShells = {
  default = pkgs.mkShell {
    buildInputs = sharedPkgs ++ nodePkgs ++ infraPkgs;
  };
  python = pkgs.mkShell {
    buildInputs = sharedPkgs ++ pythonPkgs ++ infraPkgs;
  };
  # Or per-service:
  # teams-mcp = pkgs.mkShell { ... };
};
```

Usage:

```bash
nix develop          # default (Node.js)
nix develop .#python # Python environment
```

Prefer the single devShell approach unless there's a concrete need for separation.

## Contributing

1. Install dependencies: `pnpm install`
2. Start dependencies: `docker-compose up -d`
3. Make your changes
4. Run tests: `pnpm test`
5. Check code quality: `pnpm style` and `pnpm check-types`
6. Create a pull request — versioning is handled automatically by [release-please](https://github.com/googleapis/release-please)