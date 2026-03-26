<!-- confluence-page-id: 2065629188 -->
<!-- confluence-space-key: PUBDOC -->

# Configuration

## Environment Variables

All configuration is done via environment variables, either directly or through Helm values.

### Required Secrets

These must be provided via Kubernetes secrets:

| Variable | Format | Description |
|----------|--------|-------------|
| `DATABASE_URL` | `postgresql://user:pass@host:5432/db` | PostgreSQL connection string |
| `AMQP_URL` | `amqp://user:pass@host:5672/vhost` | RabbitMQ connection string (or use individual `AMQP_*` fields) |
| `MICROSOFT_CLIENT_SECRET` | String from Azure portal | Entra app client secret |
| `MICROSOFT_WEBHOOK_SECRET` | 128-character hex string | Webhook validation secret — generate with `openssl rand -hex 64` |
| `AUTH_HMAC_SECRET` | 64-character hex string | HMAC-SHA256 session state signing key — generate with `openssl rand -hex 32` |
| `ENCRYPTION_KEY` | 64-character hex string | AES-256-GCM token encryption key — generate with `openssl rand -hex 32` |
| `UNIQUE_ZITADEL_CLIENT_SECRET` | String | Zitadel OAuth client secret (required for `external` auth mode only) |

### Application Configuration

Set via `mcpConfig.app` in Helm values:

