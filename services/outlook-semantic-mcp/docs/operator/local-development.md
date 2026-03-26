<!-- confluence-page-id: 2061271048 -->
<!-- confluence-space-key: PUBDOC -->

# Local Development

This guide walks through setting up the Outlook Semantic MCP Server for local development and testing.

## Prerequisites

| Requirement | Version | Purpose |
|-------------|---------|---------|
| Node.js | 20+ | Runtime |
| pnpm | 9+ | Package manager |
| Docker | 24+ | Run PostgreSQL and RabbitMQ |
| Azure CLI | Latest | Configure Entra app registration |
| MCP Inspector | Latest (tested with 0.17.2) | MCP Client for testing |

A public reverse proxy, recommended:

- [Azure Dev Tunnels](https://learn.microsoft.com/en-us/azure/developer/dev-tunnels/) for webhook testing

## Quick Start

```bash
# Clone and install
git clone git@github.com:Unique-AG/connectors.git
cd services/outlook-semantic-mcp
pnpm install

# Start infrastructure
docker compose -f docker-compose.prod.yaml up -d

# Configure environment
cp .env.example .env
# Edit .env with your values (see below)

# Run migrations
pnpm db:migrate

# Start development server
pnpm dev
```

The server starts at the configured port (default: `9542`).

## Infrastructure Setup

### Docker Compose

The included `docker-compose.prod.yaml` provides PostgreSQL and RabbitMQ:

```bash
docker compose -f docker-compose.prod.yaml up -d
```

| Service | Credentials |
|---------|-------------|
| PostgreSQL | postgres:postgres |
| RabbitMQ | rabbitmq:rabbitmq |
| RabbitMQ Management | rabbitmq:rabbitmq |

## Microsoft Entra App Registration

You need a Microsoft Entra ID app registration for OAuth. See [Authentication Setup](./authentication.md) for detailed instructions.

For local development, configure:

| Setting | Value |
|---------|-------|
| Redirect URI | `http://localhost:9542/auth/callback` |
| Supported account types | Your organization only |

## Environment Configuration

Create `.env` from the template:

```bash
cp .env.example .env
```

### Required Variables

```env
# Application
SELF_URL=http://localhost:9542
LOG_LEVEL=debug

# Database
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/outlook_semantic_mcp

# RabbitMQ
AMQP_URL=amqp://rabbitmq:rabbitmq@localhost:5672

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
UNIQUE_INGESTION_SERVICE_BASE_URL=http://localhost:8091
UNIQUE_SCOPE_MANAGEMENT_SERVICE_BASE_URL=http://localhost:8092
UNIQUE_ZITADEL_CLIENT_ID=<zitadel-client-id>
UNIQUE_ZITADEL_CLIENT_SECRET=<zitadel-client-secret>
UNIQUE_ZITADEL_OAUTH_TOKEN_URL=https://your-zitadel.zitadel.cloud/oauth/v2/token
UNIQUE_ZITADEL_PROJECT_ID=<zitadel-project-id>
```

### Generating Secrets

```bash
# For MICROSOFT_WEBHOOK_SECRET (128 chars)
openssl rand -hex 64

# For AUTH_HMAC_SECRET and ENCRYPTION_KEY (64 chars each)
openssl rand -hex 32
```

## Webhook Testing

Microsoft Graph webhooks require a publicly accessible HTTPS endpoint. For local development, use Azure Dev Tunnels or any other HTTPS tunnel solution (e.g., ngrok, Cloudflare Tunnel):

### Setup Dev Tunnel

```bash
# Install (macOS)
brew install azure-dev-tunnels

# Login
devtunnel user login

# Create persistent tunnel
devtunnel create outlook-semantic-mcp --allow-anonymous

# Start tunnel
devtunnel port create outlook-semantic-mcp -p 9542
devtunnel host outlook-semantic-mcp
```

### Configure Environment

Set `MICROSOFT_PUBLIC_WEBHOOK_URL` to your tunnel URL:

```env
MICROSOFT_PUBLIC_WEBHOOK_URL=https://abc123.devtunnels.ms
```

Microsoft Graph appends `/mail-subscription/notification` and `/mail-subscription/lifecycle` to this URL when delivering webhook events. It must be publicly reachable by Microsoft, which is why you need a tunnel URL locally instead of `http://localhost:9542`.

## Development Workflow

### Available Scripts

| Script | Description |
|--------|-------------|
| `pnpm dev` | Start with hot reload |
| `pnpm build` | Build for production |
| `pnpm debug` | Start with Node.js debugger |
| `pnpm test` | Run unit tests |
| `pnpm test:watch` | Run tests in watch mode |
| `pnpm test:coverage` | Run tests with coverage |
| `pnpm test:e2e` | Run end-to-end tests |
| `pnpm test:e2e:watch` | Run end-to-end tests in watch mode |
| `pnpm db:generate` | Generate migrations from schema changes |
| `pnpm db:migrate` | Apply pending migrations |
| `pnpm db:check` | Check migration consistency |
| `pnpm style` | Check code style (Biome) |
| `pnpm style:fix` | Fix code style issues |
| `pnpm check-types` | TypeScript type checking |

### Testing the OAuth Flow

1. Start the dev server: `pnpm dev`
2. Open `http://localhost:9542/.well-known/oauth-authorization-server`
3. You should see the OAuth metadata JSON
4. Connect with MCP Inspector or another MCP client that supports OAuth
5. After connecting, use `verify_inbox_connection` to check subscription status

## Debugging

### Common Issues

**OAuth redirect mismatch:**

- Verify `SELF_URL` matches the redirect URI in your Entra app registration
- The redirect URI must be exactly: `http://localhost:9542/auth/callback`

**Webhook not received:**

- Check dev tunnel is running and accessible
- Verify `MICROSOFT_PUBLIC_WEBHOOK_URL` is set correctly
- Check logs for subscription creation errors

**Database connection error:**

- Verify Docker Compose is running: `docker compose -f docker-compose.prod.yaml ps`
- Check `DATABASE_URL` matches the credentials in the Docker Compose service

**Emails not appearing in search:**

- Use the `sync_progress` tool to check the sync state
- If the state is `not_configured`, use `reconnect_inbox` first

## Related Documentation

- [Configuration Reference](./configuration.md) - All environment variables
- [Authentication Setup](./authentication.md) - Entra app registration
- [FAQ](../faq.md) - Frequently asked questions
- [Architecture](../technical/architecture.md) - System design
