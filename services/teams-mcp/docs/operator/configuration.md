# Configuration Reference

## Environment Variables

All configuration is done via environment variables, either directly or through Helm values.

### Required Secrets

These must be provided via Kubernetes secrets:

| Variable | Description | Format |
|----------|-------------|--------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://user:pass@host:5432/db` |
| `AMQP_URL` | RabbitMQ connection string | `amqp://user:pass@host:5672/vhost` |
| `MICROSOFT_CLIENT_SECRET` | Entra app client secret | String from Azure portal |
| `MICROSOFT_WEBHOOK_SECRET` | Webhook validation secret | 128-character random string |
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
| `MICROSOFT_PUBLIC_WEBHOOK_URL` | `mcpConfig.microsoft.publicWebhookUrl` | `SELF_URL` | Webhook URL if different from SELF_URL |

### Unique API Configuration

Set via `mcpConfig.unique` in Helm values:

| Variable | Helm Path | Default | Description |
|----------|-----------|---------|-------------|
| `UNIQUE_SERVICE_AUTH_MODE` | `mcpConfig.unique.serviceAuthMode` | `cluster_local` | Auth mode: `cluster_local` or `external` |
| `UNIQUE_API_BASE_URL` | `mcpConfig.unique.apiBaseUrl` | (required) | Unique API endpoint |
| `UNIQUE_API_VERSION` | `mcpConfig.unique.apiVersion` | `2023-12-06` | API version |
| `UNIQUE_ROOT_SCOPE_PATH` | `mcpConfig.unique.rootScopePath` | `Teams-MCP` | Root folder for uploads |
| `UNIQUE_USER_FETCH_CONCURRENCY` | `mcpConfig.unique.userFetchConcurrency` | `5` | Parallel user lookups |
| `UNIQUE_INGESTION_SERVICE_BASE_URL` | `mcpConfig.unique.ingestionServiceBaseUrl` | (required) | Ingestion service endpoint |

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

  # Temporary storage for processing
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
    # publicWebhookUrl: https://teams.mcp.example.com  # optional

  unique:
    serviceAuthMode: cluster_local
    apiBaseUrl: http://api-gateway.unique:8080
    apiVersion: "2023-12-06"
    rootScopePath: Teams-MCP
    userFetchConcurrency: 5
    ingestionServiceBaseUrl: http://node-ingestion.unique:8091

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

### Service Auth Modes

#### cluster_local (Default)

For deployments within the same Kubernetes cluster as Unique:

```yaml
mcpConfig:
  unique:
    serviceAuthMode: cluster_local
    apiBaseUrl: http://api-gateway.unique:8080
    ingestionServiceBaseUrl: http://node-ingestion.unique:8091
    serviceExtraHeaders:
      x-company-id: "company-id"
      x-user-id: "service-user-id"
```

#### external

For deployments outside the Unique cluster:

```yaml
mcpConfig:
  unique:
    serviceAuthMode: external
    apiBaseUrl: https://api.unique.app
    serviceExtraHeaders:
      authorization: "Bearer <api-key>"
      x-app-id: "app-id"
      x-user-id: "user-id"
      x-company-id: "company-id"
```

## Database Configuration

### Connection String Format

```
postgresql://username:password@hostname:port/database?sslmode=require
```

### Required Extensions

The PostgreSQL database requires no special extensions. Migrations create all necessary tables and indexes.

## RabbitMQ Configuration

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

1. **Rotate secrets regularly** - Especially `MICROSOFT_CLIENT_SECRET`
2. **Use managed identities** where possible (Azure, AWS, GCP)
3. **Encrypt secrets at rest** - Use Kubernetes secrets encryption or external secret managers
4. **Limit network access** - Enable network policies
5. **Monitor for anomalies** - Use the provided Grafana dashboards and alerts
