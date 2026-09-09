<!-- confluence-page-id: 1802338327 -->
<!-- confluence-space-key: PUBDOC -->

## Environment Variables

All configuration is done via environment variables, either directly or through Helm values.

### Required Secrets

These must be provided via Kubernetes secrets:

| Variable | Description | Format |
|----------|-------------|--------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://user:pass@host:5432/db` |
| `AMQP_URL` | RabbitMQ connection string — only required with transcript capture enabled | `amqp://user:pass@host:5672/vhost` |
| `MICROSOFT_CLIENT_SECRET` | Entra app client secret | String from Azure portal |
| `MICROSOFT_WEBHOOK_SECRET` | Webhook validation secret — only required with transcript capture enabled | 128-character random string |
| `AUTH_HMAC_SECRET` | JWT signing key | 64-character hex string |
| `ENCRYPTION_KEY` | Token encryption key | 64-character hex string |

### Application Configuration

Set via `mcpConfig.app` in Helm values:

| Variable | Helm Path | Default | Description |
|----------|-----------|---------|-------------|
| `SELF_URL` | `mcpConfig.app.selfUrl` | (required) | Public URL of the MCP server |

### Microsoft Configuration

Set via `mcpConfig.microsoft` in Helm values:

| Variable | Helm Path | Default | Description |
|----------|-----------|---------|-------------|
| `MICROSOFT_CLIENT_ID` | `mcpConfig.microsoft.clientId` | (required) | Entra app client ID |
| `MICROSOFT_SIGN_IN_TENANT_ID` | `mcpConfig.microsoft.signInTenantId` | `common` | Sign-in tenant ID the OAuth login should open. Set a GUID when sign-in must use the Enterprise Application (service principal) in a foreign tenant. Leave as `common` when users choose their directory at login. Independent of `clientId`/`clientSecret`; not the tenant that owns the app registration |
| `MICROSOFT_PUBLIC_WEBHOOK_URL` | `mcpConfig.microsoft.publicWebhookUrl` | `SELF_URL` | Webhook URL if different from SELF_URL. Only used by transcript capture |

### Chat Integration

Set via `mcpConfig.chat` in Helm values.

| Variable | Helm Path | Default | Description |
|----------|-----------|---------|-------------|
| `CHAT_INTEGRATION` | `mcpConfig.chat.integration` | `enabled` | `enabled` or `disabled`. Toggles the Teams chat/channel messaging tools **independently** of `UNIQUE_INTEGRATION`. When `disabled`, the eight chat tools are not registered and the messaging Graph scopes are not requested |

`CHAT_INTEGRATION` and `UNIQUE_INTEGRATION` are two independent capability axes. Setting `CHAT_INTEGRATION=disabled` together with `UNIQUE_INTEGRATION=enabled` gives an **ingestion-only** deployment: meeting transcript capture with a least-privilege app registration that carries no chat/messaging permissions. At least one of the two must be enabled — a deployment with both disabled fails fast at startup.

### Unique API Configuration

Set via `mcpConfig.unique` in Helm values.

| Variable | Helm Path | Default | Description |
|----------|-----------|---------|-------------|
| `UNIQUE_INTEGRATION` | `mcpConfig.unique.integration` | (required) | `enabled` or `disabled`. `disabled` turns off the knowledge-base tools, the ingestion pipeline, and removes the need for any other Unique or Zitadel configuration |

