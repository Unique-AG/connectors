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
| `AUTH_HMAC_SECRET` | 64-character hex string | JWT signing key — generate with `openssl rand -hex 32` |
| `ENCRYPTION_KEY` | 64-character hex string | AES-256-GCM token encryption key — generate with `openssl rand -hex 32` |

For `external` auth mode, also provide via secret:

| Variable | Format | Description |
|----------|--------|-------------|
| `UNIQUE_ZITADEL_CLIENT_SECRET` | String | Zitadel OAuth client secret |

### Application Configuration

Set via `mcpConfig.app` in Helm values:

| Variable | Helm Path | Default | Description |
|----------|-----------|---------|-------------|
| `SELF_URL` | `mcpConfig.app.selfUrl` | (required) | Public URL of the MCP server, used for OAuth callbacks |
| `PORT` | — | `9542` | Local HTTP port the server binds to |
| `MCP_DEBUG_MODE` | `mcpConfig.app.mcpDebugMode` | `disabled` | Set to `enabled` to expose debug tools and extra debugging data in tool responses |
| `APP_BUFFER_LOGS` | `mcpConfig.app.bufferLogs` | `disabled` | Buffer logs before writing to reduce I/O (`enabled`/`disabled`). When unset, defaults to buffering enabled. |
| `DEFAULT_MAIL_FILTERS` | `mcpConfig.defaultMailFilters` | `{"ignoredBefore":"2025-06-06","ignoredContents":[],"ignoredSenders":[]}` | JSON string controlling which emails are synced |

### Microsoft Configuration

Set via `mcpConfig.microsoft` in Helm values:

| Variable | Helm Path | Default | Description |
|----------|-----------|---------|-------------|
| `MICROSOFT_CLIENT_ID` | `mcpConfig.microsoft.clientId` | (required) | Entra app client ID |
| `MICROSOFT_PUBLIC_WEBHOOK_URL` | `mcpConfig.microsoft.publicWebhookUrl` | same as `SELF_URL` | Public webhook URL if different from `SELF_URL` |
| `MICROSOFT_SUBSCRIPTION_EXPIRATION_TIME_HOURS_UTC` | `mcpConfig.microsoft.subscriptionExpirationTimeHoursUTC` | `3` | Hour of day in UTC (0–23) when scheduled subscription renewals occur |

### Unique API Configuration

Set via `mcpConfig.unique` in Helm values:

| Variable | Helm Path | Default | Description |
|----------|-----------|---------|-------------|
| `UNIQUE_SERVICE_AUTH_MODE` | `mcpConfig.unique.serviceAuthMode` | `cluster_local` | Auth mode: `cluster_local` or `external` |
| `UNIQUE_INGESTION_SERVICE_BASE_URL` | `mcpConfig.unique.ingestionServiceBaseUrl` | (required) | Unique ingestion service endpoint |
| `UNIQUE_SCOPE_MANAGEMENT_SERVICE_BASE_URL` | `mcpConfig.unique.scopeManagementServiceBaseUrl` | (required) | Unique scope management service endpoint |
| `UNIQUE_STORE_INTERNALLY` | `mcpConfig.unique.storeInternally` | `enabled` | Whether to store emails internally in Unique knowledge base (`enabled`/`disabled`). Helm default is not set; the application default is `enabled`. |
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

Set via `mcpConfig.auth` in Helm values (optional — defaults are suitable for most deployments):

| Variable | Helm Path | Default | Description |
|----------|-----------|---------|-------------|
| `AUTH_ACCESS_TOKEN_EXPIRES_IN_SECONDS` | `mcpConfig.auth.accessTokenExpiresInSeconds` | `60` | MCP access token TTL in seconds |
| `AUTH_REFRESH_TOKEN_EXPIRES_IN_SECONDS` | `mcpConfig.auth.refreshTokenExpiresInSeconds` | `2592000` | MCP refresh token TTL in seconds (30 days) |

### Runtime Configuration

Set via `server.env` in Helm values for plain config, or via `server.envVars` (with `valueFrom.secretKeyRef`) for secrets:

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `info` | Log level: `fatal`, `error`, `warn`, `info`, `debug`, `trace`, `silent` |
| `MAX_HEAP_MB` | `1920` | Node.js max heap size in MB |
| `NODE_ENV` | `production` | Node environment |

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
      x-user-id: "<your-service-account-user-id>"

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

```yaml
mcpConfig:
  unique:
    serviceAuthMode: cluster_local
    ingestionServiceBaseUrl: http://node-ingestion.unique:8091
    scopeManagementServiceBaseUrl: http://node-scope-management.unique:8092
    serviceExtraHeaders:
      x-company-id: "<your-company-id>"
      x-user-id: "<your-service-account-user-id>"
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

### When a Zitadel Service Account is Required

A Zitadel service account is only needed when using `external` auth mode. It allows the Outlook MCP Server to authenticate with the Unique API using OAuth client credentials, without relying on in-cluster header-based auth.

### Creating a Zitadel Service Account

1. **Navigate to Zitadel**

   - Log in to your Zitadel instance
   - Select the organization where the Outlook MCP Server will operate

2. **Create a Service Account**

   - Go to **Service Accounts** in the organization settings
   - Click **New Service Account**
   - Provide a descriptive name (e.g., "Outlook MCP Server Service Account")
   - Assign appropriate permissions for ingestion and scope management

3. **Generate a Client Secret**

   - In the service account settings, create a new **Client Secret**
   - Copy the secret value — it will not be shown again

4. **Note the Required IDs**

   - **Client ID**: The OAuth client ID for the service account
   - **Project ID**: The Zitadel project ID used for audience validation
   - **OAuth Token URL**: Your Zitadel instance token endpoint (e.g., `https://your-instance.zitadel.cloud/oauth/v2/token`)

5. **Store the Secret in Kubernetes**

   ```bash
   kubectl create secret generic outlook-semantic-mcp-secrets \
     --from-literal=UNIQUE_ZITADEL_CLIENT_SECRET="<client-secret>" \
     ...
   ```

6. **Configure in Helm Values**

   ```yaml
   server:
     envVars:
       - name: UNIQUE_ZITADEL_CLIENT_SECRET
         valueFrom:
           secretKeyRef:
             name: outlook-semantic-mcp-secrets
             key: UNIQUE_ZITADEL_CLIENT_SECRET

   mcpConfig:
     unique:
       serviceAuthMode: external
       zitadel:
         clientId: "<zitadel-client-id>"
         oauthTokenUrl: "https://your-instance.zitadel.cloud/oauth/v2/token"
         projectId: "<zitadel-project-id>"
   ```

### Service Account Permissions

The service account must have permissions to:

- Submit content to the ingestion service
- Create and manage scopes via the scope management service

## Mail Filters

The `DEFAULT_MAIL_FILTERS` value controls which emails are synced during the initial import and ongoing sync. It is a JSON string set via `mcpConfig.defaultMailFilters`.

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