| Variable | Helm Path | Default | Description |
|----------|-----------|---------|-------------|
| `SELF_URL` | `mcpConfig.app.selfUrl` | (required) | Public URL of the MCP server, used for OAuth callbacks |
| `PORT` | — | `9542` | Local HTTP port the server binds to. Note: the Helm chart maps this to port `51345` at the service/ingress level — the application listens on `9542` inside the container, but network policies and ingress rules reference `51345`. |
| `MCP_DEBUG_MODE` | `mcpConfig.app.mcpDebugMode` | `disabled` | Set to `enabled` to expose debug tools and extra debugging data in tool responses |
| `APP_BUFFER_LOGS` | `mcpConfig.app.bufferLogs` | `enabled` | Buffer logs before writing to reduce I/O. Set to `disabled` only for startup debugging when you need logs to appear immediately. |
| `DEFAULT_MAIL_FILTERS` | `mcpConfig.defaultMailFilters` | Helm default: `{"ignoredBefore":"2025-06-06","ignoredContents":[],"ignoredSenders":[]}` | JSON string controlling which emails are synced — see [Mail Filters](#mail-filters). The application has no built-in default; this value is provided by Helm `values.yaml`. Required when running outside Helm. **Warning:** Setting `ignoredBefore` far in the past can cause very large initial syncs for users with large mailboxes, consuming significant time and Microsoft Graph API quota. |

### Microsoft Configuration

Set via `mcpConfig.microsoft` in Helm values:

| Variable | Helm Path | Default | Description |
|----------|-----------|---------|-------------|
| `MICROSOFT_CLIENT_ID` | `mcpConfig.microsoft.clientId` | (required) | Entra app client ID |
| `MICROSOFT_PUBLIC_WEBHOOK_URL` | `mcpConfig.microsoft.publicWebhookUrl` | defaults to `SELF_URL` | Base URL Microsoft Graph uses for **webhook** callbacks (not OAuth callbacks — those always use `SELF_URL`). Microsoft appends `/mail-subscription/notification` and `/mail-subscription/lifecycle` to this URL. Must be publicly reachable by Microsoft Graph. Set this when the externally reachable URL differs from `SELF_URL` (e.g., a dev tunnel URL in local development). In most production deployments this matches `SELF_URL`. Note: the Entra ID app registration redirect URI must match `SELF_URL/auth/callback`, not this variable. |
| `MICROSOFT_SUBSCRIPTION_EXPIRATION_TIME_HOURS_UTC` | `mcpConfig.microsoft.subscriptionExpirationTimeHoursUTC` | `3` | Hour of day in UTC (0–23) when scheduled subscription renewals occur. Subscriptions are renewed daily at this hour. Adjust to align with your operations timezone so renewals happen during business hours when monitoring is active. |

### Unique API Configuration

Set via `mcpConfig.unique` in Helm values:

| Variable | Helm Path | Default | Description |
|----------|-----------|---------|-------------|
| `UNIQUE_SERVICE_AUTH_MODE` | `mcpConfig.unique.serviceAuthMode` | `cluster_local` | Auth mode: `cluster_local` or `external` |
| `UNIQUE_INGESTION_SERVICE_BASE_URL` | `mcpConfig.unique.ingestionServiceBaseUrl` | (required) | Unique ingestion service endpoint |
| `UNIQUE_SCOPE_MANAGEMENT_SERVICE_BASE_URL` | `mcpConfig.unique.scopeManagementServiceBaseUrl` | (required) | Unique scope management service endpoint |
| `UNIQUE_STORE_INTERNALLY` | `mcpConfig.unique.storeInternally` | `enabled` | When `enabled`, emails are ingested into the Unique Knowledge Base for semantic search. Set to `disabled` to prevent ingestion (emails will not be searchable via `search_emails`). |
| `UNIQUE_SERVICE_EXTRA_HEADERS` | `mcpConfig.unique.serviceExtraHeaders` | (required for `cluster_local`) | JSON: `{"x-company-id":"...","x-user-id":"..."}` |
| `UNIQUE_ZITADEL_CLIENT_ID` | `mcpConfig.unique.zitadel.clientId` | (required for `external`) | Zitadel OAuth client ID |
| `UNIQUE_ZITADEL_OAUTH_TOKEN_URL` | `mcpConfig.unique.zitadel.oauthTokenUrl` | (required for `external`) | Zitadel OAuth token URL |
| `UNIQUE_ZITADEL_PROJECT_ID` | `mcpConfig.unique.zitadel.projectId` | (required for `external`) | Zitadel project ID for audience validation |

### Logs Configuration

Set via `mcpConfig.logs` in Helm values:

| Variable | Helm Path | Default | Description |
|----------|-----------|---------|-------------|
| `LOGS_DIAGNOSTICS_DATA_POLICY` | `mcpConfig.logs.diagnosticsDataPolicy` | `conceal` | Controls what diagnostic data is logged: `conceal` hides sensitive data, `disclose` shows full data |

### Authentication Token Configuration

These tokens are issued by the MCP server to MCP clients (e.g., AI assistants) after a user completes OAuth. They are distinct from Microsoft tokens and control how long a client session remains valid without re-authentication.

Set via `mcpConfig.auth` in Helm values (optional — defaults are suitable for most deployments):

| Variable | Helm Path | Default | Description |
|----------|-----------|---------|-------------|
| `AUTH_ACCESS_TOKEN_EXPIRES_IN_SECONDS` | `mcpConfig.auth.accessTokenExpiresInSeconds` | `60` | TTL of the short-lived access token issued to MCP clients |
| `AUTH_REFRESH_TOKEN_EXPIRES_IN_SECONDS` | `mcpConfig.auth.refreshTokenExpiresInSeconds` | `2592000` | TTL of the long-lived refresh token issued to MCP clients (30 days) |

### Runtime Configuration

Set via `server.env` in Helm values for plain config, or via `server.envVars` (with `valueFrom.secretKeyRef`) for secrets:

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `info` | Log level: `fatal`, `error`, `warn`, `info`, `debug`, `trace`, `silent` |
| `MAX_HEAP_MB` | `1920` | Node.js max heap size in MB. With the default of 1920 MB, set the pod memory request/limit to at least ~2.5 GB to account for non-heap memory overhead. |
| `NODE_ENV` | `production` | Node environment |
| `NODE_EXTRA_CA_CERTS`                 | —                                                 | Path to a PEM file containing additional CA certificates for TLS verification if pod's trust store doesn't have them |
| `OTEL_METRICS_EXPORTER` | `prometheus` | OpenTelemetry metrics exporter |
| `OTEL_EXPORTER_PROMETHEUS_HOST` | `0.0.0.0` | Host for the Prometheus metrics scrape endpoint |
| `OTEL_EXPORTER_PROMETHEUS_PORT` | `51346` | Port for the Prometheus metrics scrape endpoint |

## Helm Values Reference

### Full Example

```yaml
server:
  envVars:
    - name: DATABASE_URL
      valueFrom:
        secretKeyRef:
          name: outlook-semantic-mcp-secrets
          key: DATABASE_URL
    - name: AMQP_URL
      valueFrom:
        secretKeyRef:
          name: outlook-semantic-mcp-secrets
          key: AMQP_URL
    - name: MICROSOFT_CLIENT_SECRET
      valueFrom:
        secretKeyRef:
          name: outlook-semantic-mcp-secrets
          key: MICROSOFT_CLIENT_SECRET
    - name: MICROSOFT_WEBHOOK_SECRET
      valueFrom:
        secretKeyRef:
          name: outlook-semantic-mcp-secrets
          key: MICROSOFT_WEBHOOK_SECRET
    - name: AUTH_HMAC_SECRET
      valueFrom:
        secretKeyRef:
          name: outlook-semantic-mcp-secrets
          key: AUTH_HMAC_SECRET
    - name: ENCRYPTION_KEY
      valueFrom:
        secretKeyRef:
          name: outlook-semantic-mcp-secrets
          key: ENCRYPTION_KEY

  env:
    LOG_LEVEL: info
    MAX_HEAP_MB: 1920
    NODE_ENV: production
    OTEL_METRICS_EXPORTER: prometheus
    OTEL_EXPORTER_PROMETHEUS_HOST: "0.0.0.0"
    OTEL_EXPORTER_PROMETHEUS_PORT: "51346"

mcpConfig:
  enabled: true

  app:
    selfUrl: https://outlook.semantic.mcp.example.com
    mcpDebugMode: disabled

  microsoft:
    clientId: "12345678-1234-1234-1234-123456789012"
    # publicWebhookUrl: https://outlook.semantic.mcp.example.com  # optional, defaults to selfUrl

  unique:
    serviceAuthMode: cluster_local
    ingestionServiceBaseUrl: http://node-ingestion.unique:8091
    scopeManagementServiceBaseUrl: http://node-scope-management.unique:8092
    serviceExtraHeaders:
      x-company-id: "<your-company-id>"
      x-user-id: "<your-zitadel-service-user-id>"

  defaultMailFilters: '{"ignoredBefore":"2025-06-06","ignoredContents":[],"ignoredSenders":[]}'

ingress:
  enabled: true
  ingressClassName: kong
  hosts:
    - host: outlook.semantic.mcp.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: outlook-semantic-mcp-tls
      hosts:
        - outlook.semantic.mcp.example.com

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

For deployments within the same Kubernetes cluster as Unique. Uses in-cluster service URLs with `x-company-id` and `x-user-id` headers passed to all Unique API requests.

!!! warning "`x-user-id` must be a real Zitadel service user"
    The `x-user-id` value **must** be the ID of an actual service user created in Zitadel — it cannot be an arbitrary value. See [Zitadel Service Account](#zitadel-service-account) for setup instructions.

```yaml
mcpConfig:
  unique:
    serviceAuthMode: cluster_local
    ingestionServiceBaseUrl: http://node-ingestion.unique:8091
    scopeManagementServiceBaseUrl: http://node-scope-management.unique:8092
    serviceExtraHeaders:
      x-company-id: "<your-company-id>"
      x-user-id: "<your-zitadel-service-user-id>"
```

#### external

For deployments outside the Unique cluster. Uses Zitadel OAuth for service-to-service authentication. `UNIQUE_ZITADEL_CLIENT_SECRET` must be provided as a Kubernetes secret.

```yaml
mcpConfig:
  unique:
    serviceAuthMode: external
    ingestionServiceBaseUrl: https://ingestion.unique.app
    scopeManagementServiceBaseUrl: https://scope-management.unique.app
    zitadel:
      clientId: "<zitadel-client-id>"
      oauthTokenUrl: "https://your-zitadel-instance.zitadel.cloud/oauth/v2/token"
      projectId: "<zitadel-project-id>"
```

## Zitadel Service Account

A Zitadel service account is required for both `cluster_local` and `external` auth modes. For `cluster_local`, its user ID is passed in the `x-user-id` header. For `external`, its credentials are used for service-to-service OAuth.

For instructions on creating a service user, see the [How To Configure A Service User](https://unique-ch.atlassian.net/wiki/spaces/PUBDOC/pages/1411023075/How+To+Configure+A+Service+User) guide.

### Service-Specific Setup

After creating the service user, note the following values for configuration:

| Value | Used In | Helm Path |
|-------|---------|-----------|
| **User ID** | `cluster_local` | `mcpConfig.unique.serviceExtraHeaders.x-user-id` |
| **Client ID** | `external` | `mcpConfig.unique.zitadel.clientId` |
| **Client Secret** | `external` | Secret: `UNIQUE_ZITADEL_CLIENT_SECRET` |
| **Project ID** | `external` | `mcpConfig.unique.zitadel.projectId` |
| **OAuth Token URL** | `external` | `mcpConfig.unique.zitadel.oauthTokenUrl` |

### Service Account Permissions

The service account must have the following Unique platform permissions:

- **Ingestion**: permission to submit content to the ingestion service (`UNIQUE_INGESTION_SERVICE_BASE_URL`)
- **Scope management**: permission to create and manage scopes via the scope management service (`UNIQUE_SCOPE_MANAGEMENT_SERVICE_BASE_URL`)

## Mail Filters

The `DEFAULT_MAIL_FILTERS` value controls which emails are synced during the initial import and ongoing sync. It is a JSON string set via `mcpConfig.defaultMailFilters`.

> **Warning:** Changing `DEFAULT_MAIL_FILTERS` only affects newly synced emails. Emails that were already ingested under a previous filter configuration are **not** removed. To remove previously ingested emails, you must delete them manually.

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `ignoredBefore` | ISO date string | Skip emails received before this date. Useful to limit the scope of the initial sync. |
| `ignoredSenders` | Array of regex patterns | Regex patterns in `/pattern/flags` format tested against the sender's email address. Emails matching any pattern are excluded from sync. |
| `ignoredContents` | Array of regex patterns | Regex patterns in `/pattern/flags` format tested against both the email subject and body. Emails matching any pattern are excluded from sync. |

Patterns for `ignoredSenders` and `ignoredContents` must be in `/pattern/flags` format (e.g. `/^noreply@example\.com$/i`, `/unsubscribe/i`). Patterns are validated against ReDoS attacks on ingestion — invalid or unsafe patterns are rejected.

### Example

```yaml
mcpConfig:
  defaultMailFilters: '{"ignoredBefore":"2025-06-06","ignoredContents":["/unsubscribe/i"],"ignoredSenders":["/^noreply@example\\.com$/i"]}'
```

The default value (`ignoredBefore: 2025-06-06`, empty arrays for the rest) limits the initial sync to emails received after June 6, 2025 with no sender or content exclusions.

## Database Configuration

### Connection String Format

```
postgresql://username:password@hostname:port/database?sslmode=require
```

No special PostgreSQL extensions are required. Database migrations run automatically on deployment and create all necessary tables and indexes.

## RabbitMQ Configuration

### Connection String Format

```
amqp://username:password@hostname:5672/vhost
```

### Alternative: Individual Fields

Instead of `AMQP_URL`, you can provide individual connection fields:

| Variable | Description | Default |
|----------|-------------|---------|
| `AMQP_USERNAME` | RabbitMQ username | — |
| `AMQP_PASSWORD` | RabbitMQ password | — |
| `AMQP_HOST` | RabbitMQ hostname | — |
| `AMQP_PORT` | RabbitMQ port | `5672` |
| `AMQP_VHOST` | Virtual host | — |

## Security Best Practices

1. Rotate secrets regularly, especially `MICROSOFT_CLIENT_SECRET` and `ENCRYPTION_KEY`
2. Use an external secret manager (e.g., AWS Secrets Manager, Azure Key Vault, HashiCorp Vault) rather than static Kubernetes secrets
3. Keep `LOGS_DIAGNOSTICS_DATA_POLICY` set to `conceal` (the default) in production to avoid logging sensitive data
4. Enable network policies to restrict inbound and outbound traffic to only required services
5. Monitor deployments using the provided Grafana dashboards and alert rules (`grafana.dashboard.enabled: true`, `alerts.enabled: true`)
