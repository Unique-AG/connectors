# Connectors Monorepo

A monorepo containing Model Context Protocol (MCP) servers, Unique ingestion connectors and shared packages.

## Quick Start

### Prerequisites

- Node.js >= 22
- pnpm (specified version: 10.15.1)

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
# Lint code
pnpm lint

# Fix linting issues
pnpm lint:fix

# Format code
pnpm format

# Fix formatting
pnpm format:fix

# Type checking
pnpm check-types
```

### Release

```bash
# Bump version and create release
./version-bump.sh <service-name> <new-version>

# Example:
./version-bump.sh outlook-mcp 0.0.3
```

## Project Structure

### Packages

Shared packages used across services:

- **[aes-gcm-encryption](./packages/aes-gcm-encryption/)** - AES-GCM encryption utilities
- **[instrumentation](./packages/instrumentation/)** - OpenTelemetry instrumentation setup
- **[logger](./packages/logger/)** - Logging utilities
- **[mcp-oauth](./packages/mcp-oauth/README.md)** - OAuth 2.1 Authorization Code + PKCE flow for MCP servers
- **[mcp-server-module](./packages/mcp-server-module/README.md)** - NestJS module for creating MCP servers
- **[probe](./packages/probe/)** - Health check and monitoring utilities

### Services

MCP server implementations:

- **[factset-mcp](./services/factset-mcp/README.md)** - FactSet financial data MCP server
- **[outlook-mcp](./services/outlook-mcp/README.md)** - Microsoft Outlook MCP server

## Contributing

1. Install dependencies: `pnpm install`
2. Start dependencies: `docker-compose up -d`
3. Make your changes
4. Run tests: `pnpm test`
5. Check code quality: `pnpm lint` and `pnpm check-types`
6. Bump version: `./version-bump.sh <service-name> <new-version>`
7. Create a pull request

## License

Refer to [`LICENSE.md`](./LICENSE.md).

## Security

Refer to [`SECURITY.md`](./SECURITY.md).