Setting this to `enabled` turns on meeting transcript capture and makes a further set of variables mandatory — the Unique API endpoint, a root scope, and Zitadel service account headers. Those variables, the service account roles, and the root scope setup are documented in the [Recordings & Transcripts Operator Manual](https://unique-ch.atlassian.net/wiki/spaces/PUBDOC/pages/2535522323/Recordings+Transcripts+-+Operator+Manual).

### Authentication Configuration

Set via `mcpConfig.auth` in Helm values:

| Variable | Helm Path | Default | Description |
|----------|-----------|---------|-------------|
| `AUTH_ACCESS_TOKEN_EXPIRES_IN_SECONDS` | `mcpConfig.auth.accessTokenExpiresInSeconds` | `60` | MCP access token TTL |
| `AUTH_REFRESH_TOKEN_EXPIRES_IN_SECONDS` | `mcpConfig.auth.refreshTokenExpiresInSeconds` | `2592000` | MCP refresh token TTL (30 days) |

### Runtime Configuration

Set via `server.env` in Helm values:

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `info` | Log level: `debug`, `info`, `warn`, `error` |
| `MAX_HEAP_MB` | `1920` | Node.js max heap size |
| `NODE_ENV` | `production` | Node environment |

## Helm Values Reference

### Full Example

```yaml
server:
  # Environment variables from secrets
  envVars:
    - secretRef:
        name: teams-mcp-secrets

  # Static environment variables
  env:
    LOG_LEVEL: info
    MAX_HEAP_MB: 1920
    NODE_ENV: production

  # Resource limits
  resources:
    limits:
      memory: 2048Mi
    requests:
      cpu: 1
      memory: 1984Mi

  # Temporary storage — sized for transcript and recording downloads;
  # a chat-only deployment needs far less
  volumes:
    - name: tmp
      emptyDir:
        sizeLimit: 20Gi
  volumeMounts:
    - name: tmp
      mountPath: /tmp

# Application configuration
mcpConfig:
  enabled: true

  app:
    selfUrl: https://teams.mcp.example.com

  microsoft:
    clientId: "12345678-1234-1234-1234-123456789012"
    # signInTenantId: common  # optional; set a foreign-tenant GUID to pin login to that service principal
    # publicWebhookUrl: https://teams.mcp.example.com  # optional

  chat:
    # Teams chat/channel messaging tools. Defaults to "enabled".
    # Set to "disabled" for an ingestion-only deployment (with unique.integration: enabled).
    integration: enabled

  unique:
    # Chat-only. Set to "enabled" only to add meeting transcript capture,
    # which requires additional configuration — see Recordings & Transcripts.
    integration: disabled

  auth:
    accessTokenExpiresInSeconds: 60
    refreshTokenExpiresInSeconds: 2592000

# Ingress is disabled by default - traffic routed via Kong Gateway
ingress:
  enabled: false

# Monitoring
grafana:
  dashboard:
    enabled: true
    folder: mcp-servers

alerts:
  enabled: true
  defaultAlerts:
    graphql:
      enabled: true
    uniqueApi:
      enabled: true
```

### Unique Service Auth Modes

When transcript capture is enabled, the server talks to the Unique Public API either in `cluster_local` mode (same Kubernetes cluster) or `external` mode (API key). Both are configured under `mcpConfig.unique` and documented, with examples, in the [Recordings & Transcripts Operator Manual](https://unique-ch.atlassian.net/wiki/spaces/PUBDOC/pages/2535522323/Recordings+Transcripts+-+Operator+Manual).

## Database Configuration

### Connection String Format

```
postgresql://username:password@hostname:port/database?sslmode=require
```

### Required Extensions

The PostgreSQL database requires no special extensions. Migrations create all necessary tables and indexes.

## RabbitMQ Configuration

RabbitMQ is only used by the transcript capture pipeline. Chat-only deployments do not need it.

### Connection String Format

```
amqp://username:password@hostname:5672/vhost
```

### Alternative: Individual Fields

Instead of `AMQP_URL`, you can set individual fields:

| Variable | Description |
|----------|-------------|
| `AMQP_USERNAME` | RabbitMQ username |
| `AMQP_PASSWORD` | RabbitMQ password |
| `AMQP_HOST` | RabbitMQ hostname |
| `AMQP_PORT` | RabbitMQ port (default: 5672) |
| `AMQP_VHOST` | Virtual host |

## Security Best Practices

1. Rotate secrets regularly (especially `MICROSOFT_CLIENT_SECRET`)
2. Use managed identities where possible (Azure, AWS, GCP)
3. Encrypt secrets at rest (Kubernetes secrets encryption or external secret managers)
4. Limit network access (enable network policies)
5. Monitor for anomalies (use provided Grafana dashboards and alerts)

See [Security Documentation](../technical/security.md) for details.
