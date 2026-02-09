<!-- confluence-page-id: -1 -->
<!-- confluence-space-key: PUBDOC -->

This guide walks through setting up the Outlook MCP Server for local development and testing.

## Prerequisites

| Requirement | Version | Purpose |
|-------------|---------|---------|
| Node.js | 20+ | Runtime |
| pnpm | 9+ | Package manager |
| Docker | 24+ | Run PostgreSQL and RabbitMQ |
| Azure CLI | Latest | Configure Entra app registration |
| MCP Inspector | 0.17.2 | MCP Client |

A public reverse proxy, recommended:

- [Azure Dev Tunnels](https://learn.microsoft.com/en-us/azure/developer/dev-tunnels/) for webhook testing

## Quick Start

```bash
# Clone and install
git clone git@github.com:Unique-AG/connectors.git
cd services/outlook-semantic-mcp
pnpm install

# Start infrastructure
docker compose up -d

# Configure environment
cp .env.example .env
# Edit .env with your values (see below)

# Run migrations
pnpm db:migrate

# Start development server
pnpm dev
```

The server starts at the configured port.

## Infrastructure Setup

### Docker Compose

The included `docker-compose.yaml` provides PostgreSQL and RabbitMQ:

```bash
docker compose up -d
```

| Service | Credentials |
|---------|-------------|
| PostgreSQL | postgres:postgres |
| RabbitMQ | guest:guest |
| RabbitMQ Management | guest:guest |

## Microsoft Entra App Registration

You need a Microsoft Entra ID app registration for OAuth. See [Authentication Setup](./authentication.md) for detailed instructions.

For local development, configure:

| Setting | Value |
|---------|-------|
| Redirect URI | `http://localhost:<port>/auth/callback` |
| Supported account types | Your organization only |

## Environment Configuration

Create `.env` from the template:

```bash
cp .env.example .env
```

### Required Variables

```env
# Application
SELF_URL=http://localhost:<port>

# Database
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/outlook_semantic_mcp

# RabbitMQ
AMQP_URL=amqp://guest:guest@localhost:5672

# Microsoft (from Entra app registration)
MICROSOFT_CLIENT_ID=<your-client-id>
MICROSOFT_CLIENT_SECRET=<your-client-secret>
MICROSOFT_WEBHOOK_SECRET=<generate-128-char-hex>
MICROSOFT_PUBLIC_WEBHOOK_URL=<your-tunnel-url>  # See webhook testing below

# Security (generate with: openssl rand -hex 32)
AUTH_HMAC_SECRET=<64-char-hex>
ENCRYPTION_KEY=<64-char-hex>

# Unique API (for local testing, use external mode)
UNIQUE_SERVICE_AUTH_MODE=external
UNIQUE_API_BASE_URL=http://localhost:8092/public/
UNIQUE_INGESTION_SERVICE_BASE_URL=http://localhost:8091
```

### Generating Secrets

```bash
# For MICROSOFT_WEBHOOK_SECRET (128 chars)
openssl rand -hex 64

# For AUTH_HMAC_SECRET and ENCRYPTION_KEY (64 chars each)
openssl rand -hex 32
```

## Webhook Testing

Microsoft Graph webhooks require a publicly accessible HTTPS endpoint. For local development, use Azure Dev Tunnels:

### Setup Dev Tunnel

```bash
# Install (macOS)
brew install azure-dev-tunnels

# Login
devtunnel user login

# Create persistent tunnel
devtunnel create outlook-semantic-mcp --allow-anonymous

# Start tunnel
devtunnel port create outlook-semantic-mcp -p <port>
devtunnel host outlook-semantic-mcp
```

### Configure Environment

Set `MICROSOFT_PUBLIC_WEBHOOK_URL` to your tunnel URL:

```env
MICROSOFT_PUBLIC_WEBHOOK_URL=https://abc123.devtunnels.ms
```

This URL is used when creating Microsoft Graph subscriptions.

## Development Workflow

### Available Scripts

| Script | Description |
|--------|-------------|
| `pnpm dev` | Start with hot reload |
| `pnpm build` | Build for production |
| `pnpm test` | Run unit tests |
| `pnpm test:watch` | Run tests in watch mode |
| `pnpm test:coverage` | Run tests with coverage |
| `pnpm test:e2e` | Run end-to-end tests |
| `pnpm db:generate` | Generate migrations from schema changes |
| `pnpm db:migrate` | Apply pending migrations |
| `pnpm db:studio` | Open Drizzle Studio (database GUI) |
| `pnpm style` | Check code style (Biome) |
| `pnpm style:fix` | Fix code style issues |

### Testing the OAuth Flow

1. Start the dev server: `pnpm dev`
2. Open `http://localhost:<port>/.well-known/oauth-authorization-server`
3. You should see the OAuth metadata JSON
4. Connect with an MCP client that supports OAuth

### Testing Webhooks

1. Ensure dev tunnel is running
2. Complete OAuth flow to create a user
3. The system automatically creates a Microsoft Graph subscription
4. Send an email to Outlook to see if sync is working

### Database Inspection

Use Drizzle Studio to inspect the database:

```bash
pnpm db:studio
```

Opens a browser UI at `https://local.drizzle.studio`.

## Debugging

### Common Issues

**OAuth redirect mismatch:**

- Verify `SELF_URL` matches the redirect URI in your Entra app registration
- Include the exact path: `http://localhost:<port>/auth/callback`

**Webhook not received:**

- Check dev tunnel is running and accessible
- Verify `MICROSOFT_PUBLIC_WEBHOOK_URL` is set correctly
- Check Microsoft Graph subscription was created (see logs)

## Related Documentation

- [Configuration Reference](./configuration.md) - All environment variables
- [Authentication Setup](./authentication.md) - Entra app registration
- [FAQ](../faq.md) - Frequently asked questions
- [Architecture](../technical/architecture.md) - System design
