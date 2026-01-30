# n8n MCP Server

MCP (Model Context Protocol) server for n8n workflow automation with OAuth 2.1 authentication via Zitadel.

## Features

- **OAuth 2.1 Authentication**: Secure authentication via Zitadel identity provider
- **n8n Node Documentation**: Search and explore n8n node documentation
- **Workflow Validation**: Validate workflow configurations before deployment
- **Template Search**: Find workflow templates by keyword, nodes, or task type

## Prerequisites

- Node.js 20+
- PostgreSQL database (for OAuth token storage)
- Zitadel instance (for authentication)
- n8n nodes database (`nodes.db`)

## Setup

1. Copy the environment file:
   ```bash
   cp .env.example .env
   ```

2. Configure your environment variables (see `.env.example`)

3. Generate Prisma client:
   ```bash
   pnpm db:generate
   ```

4. Run database migrations:
   ```bash
   pnpm db:migrate:deploy
   ```

5. Start the server:
   ```bash
   pnpm dev
   ```

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DATABASE_URL` | PostgreSQL connection string | Yes |
| `ZITADEL_CLIENT_ID` | Zitadel OAuth client ID | Yes |
| `ZITADEL_CLIENT_SECRET` | Zitadel OAuth client secret | Yes |
| `ZITADEL_ISSUER` | Zitadel issuer URL | Yes |
| `HMAC_SECRET` | Secret for JWT signing | Yes |
| `ENCRYPTION_KEY` | 32-byte key for token encryption | Yes |
| `SELF_URL` | Public URL of this server | Yes |
| `NODES_DB_PATH` | Path to n8n nodes SQLite database | No |
| `N8N_API_URL` | n8n instance API URL | No |
| `N8N_API_KEY` | n8n API key | No |

## Available MCP Tools

### Documentation Tools
- `search_nodes` - Search n8n nodes by keyword
- `get_node` - Get detailed node information
- `tools_documentation` - Get MCP tools documentation

### Validation Tools
- `validate_node` - Validate node configuration
- `validate_workflow` - Validate complete workflow

### Template Tools
- `get_template` - Get template by ID
- `search_templates` - Search workflow templates

## Development

```bash
# Build
pnpm build

# Run tests
pnpm test

# Type check
pnpm check-types

# Lint
pnpm style
```

## Architecture

This service uses:
- **NestJS** - Application framework
- **@unique-ag/mcp-oauth** - OAuth 2.1 authentication module
- **@unique-ag/mcp-server-module** - MCP server module with tool decorators
- **Prisma** - Database ORM for PostgreSQL
- **better-sqlite3** - SQLite for n8n node documentation database

## License

Unique License v1

