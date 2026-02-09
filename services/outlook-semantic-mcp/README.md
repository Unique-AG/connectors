# Outlook Fat MCP Server

A NestJS-based microservice that integrates Microsoft Outlook with the Unique platform through the Model Context Protocol (MCP). It provides email management capabilities through Microsoft Graph API.

## Table of Contents

- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Development](#development)
- [Deployment](#deployment)
- [Observability](#observability)
- [Technical Documentation](#technical-documentation)

## Quick Start

```bash
# Install dependencies
pnpm install

# Copy environment template
cp .env.example .env

# Run database migrations
pnpm db:migrate

# Start development server
pnpm dev
```

## Configuration

Copy `.env.example` to `.env` and configure the following:

### Required Variables

| Variable | Description |
|----------|-------------|
| `SELF_URL` | Base URL for OAuth callbacks |
| `DATABASE_URL` | PostgreSQL connection string |
| `AMQP_URL` | RabbitMQ connection string |
| `MICROSOFT_CLIENT_ID` | Azure AD application client ID |
| `MICROSOFT_CLIENT_SECRET` | Azure AD application client secret |
| `MICROSOFT_WEBHOOK_SECRET` | 128-char hex secret used as `clientState` for webhook validation |
| `MICROSOFT_PUBLIC_WEBHOOK_URL` | Publicly reachable URL for Microsoft webhooks |
| `AUTH_HMAC_SECRET` | 64-char hex secret for JWT signing |
| `ENCRYPTION_KEY` | 64-char hex secret for AES-GCM token encryption |

For complete configuration reference, see [Configuration Guide](./docs/operator/configuration.md).

### Unique API Configuration

**External Mode** (for external deployments):
```env
UNIQUE_SERVICE_AUTH_MODE=external
UNIQUE_API_BASE_URL=http://localhost:8092/public/
UNIQUE_SERVICE_EXTRA_HEADERS={"authorization":"Bearer <app-key>","x-app-id":"<app-id>","x-user-id":"<user-id>","x-company-id":"<company-id>"}
```

**Cluster Local Mode** (for in-cluster deployments):
```env
UNIQUE_SERVICE_AUTH_MODE=cluster_local
UNIQUE_API_BASE_URL=http://chat.namespace.svc:PORT/public/chat/
UNIQUE_INGESTION_SERVICE_BASE_URL=http://ingestions.namespace.svc:PORT
UNIQUE_SERVICE_EXTRA_HEADERS={"x-company-id":"<company-id>","x-user-id":"<user-id>"}
```

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `info` | Logging level (debug, info, warn, error) |
| `AUTH_ACCESS_TOKEN_EXPIRES_IN_SECONDS` | `60` | Access token TTL |
| `AUTH_REFRESH_TOKEN_EXPIRES_IN_SECONDS` | `2592000` | Refresh token TTL (30 days) |
| `UNIQUE_ROOT_SCOPE_PATH` | `outlook-semantic-mcp` | Root folder path in Unique |
| `UNIQUE_USER_FETCH_CONCURRENCY` | `5` | Concurrent user resolution limit |

For complete configuration reference, see [Configuration Guide](./docs/operator/configuration.md).

### Generating Secrets

```bash
# Generate 128-char hex secret (for MICROSOFT_WEBHOOK_SECRET)
openssl rand -hex 64

# Generate 64-char hex secret (for AUTH_HMAC_SECRET, ENCRYPTION_KEY)
openssl rand -hex 32
```

## Development

### Prerequisites

- Node.js 20+
- pnpm
- PostgreSQL 17
- RabbitMQ 4
- Microsoft Azure AD application with required permissions

### Available Scripts

| Script | Description |
|--------|-------------|
| `pnpm dev` | Start development server |
| `pnpm build` | Build for production |
| `pnpm test` | Run unit tests |
| `pnpm test:e2e` | Run end-to-end tests |
| `pnpm test:coverage` | Run tests with coverage |
| `pnpm db:generate` | Generate database migrations |
| `pnpm db:migrate` | Apply database migrations |
| `pnpm style` | Check code style |
| `pnpm style:fix` | Fix code style issues |

### Local Development with Dev Tunnels

For local webhook testing, use Azure Dev Tunnels:

```bash
# Create a tunnel
devtunnel create --allow-anonymous

# Set MICROSOFT_PUBLIC_WEBHOOK_URL to your tunnel URL
```

## Deployment

### Docker Compose (Production)

```bash
docker compose -f docker-compose.prod.yaml up -d
```

Services:
- `outlook-semantic-mcp`: Main application (port 3000)
- `outlook-semantic-mcp-migration`: Database migration runner
- `postgres`: PostgreSQL 17
- `rabbitmq`: RabbitMQ 4 with management UI

### Kubernetes (Helm)

```bash
helm install outlook-semantic-mcp ./deploy/helm-charts/outlook-semantic-mcp \
  --namespace outlook-semantic-mcp \
  --create-namespace \
  -f values.yaml
```

### Terraform (Azure)

Infrastructure modules available in `deploy/terraform/`:
- `outlook-semantic-mcp-secrets`: Azure Key Vault integration
- `outlook-semantic-mcp-entra-application`: Microsoft Entra app registration

## Observability

The service includes comprehensive observability:

- **Logging**: Structured JSON logs via Pino with correlation IDs
- **Metrics**: OpenTelemetry instrumentation for Graph API calls
- **Tracing**: Distributed tracing via OpenTelemetry
- **Dashboards**: Grafana dashboard available in Helm chart

Configure with environment variables:
```env
OTEL_SERVICE_NAME=outlook-semantic-mcp
OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318
OTEL_EXPORTER_PROMETHEUS_PORT=8081
```

## Documentation

Full documentation is available in the `docs/` directory:

| Document | Description |
|----------|-------------|
| [Overview](./docs/README.md) | Features, requirements, limitations, and how it works |
| [Operator Guide](./docs/operator/README.md) | Deployment, configuration, authentication, troubleshooting |
| [Technical Reference](./docs/technical/README.md) | Architecture, flows, permissions, security |

### Technical Deep Dives

| Document | Description |
|----------|-------------|
| [Architecture](./docs/technical/architecture.md) | System components, data model, infrastructure |
| [Flows](./docs/technical/flows.md) | User connection, subscription lifecycle, transcript processing |
| [Security](./docs/technical/security.md) | Encryption, PKCE, threat model |
| [Permissions](./docs/technical/permissions.md) | Microsoft Graph permissions and least-privilege justification |
