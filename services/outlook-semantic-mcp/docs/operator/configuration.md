<!-- confluence-page-id: 2065629188 -->
<!-- confluence-space-key: PUBDOC -->

## Deployment Modes

The server supports two deployment modes controlled by `MCP_BACKEND`. **Choose your mode before configuring anything else** — it determines which infrastructure components you need and which configuration sections apply.

| | `microsoft_graph_and_unique_api` (default) | `microsoft_graph` |
|---|---|---|
| Search | Semantic (Unique KB) + KQL (Graph), merged | KQL (Graph) only |
| Ingestion | Full sync + live catch-up | None |
| Tools | Those listed in `MCP_TOOLS`, from 10 mail, 4 sync, 5 debug and 8 calendar tools | Those listed in `MCP_TOOLS`, from 10 mail and 8 calendar tools |
| Requires Unique KB | Yes | Only with `UNIQUE_ATTACHMENTS=enabled` (the default) |
| Requires RabbitMQ | Yes | Yes |
| Folder filtering | Supported | Not supported |

**Configuration impact:**

| Section | Mode A (`microsoft_graph_and_unique_api`) | Mode B (`microsoft_graph`) |
|---|---|---|
| Required Secrets | All secrets | Same, except `UNIQUE_ZITADEL_CLIENT_SECRET`: needed for `external` auth, and only with `UNIQUE_ATTACHMENTS=enabled` |
| Ingestion Configuration (`mcpConfig.ingestion`) | Required | **Omit entirely** |

Two values are accepted for `MCP_BACKEND`:

- **`microsoft_graph_and_unique_api`** (default) — dual backend mode. Emails are ingested into the Unique Knowledge Base via the full sync pipeline; `search_emails` runs both Microsoft Graph KQL search and Unique KB semantic search in parallel and merges the results; the sync tools (`sync_progress`, `run_full_sync`, etc.) can be listed in [`MCP_TOOLS`](#MCP_TOOLS). Requires the `mcpConfig.ingestion` section to be configured.
- **`microsoft_graph`** — lean mode. No ingestion pipeline is started; `search_emails` and `open_email` call the Microsoft Graph Search API directly. Sync tools (`sync_progress`, `run_full_sync`, `pause_full_sync`, `resume_full_sync`, `restart_full_sync`) are not available; the server refuses to start when [`MCP_TOOLS`](#MCP_TOOLS) lists one. Folder filtering is not supported because the Graph Search API does not expose a folder-scoped KQL predicate. The `mcpConfig.ingestion` section is not required and is ignored.

The Helm chart sets `microsoft_graph_and_unique_api` by default. The service itself has no default, so set `MCP_BACKEND` when running it outside the chart.

## Environment Variables

All configuration is done via environment variables, either directly or through Helm values.

### Required Secrets

These must be provided via Kubernetes secrets:

| Variable | Format | Description | Required for |
|----------|--------|-------------|-------------|
| `DATABASE_URL` | `postgresql://user:pass@host:5432/db` | PostgreSQL connection string | Both modes |
| `AMQP_URL` | `amqp://user:pass@host:5672/vhost` | RabbitMQ connection string (or use individual `AMQP_*` fields — see below) | Both modes |
| `MICROSOFT_CLIENT_SECRET` | String from Azure portal | Entra app client secret | Both modes |
| `MICROSOFT_WEBHOOK_SECRET` | 128-character hex string | Webhook validation secret | Both modes |
| `AUTH_HMAC_SECRET` | 64-character hex string | HMAC-SHA256 session state signing key | Both modes |
| `ENCRYPTION_KEY` | 64-character hex string | AES-256-GCM token encryption key | Both modes |
| `UNIQUE_ZITADEL_CLIENT_SECRET` | String | Zitadel OAuth client secret | `external` service auth, when Unique is needed |
| `PROXY_PASSWORD` | String | Proxy password. Inline value or `os.environ/ENV_VAR_NAME`. | `username_password` proxy auth only |

**Connection string formats:**

- `DATABASE_URL`: `postgresql://user:password@host:5432/dbname?sslmode=require` — see [PostgreSQL connection string docs](https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNSTRING)
- `AMQP_URL`: `amqp://user:password@host:5672/vhost` — see [RabbitMQ URI specification](https://www.rabbitmq.com/docs/uri-spec). Alternatively, use individual fields instead of a connection string:

| Variable | Description | Default |
|----------|-------------|---------|
| `AMQP_USERNAME` | RabbitMQ username | — |
| `AMQP_PASSWORD` | RabbitMQ password | — |
| `AMQP_HOST` | RabbitMQ hostname | — |
| `AMQP_PORT` | RabbitMQ port | `5672` |
| `AMQP_VHOST` | Virtual host | — |

#### Generating Secrets

The following secrets must be generated with a cryptographically secure random source:

| Variable | Command |
|----------|---------|
| `MICROSOFT_WEBHOOK_SECRET` | `openssl rand -hex 64` |
| `AUTH_HMAC_SECRET` | `openssl rand -hex 32` |
| `ENCRYPTION_KEY` | `openssl rand -hex 32` |

### Microsoft Configuration

Set via `mcpConfig.microsoft` in Helm values:

| Variable | Helm key | Default | Description |
|----------|----------|---------|-------------|
| `MICROSOFT_CLIENT_ID` | `clientId` | (required) | Entra app client ID |
| `MICROSOFT_SIGN_IN_TENANT_ID` | `signInTenantId` | `common` | Sign-in tenant ID the OAuth login should open. Set a GUID when sign-in must use the Enterprise Application (service principal) in a foreign tenant. Leave as `common` when users choose their directory at login. Independent of `clientId`/`clientSecret`; not the tenant that owns the app registration |
| `MICROSOFT_ADMIN_CONSENT_REDIRECT_URI` | `adminConsentRedirectUri` | `https://www.unique.ai/setup/consent-completed/entra-id` | Where Microsoft Entra sends a tenant admin after they grant admin consent through `/admin/consent`. Must be registered as a redirect URI on the app registration |
| `MICROSOFT_PUBLIC_WEBHOOK_URL` | `publicWebhookUrl` | defaults to `SELF_URL` | Base URL for Microsoft Graph webhook callbacks — see [MICROSOFT_PUBLIC_WEBHOOK_URL](#MICROSOFT_PUBLIC_WEBHOOK_URL) |
| `MICROSOFT_SUBSCRIPTION_EXPIRATION_TIME_HOURS_UTC` | `subscriptionExpirationTimeHoursUTC` | `3` | UTC hour (0–23) when daily subscription renewals run |
| `MICROSOFT_OFFLINE_ACCESS` | `offlineAccess` | `enabled` | Whether sign-in requests `offline_access` — see [MICROSOFT_OFFLINE_ACCESS](#MICROSOFT_OFFLINE_ACCESS) |
| `MICROSOFT_PROFILE_SCOPES` | `profileScopes` | `enabled` | Whether sign-in requests `profile` and `email`. `openid` is always requested. The server reads the user's profile from Microsoft Graph `GET /me`, not from the ID token these scopes shape, so `disabled` changes nothing it stores |

### Unique API Configuration

Set via `mcpConfig.unique` in Helm values.

The server talks to Unique only when an enabled feature needs it: `MCP_BACKEND=microsoft_graph_and_unique_api`, or `UNIQUE_ATTACHMENTS=enabled`. Otherwise it does not read the other `UNIQUE_*` variables, the chart does not render them, and the server makes no call to Unique. With `MCP_BACKEND=microsoft_graph`, the folder sync never calls Unique. When Unique is needed and a variable is missing, startup fails and names the variable.

| Variable | Helm key | Default | Description |
|----------|----------|---------|-------------|
| `UNIQUE_ATTACHMENTS` | `attachments` | `enabled` | `enabled` lets `draft_email` and `add_attachments_to_draft_email` attach `unique://content/{contentId}` files from the Unique knowledge base. `disabled` accepts only `data:` URIs |
| `UNIQUE_SERVICE_AUTH_MODE` | `serviceAuthMode` | `cluster_local` | Auth mode: `cluster_local` or `external` |
| `UNIQUE_INGESTION_SERVICE_BASE_URL` | `ingestionServiceBaseUrl` | (required when Unique is needed) | Unique ingestion service endpoint |
| `UNIQUE_SCOPE_MANAGEMENT_SERVICE_BASE_URL` | `scopeManagementServiceBaseUrl` | (required when Unique is needed) | Unique scope management service endpoint |
| `UNIQUE_STORE_INTERNALLY` | `storeInternally` | `enabled` | Store emails as files in the Knowledge Base — see [UNIQUE_STORE_INTERNALLY](#UNIQUE_STORE_INTERNALLY) |
| `UNIQUE_SERVICE_EXTRA_HEADERS` | `serviceExtraHeaders` | (required for `cluster_local`, when Unique is needed) | `x-company-id` and `x-user-id` headers for `cluster_local` mode — see [UNIQUE_SERVICE_EXTRA_HEADERS](#UNIQUE_SERVICE_EXTRA_HEADERS) |
| `UNIQUE_ZITADEL_CLIENT_ID` | `zitadel.clientId` | (required for `external`, when Unique is needed) | Zitadel OAuth client ID |
| `UNIQUE_ZITADEL_OAUTH_TOKEN_URL` | `zitadel.oauthTokenUrl` | (required for `external`, when Unique is needed) | Zitadel OAuth token URL |
| `UNIQUE_ZITADEL_PROJECT_ID` | `zitadel.projectId` | (required for `external`, when Unique is needed) | Zitadel project ID for audience validation |

### Proxy Configuration

The server supports HTTP/HTTPS forward proxies for environments where outbound internet access is only available through a proxy. Proxy settings are configured via environment variables (managed by the Helm chart's `proxyConfig` section).

| Mode                | Description                          |
|---------------------|--------------------------------------|
| `none`              | Proxy disabled (default)             |
| `no_auth`           | Proxy enabled without authentication |
| `username_password` | Basic authentication proxy           |
| `ssl_tls`           | TLS client certificate proxy         |

**Common options** (required for `no_auth`, `username_password`, and `ssl_tls` modes):

| Variable                   | Description                                                      |
|----------------------------|------------------------------------------------------------------|
| `PROXY_HOST`               | Proxy server hostname                                            |
| `PROXY_PORT`               | Proxy server port                                                |
| `PROXY_PROTOCOL`           | `http` or `https`                                                |
| `PROXY_SSL_CA_BUNDLE_PATH` | (Optional) Path to CA bundle for verifying proxy TLS certificate |
| `PROXY_HEADERS`            | (Optional) JSON string of custom headers for CONNECT request     |

**`username_password` mode** adds:

| Variable         | Description                                                                                          |
|------------------|------------------------------------------------------------------------------------------------------|
| `PROXY_USERNAME` | Proxy username. Inline value or `os.environ/ENV_VAR_NAME` so the username is not stored in Helm values. |
| `PROXY_PASSWORD` | Proxy password. Inline value or `os.environ/ENV_VAR_NAME` (typically loaded from a secret).          |

**`ssl_tls` mode** adds:

| Variable              | Description                    |
|-----------------------|--------------------------------|
| `PROXY_SSL_CERT_PATH` | Path to TLS client certificate |
| `PROXY_SSL_KEY_PATH`  | Path to TLS client key         |

For `ssl_tls` mode, certificates must be mounted into the pod and the path env vars must point at those files. The chart does not mount proxy certs automatically. Example (Secret-backed volume):

```yaml
volumes:
  - name: tmp
    emptyDir:
      sizeLimit: 20Gi
  - name: proxy-certs
    secret:
      secretName: outlook-semantic-mcp-proxy-certs
volumeMounts:
  - name: tmp
    mountPath: /tmp
  - name: proxy-certs
    mountPath: /app/proxy-certs
    readOnly: true

proxyConfig:
  enabled: true
  authMode: ssl_tls
  host: proxy.example.com
  port: 8443
  protocol: https
  sslCertPath: /app/proxy-certs/client.crt
  sslKeyPath: /app/proxy-certs/client.key
  # Optional when the proxy uses a private/self-signed CA:
  # sslCaBundlePath: /app/proxy-certs/ca.crt
```

The service reads these files at startup; missing or unreadable paths prevent the pod from starting.

#### Traffic Routing

When the proxy is enabled, traffic is routed as follows:

| Target | Routing |
|--------|---------|
| Microsoft Graph, `login.microsoftonline.com`, Graph upload sessions, and passport Microsoft login | Always through the proxy |
| Unique API and blob-ingestion upload | Through the proxy only when `UNIQUE_SERVICE_AUTH_MODE` is `external`. Bypassed in `cluster_local` mode |
| Unique content download (cluster-local attachment stream) | Never proxied |

### Authentication Token Configuration

These tokens are issued by the MCP server to MCP clients (e.g., AI assistants) after a user completes OAuth. They are distinct from Microsoft tokens and control how long a client session remains valid without re-authentication.

Set via `mcpConfig.auth` in Helm values (optional — defaults are suitable for most deployments):

| Variable | Helm key | Default | Description |
|----------|----------|---------|-------------|
| `AUTH_ACCESS_TOKEN_EXPIRES_IN_SECONDS` | `accessTokenExpiresInSeconds` | `60` | TTL of the short-lived access token issued to MCP clients |
| `AUTH_REFRESH_TOKEN_EXPIRES_IN_SECONDS` | `refreshTokenExpiresInSeconds` | `2592000` | TTL of the long-lived refresh token issued to MCP clients (30 days). At most `3600` with `MICROSOFT_OFFLINE_ACCESS=disabled`, where it is the session length — see [MICROSOFT_OFFLINE_ACCESS](#MICROSOFT_OFFLINE_ACCESS) |
| `AUTH_DISABLE_RATE_LIMITING` | `disableRateLimiting` | `false` | Emergency switch: skip the rate limit on every OAuth route. Leave off unless rate limiting itself is suspected in an incident |

### Application Configuration

Set via `mcpConfig.app` in Helm values:

| Variable | Helm key | Default | Description |
|----------|----------|---------|-------------|
| `SELF_URL` | `selfUrl` | (required) | Public URL of the MCP server, used for OAuth callbacks |
| `PORT` | — | `9542` | HTTP port the server binds to — see [PORT](#PORT) |
| `MCP_DEBUG_MODE` | `mcpDebugMode` | `disabled` | Adds debug data to tool responses and allows the debug tools in `MCP_TOOLS`. **Do not leave enabled in production** — see [MCP_DEBUG_MODE](#MCP_DEBUG_MODE) |
| `MCP_BACKEND` | `mcpBackend` | (required; the chart sets `microsoft_graph_and_unique_api`) | Selects the search backend — see [Deployment Modes](#Deployment-Modes) |
| `MCP_TOOLS` | `tools` | (required) | Non-empty JSON array of the tool names to register. Listing a calendar tool turns calendar on — see [MCP_TOOLS](#MCP_TOOLS) and [Calendar tools](#Calendar-tools) |
| `DIRECTORY_SYNC_MODE` | `directorySyncMode` | `scheduled` | How the folder cache is refreshed: `scheduled` or `on_demand` — see [DIRECTORY_SYNC_MODE](#DIRECTORY_SYNC_MODE) |
| `EXCLUDED_SENSITIVITY_LABELS` | `excludedSensitivity.labels` | `[]` | JSON array of Purview sensitivity label ids or names. Mail carrying one is left out — see [Sensitivity exclusions](#Sensitivity-exclusions) |
| `EXCLUDED_LEGACY_SENSITIVITY` | `excludedSensitivity.legacy` | `[]` | JSON array of legacy Outlook sensitivity flags: `personal`, `private`, `confidential`. Mail flagged with one is left out — see [Sensitivity exclusions](#Sensitivity-exclusions) |
| `LOGS_BUFFERING` | `app.logsBuffering` | `enabled` | Buffer logs before writing. Set to `disabled` only for startup debugging |
| `LOGS_DIAGNOSTICS_DATA_POLICY` | `app.logsDiagnosticsDataPolicy` | `conceal` | Controls what diagnostic data is logged: `conceal` hides sensitive data, `disclose` shows full data |

### Delegated Access Configuration

Set via `mcpConfig.delegatedAccess` in Helm values:

| Variable | Helm key | Default | Description |
|----------|----------|---------|-------------|
| `DELEGATED_ACCESS_SCAN` | `scan` | `disabled` | Delegated access scanning mode — see [DELEGATED_ACCESS_SCAN](#DELEGATED_ACCESS_SCAN) |
| `DELEGATED_ACCESS_DISCOVERY_CRON_SCHEDULE` | `discoveryCronSchedule` | `0 */12 * * *` | Cron schedule for delegated access discovery runs. Required when `DELEGATED_ACCESS_SCAN` is not `disabled` |
| `DELEGATED_ACCESS_VERIFICATION_CRON_SCHEDULE` | `verificationCronSchedule` | `0 */4 * * *` | Cron schedule for delegated access verification runs. Required when `DELEGATED_ACCESS_SCAN` is `granular_access` |
| `DELEGATED_ACCESS_RECOVERY_CRON_SCHEDULE` | `recoveryCronSchedule` | `*/30 * * * *` | Cron schedule for recovering stuck delegated access discovery and verification jobs. Active when `DELEGATED_ACCESS_SCAN` is not `disabled` |
| `DELEGATED_ACCESS_STALENESS_THRESHOLD_HOURS` | `stalenessThresholdHours` | `24` | Hours after which a delegated access account is considered stale for the `/health` check |
| `DELEGATED_ACCESS_FAILURE_THRESHOLD` | `failureThreshold` | `0.15` | Fraction (0–1) of eligible delegated users that may be stale before the `/health` check reports down |
| `DELEGATED_ACCESS_SHARED_MAILBOX_EMAILS` | `sharedMailboxEmails` | (empty) | Comma-separated mailbox addresses to register as shared-mailbox profiles without an MCP login — see [DELEGATED_ACCESS_SHARED_MAILBOX_EMAILS](#DELEGATED_ACCESS_SHARED_MAILBOX_EMAILS) |
| `DELEGATED_ACCESS_SHARED_MAILBOX_SYNC_CRON_SCHEDULE` | `sharedMailboxSyncCronSchedule` | `0 */6 * * *` | Cron schedule for syncing those addresses into user profiles. Active when `DELEGATED_ACCESS_SCAN` is not `disabled` |

### Ingestion Configuration

!!! warning "Mode A (`microsoft_graph_and_unique_api`) only"
    This entire section applies only when `MCP_BACKEND` is `microsoft_graph_and_unique_api`. If you are deploying in `microsoft_graph` mode, omit all `mcpConfig.ingestion` values from your Helm configuration.

Set via `mcpConfig.ingestion` in Helm values:

| Variable | Helm key | Default | Description |
|----------|----------|---------|-------------|
| `INGESTION_DEFAULT_MAIL_FILTERS` | `defaultMailFilters` | (required) | JSON email sync filters — see [Mail Filters](#Mail-Filters) |
| `INGESTION_LIVE_CATCHUP_OVERLAPPING_WINDOW_MINUTES` | `liveCatchupOverlappingWindowMinutes` | `3` | Minutes to overlap each live catch-up sync run to account for Office 365 eventual consistency. Minimum: `2` — see [INGESTION_LIVE_CATCHUP_OVERLAPPING_WINDOW_MINUTES](#INGESTION_LIVE_CATCHUP_OVERLAPPING_WINDOW_MINUTES) |
| `INGESTION_LIVE_CATCHUP_RECHECK_OVERLAPPING_WINDOW_MINUTES` | `liveCatchupRecheckOverlappingWindowMinutes` | `10` | Minutes to overlap live catch-up ready-recheck runs. Minimum: `10` — see [INGESTION_LIVE_CATCHUP_RECHECK_OVERLAPPING_WINDOW_MINUTES](#INGESTION_LIVE_CATCHUP_RECHECK_OVERLAPPING_WINDOW_MINUTES) |
| `INGESTION_FULL_SYNC_RECOVERY_CRON` | `fullSyncRecoveryCron` | `*/2 * * * *` | Cron schedule for stuck full-sync recovery scans |
| `INGESTION_LIVE_CATCHUP_RECOVERY_CRON` | `liveCatchupRecoveryCron` | `*/5 * * * *` | Cron schedule for recovering live catch-ups stuck in `running` or `failed` state past their heartbeat threshold |
| `INGESTION_LIVE_CATCHUP_OAUTH_USERS_RECHECK_CRON` | `liveCatchupOauthUsersRecheckCron` | `*/10 * * * *` | Cron schedule for subscription-user live catch-up ready-recheck runs (retriggers users with an active subscription that haven't run in 30 minutes) |
| `INGESTION_LIVE_CATCHUP_SHARED_MAILBOX_RECHECK_CRON` | `liveCatchupSharedMailboxRecheckCron` | `*/10 * * * *` | Cron schedule for shared-mailbox live catch-up ready-recheck runs (retriggers shared-mailbox profiles that haven't run in 10 minutes) |
| `INGESTION_DELETE_INBOX_RECOVERY_CRON` | `deleteInboxRecoveryCron` | `*/5 * * * *` | Cron schedule for stuck inbox deletion recovery scans |
| `INGESTION_CONNECTIVITY_TIMEOUT_MS` | `connectivityTimeoutMs` | `3000` | Timeout in milliseconds for the Microsoft Graph connectivity check in `/health` |
| `INGESTION_SYNC_FAILURE_THRESHOLD` | `syncFailureThreshold` | `0.15` | Fraction (0–1) of eligible users that may be failing fullSync or liveCatchup before the `/health` check reports down |

### Runtime Configuration

Set via `server.env` in Helm values for plain config, or via `server.envVars` (with `valueFrom.secretKeyRef`) for secrets:

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `info` | Log level: `fatal`, `error`, `warn`, `info`, `debug`, `trace`, `silent` |
| `MAX_HEAP_MB` | `850` | Node.js max heap size in MB — see [MAX_HEAP_MB](#MAX_HEAP_MB) |
| `NODE_ENV` | `production` | Node environment |
| `NODE_EXTRA_CA_CERTS` | — | Path to a PEM file with additional CA certificates for TLS verification |
| `OTEL_METRICS_EXPORTER` | `prometheus` | OpenTelemetry metrics exporter |
| `OTEL_EXPORTER_PROMETHEUS_HOST` | `0.0.0.0` | Host for the Prometheus metrics scrape endpoint |
| `OTEL_EXPORTER_PROMETHEUS_PORT` | `51346` | Port for the Prometheus metrics scrape endpoint |
| `DIRECTORY_SYNC_CRON_SCHEDULE` | `*/5 * * * *` | Cron schedule for directory (folder tree) delta sync with `DIRECTORY_SYNC_MODE=scheduled`. No dedicated `mcpConfig.app` Helm path exists — set via `server.env` |

## Helm Values Reference

### Mode A Minimal Values Example

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
    MAX_HEAP_MB: 850
    NODE_ENV: production
    OTEL_METRICS_EXPORTER: prometheus
    OTEL_EXPORTER_PROMETHEUS_HOST: "0.0.0.0"
    OTEL_EXPORTER_PROMETHEUS_PORT: "51346"

mcpConfig:
  enabled: true

  app:
    selfUrl: https://outlook.semantic.mcp.example.com
    mcpDebugMode: disabled
    mcpBackend: microsoft_graph_and_unique_api
    tools:
      - list_mailboxes_and_directories
      - list_categories
      - draft_email
      - update_draft_email
      - add_attachments_to_draft_email
      - remove_attachments_from_draft_email
      - lookup_contacts
      - search_emails
      - fetch_next_search_pages
      - open_email
      - sync_progress
      - verify_inbox_connection
      - delete_inbox_data
      - reconnect_inbox

  delegatedAccess:
    scan: disabled
    # discoveryCronSchedule: '0 */12 * * *'   # required when scan != disabled
    # verificationCronSchedule: '0 */4 * * *'  # required when scan == granular_access
    # sharedMailboxEmails: "support@example.com,team@example.com"  # env-listed shared mailboxes; MCP login is optional

  microsoft:
    clientId: "12345678-1234-1234-1234-123456789012"
    # signInTenantId: common  # optional; set a foreign-tenant GUID to pin login to that service principal
    # publicWebhookUrl: https://outlook.semantic.mcp.example.com  # optional, defaults to selfUrl

  unique:
    serviceAuthMode: cluster_local
    ingestionServiceBaseUrl: http://node-ingestion.unique:8091
    scopeManagementServiceBaseUrl: http://node-scope-management.unique:8092
    serviceExtraHeaders:
      x-company-id: "<your-company-id>"
      x-user-id: "<your-zitadel-service-user-id>"
    # For external auth mode, replace serviceExtraHeaders with zitadel: — see Zitadel Service Account section below

  ingestion:
    defaultMailFilters:
      retentionWindowInDays: 95
      ignoredContents: []
      ignoredSenders: []
    # liveCatchupOverlappingWindowMinutes: 3    # optional, min 2
    # liveCatchupRecheckOverlappingWindowMinutes: 10  # optional, min 10
    # liveCatchupOauthUsersRecheckCron: "*/10 * * * *"         # optional
    # liveCatchupSharedMailboxRecheckCron: "*/10 * * * *"   # optional

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

### Mode B Minimal Values Example

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

mcpConfig:
  enabled: true

  app:
    selfUrl: https://outlook.semantic.mcp.example.com
    mcpBackend: microsoft_graph
    tools:
      - list_mailboxes_and_directories
      - list_categories
      - draft_email
      - update_draft_email
      - add_attachments_to_draft_email
      - remove_attachments_from_draft_email
      - lookup_contacts
      - search_emails
      - fetch_next_search_pages
      - open_email

  microsoft:
    clientId: "12345678-1234-1234-1234-123456789012"
    # signInTenantId: common  # optional; set a foreign-tenant GUID to pin login to that service principal

  unique:
    serviceAuthMode: cluster_local
    ingestionServiceBaseUrl: http://node-ingestion.unique:8091
    scopeManagementServiceBaseUrl: http://node-scope-management.unique:8092
    serviceExtraHeaders:
      x-company-id: "<your-company-id>"
      x-user-id: "<your-service-account-user-id>"
    # For external auth mode, replace serviceExtraHeaders with zitadel: — see Zitadel Service Account section below

  # No mcpConfig.ingestion section — omit entirely for microsoft_graph mode
```

### Service Auth Modes

#### cluster_local (Default)

For deployments within the same Kubernetes cluster as Unique. Uses in-cluster service URLs with `x-company-id` and `x-user-id` headers passed to all Unique API requests.

!!! warning "`x-user-id` must be a real Zitadel service user"
    The `x-user-id` value **must** be the ID of an actual service user created in Zitadel — it cannot be an arbitrary value. See [Zitadel Service Account](#Zitadel-Service-Account) for setup instructions.

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

## Security Best Practices

1. Rotate secrets regularly, especially `MICROSOFT_CLIENT_SECRET` and `ENCRYPTION_KEY`
2. Use an external secret manager (e.g., AWS Secrets Manager, Azure Key Vault, HashiCorp Vault) rather than static Kubernetes secrets
3. Keep `LOGS_DIAGNOSTICS_DATA_POLICY` set to `conceal` (the default) in production to avoid logging sensitive data
4. Enable network policies to restrict inbound and outbound traffic to only required services
5. Monitor deployments using the provided Grafana dashboards and alert rules (`grafana.dashboard.enabled: true`, `alerts.enabled: true`)

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

The service account must be assigned the following Zitadel permissions:

| Permission | Used For |
|------------|----------|
| `chat.admin.all` | Administrative access required for scope and folder management |
| `chat.knowledge.read` | Reading Knowledge Base scopes and content |
| `chat.knowledge.write` | Ingesting email content and managing scopes via the ingestion and scope management services |

## Configuration Reference

Detailed documentation for variables that require more context than the tables above provide.

### Runtime

#### PORT

The server listens on `PORT` (default `9542`). In Helm deployments, `server.ports.application` (default `51345`) overrides this value — the Helm chart injects the port via the deployment spec, so `PORT` typically does not need to be set explicitly.

#### MAX_HEAP_MB

Sets the Node.js `--max-old-space-size` flag. With the default of `850` MB, set the pod memory request/limit to at least ~1 GB to account for non-heap memory overhead (native modules, OS buffers, etc.).

### Microsoft

#### MICROSOFT_PUBLIC_WEBHOOK_URL

Microsoft Graph sends webhook callbacks (change notifications and lifecycle events) to this base URL. Microsoft appends `/mail-subscription/notification` and `/mail-subscription/lifecycle` to construct the full endpoints. The URL must be publicly reachable by Microsoft Graph.

This defaults to `SELF_URL`. Set it explicitly only when the externally reachable webhook URL differs from `SELF_URL` — for example, when using a dev tunnel in local development. In most production deployments the two values are identical.

Note: the Entra ID app registration redirect URI must match `SELF_URL/auth/callback`, not this variable.

#### MICROSOFT_OFFLINE_ACCESS

Set via `mcpConfig.microsoft.offlineAccess`. With `enabled` (default), sign-in requests `offline_access`, Microsoft returns a refresh token, and the server uses it to renew the user's Microsoft token and to run background jobs.

With `disabled`, sign-in does not request `offline_access` and the server stores no refresh token. The Microsoft access token lasts about an hour (60 to 90 minutes by default; a tenant policy can shorten it), and nothing renews it. So that the MCP client signs the user in again before it runs out:

- The MCP session ends `AUTH_REFRESH_TOKEN_EXPIRES_IN_SECONDS` after sign-in, however active the user is. Refreshing the MCP access token does not extend it. The server refuses to start when that is above `3600`.
- If Microsoft still rejects the token before then, the server clears the user's Microsoft token, ends their MCP session and answers with the error the MCP client turns into a sign-in prompt.

No background job can run without a refresh token, so `disabled` needs `MCP_BACKEND=microsoft_graph`, [`DIRECTORY_SYNC_MODE=on_demand`](#DIRECTORY_SYNC_MODE) and `DELEGATED_ACCESS_SCAN=disabled`. The server refuses to start otherwise, naming `MICROSOFT_OFFLINE_ACCESS`, and the chart refuses to render.

#### Requested Graph permissions

The server computes the Microsoft Graph permissions it requests from its configuration. The OAuth authorize request, token refresh and the Graph client all use the same list:

1. Always: `openid`, `User.Read` (sign-in) and `Mail.Read` (the folder sync runs for every deployment). Also `profile` and `email` unless [`MICROSOFT_PROFILE_SCOPES`](#Microsoft-Configuration) is `disabled`, and `offline_access` unless [`MICROSOFT_OFFLINE_ACCESS`](#MICROSOFT_OFFLINE_ACCESS) is `disabled`.
2. Each tool in [`MCP_TOOLS`](#MCP_TOOLS) adds what its Microsoft Graph calls need:
   - `draft_email`, `update_draft_email`, `add_attachments_to_draft_email` and `remove_attachments_from_draft_email`: `Mail.ReadWrite`.
   - `lookup_contacts`: `People.Read`.
   - `list_categories`, `search_emails`, `fetch_next_search_pages` and `open_email`: `MailboxSettings.Read` (categories and the mailbox time zone).
   - The calendar tools: `Calendars.ReadWrite.Shared`; all but `list_calendars` and `respond_to_invite` also `MailboxSettings.Read`. See [Calendar tools](#Calendar-tools).
   - The other tools need nothing beyond `Mail.Read`.
3. `MCP_BACKEND=microsoft_graph_and_unique_api` needs `Mail.Read` for the sync and the mail subscription.
4. Shared mailboxes, meaning [`DELEGATED_ACCESS_SCAN`](#DELEGATED_ACCESS_SCAN) is anything but `disabled`, add `User.Read.All` and `Mail.Read.Shared`. With a draft tool listed, they add `Mail.ReadWrite.Shared` instead of `Mail.Read.Shared`.
5. A write permission replaces its read permission: `Mail.ReadWrite` removes `Mail.Read`, and `Mail.ReadWrite.Shared` removes `Mail.Read.Shared`. A permission and its `.Shared` counterpart stay side by side.

The server sends the list sorted. Some selections and what they request:

| Selection | Requested permissions |
|-----------|-----------------------|
| The 10 mail tools, or the 14 with the sync tools, and `DELEGATED_ACCESS_SCAN` not `disabled` | `openid profile email offline_access User.Read User.Read.All MailboxSettings.Read Mail.ReadWrite Mail.ReadWrite.Shared People.Read`. This is the fixed list earlier versions always requested |
| The same, plus calendar tools | The list above plus `Calendars.ReadWrite.Shared` |
| The 10 mail tools, or the 14 with the sync tools, and `DELEGATED_ACCESS_SCAN=disabled` | `openid profile email offline_access User.Read MailboxSettings.Read Mail.ReadWrite People.Read` |
| `search_emails`, `fetch_next_search_pages`, `open_email`, `list_mailboxes_and_directories`, `list_categories` and `lookup_contacts`, with `DELEGATED_ACCESS_SCAN=disabled` | `openid profile email offline_access User.Read Mail.Read People.Read MailboxSettings.Read` |
| The same, with `MICROSOFT_OFFLINE_ACCESS=disabled` and `MICROSOFT_PROFILE_SCOPES=disabled` | `openid User.Read Mail.Read People.Read MailboxSettings.Read` |

Asking Entra for fewer permissions than the app was granted needs no consent. Asking for one the app was not granted does: users see a consent prompt, or need an admin where the tenant disables user consent. The `outlook-semantic-mcp-entra-application` Terraform module registers exactly this list, without `offline_access` and the OpenID scopes, which need no registration. It grants the list tenant-wide only when `service_principal_configuration` is set; without it, users or an admin consent at sign-in. Give it the same selection through `tools_preset` or `tools_enabled` and `delegated_access_scan` — see [Authentication](./authentication.md). Changing `MCP_TOOLS` or `DELEGATED_ACCESS_SCAN` can change the list, and users then consent to any permission the app was not granted before.

### Unique API

#### UNIQUE_STORE_INTERNALLY

When `enabled` (default), emails are ingested into the Unique Knowledge Base and stored as physical files, making them available for semantic search via `search_emails`.

When `disabled`, emails are ingested (metadata recorded) but not stored as files. They remain searchable via `search_emails`, but the email content is not persisted in the Knowledge Base.

#### UNIQUE_SERVICE_EXTRA_HEADERS

Required for `cluster_local` auth mode. Provide as a JSON object:

```json
{"x-company-id": "<your-company-id>", "x-user-id": "<your-zitadel-service-user-id>"}
```

- **`x-company-id`** — your organization's ID in the Unique platform. Find it in the Unique admin dashboard under **Settings > Organization**, or via the Unique API (`GET /api/company`).
- **`x-user-id`** — the Zitadel service user ID. See [Zitadel Service Account](#Zitadel-Service-Account).

### Application

#### MCP_DEBUG_MODE

When set to `enabled`, adds debug data to tool responses and allows five debug tools: `run_full_sync`, `pause_full_sync`, `resume_full_sync`, `restart_full_sync` and `admin_ops`. It does not register them by itself: a debug tool is registered only when it is also listed in [`MCP_TOOLS`](#MCP_TOOLS), and debug tools also need `MCP_BACKEND=microsoft_graph_and_unique_api`. These tools are intended for troubleshooting sync issues, but because MCP tools are scoped to the authenticated user there is no way to restrict them to operators only — all users can call them while they are registered. Enable only during active troubleshooting and disable immediately after.

#### MCP_TOOLS

Required. Set via `mcpConfig.app.tools`, a YAML list the chart renders as a JSON array. The chart fails to render while the list is empty. Only the listed tools are registered; there is no setting that registers every tool. For example, `["search_emails","fetch_next_search_pages","open_email"]` registers those three tools only.

Listing at least one calendar tool turns calendar on. See [Calendar tools](#Calendar-tools).

The listed tools decide part of the Microsoft Graph permissions the server requests. See [Requested Graph permissions](#Requested-Graph-permissions).

The server refuses to start, naming the tool and the setting, when:

- a listed name is unknown
- `sync_progress`, `verify_inbox_connection`, `delete_inbox_data` or `reconnect_inbox` is listed and `MCP_BACKEND` is not `microsoft_graph_and_unique_api`
- a debug tool (`run_full_sync`, `restart_full_sync`, `pause_full_sync`, `resume_full_sync`, `admin_ops`) is listed and `MCP_DEBUG_MODE` is not `enabled`; debug tools also need `MCP_BACKEND=microsoft_graph_and_unique_api`

Tool descriptions and the server instructions still mention other tools by name, including ones a deployment leaves out.

#### DIRECTORY_SYNC_MODE

Set via `mcpConfig.app.directorySyncMode`. The server keeps each user's Outlook folders in a table. `list_mailboxes_and_directories` lists them, and `search_emails` resolves its folder filter (`directories`) from them.

- **`scheduled`** (default) — a scan at startup and a cron job (`DIRECTORY_SYNC_CRON_SCHEDULE`) refresh the folders of every signed-in user and shared mailbox, with the stored Microsoft tokens.
- **`on_demand`** — no scan at startup and no cron job. The folders are refreshed with the calling user's own token: on every `list_mailboxes_and_directories` call, and before a `search_emails` call with a folder filter when the user's folders were last refreshed over 4 hours ago. Concurrent searches of one user share one refresh. When that refresh fails, the search uses the folders already cached, unless the user's Microsoft sign-in was revoked, and searches in the next 5 minutes do not try it again. The sign-in also refreshes them. A folder created in Outlook is therefore found by a folder filter at the latest 4 hours later, or at once after `list_mailboxes_and_directories`.

`on_demand` needs `MCP_BACKEND=microsoft_graph`, because ingestion syncs the folders itself, and `DELEGATED_ACCESS_SCAN=disabled`, because shared mailbox folders are refreshed only by the scheduled sync. The server refuses to start otherwise, and the chart refuses to render.

#### Sensitivity exclusions

Set via `mcpConfig.app.excludedSensitivity`. Mail with an excluded sensitivity is left out of `search_emails` and `fetch_next_search_pages`, and `open_email` answers it as not found, so the agent cannot tell it exists.

```yaml
mcpConfig:
  app:
    mcpBackend: microsoft_graph
    excludedSensitivity:
      labels: [Confidential, 2d69afbc-f32c-424f-83ad-75460acd2aa1]
      legacy: [private, confidential]
```

- **`labels`** (`EXCLUDED_SENSITIVITY_LABELS`) — Microsoft Purview sensitivity labels, each by its id (a GUID) or its name, ignoring case. A message is excluded when one of its labels matches. A sublabel carries only its own name and id, so list each sublabel to exclude.
- **`legacy`** (`EXCLUDED_LEGACY_SENSITIVITY`) — the sensitivity flag Outlook sets under *Options → Sensitivity*: `personal`, `private` or `confidential`.

The server reads both from each message Microsoft Graph returns, without an extra request: a search asks Graph for the two properties alongside its results, and `open_email` asks for them with the message. A message whose properties Graph does not return, or returns in a form the server cannot read, is left out as well. A results page the filter empties still carries its cursor, so `fetch_next_search_pages` continues past it. With both lists empty (the default) the requests to Graph are unchanged and nothing is filtered.

Both settings need `MCP_BACKEND=microsoft_graph`, because semantic search results from the Unique knowledge base carry no sensitivity to filter on. The server refuses to start otherwise, naming the setting, and the chart refuses to render. An unknown legacy flag, a blank label, or a value that is not a JSON array also stops the server at startup. `lookup_contacts` and the draft tools are not filtered.

#### Calendar tools

The calendar tools are `list_calendars`, `search_calendar_events`, `check_availability`, `suggest_meeting_times`, `respond_to_invite`, `create_event`, `update_event` and `cancel_event`. When [`MCP_TOOLS`](#MCP_TOOLS) lists at least one of them, the service registers the listed calendar tools, adds the calendar server instructions, and appends `Calendars.ReadWrite.Shared` to the Microsoft Graph OAuth and token-refresh scope string. When none is listed, calendar is off. `respond_to_invite` notifies the organizer immediately. `create_event`, `update_event`, and `cancel_event` notify other people after the user confirms. There is no draft state. `cancel_event` notifies attendees; it is not a silent delete.

The Entra app registration is gated separately: the `outlook-semantic-mcp-entra-application` Terraform module only registers `Calendars.ReadWrite.Shared` — and includes it in the tenant-wide delegated permission grant it creates when `service_principal_configuration` is set — when its selection includes a calendar tool, e.g. `tools_preset = ["mail", "calendar"]`. Runtime `getScopes()` still omits the calendar scope until `MCP_TOOLS` lists a calendar tool.

Do this in order. Listing a calendar tool before Entra has the scope breaks **mail** token refresh (`invalid_grant`).

1. Apply Terraform `outlook-semantic-mcp-entra-application` with the calendar tools in its selection, e.g. `tools_preset = ["mail", "calendar"]`.
2. Confirm the Entra app lists that delegated permission.
3. Add the calendar tools to `mcpConfig.app.tools` (`MCP_TOOLS`).
4. Existing connected users must **reconnect Outlook**, unless an Entra admin has already granted the extra scope tenant-wide. `reconnect_inbox` only renews the mail webhook; it does not re-run OAuth. The user has to start a new Outlook connection.
5. If a calendar tool returns `consentRequired: true`, Graph denied calendar permission on the signed-in user's own mailbox. Ask the user to reconnect Outlook (new Microsoft OAuth). Do not call `reconnect_inbox`. Do not send them to `/auth/authorize` — that is the MCP OAuth start URL for clients, not a user reconnect.

Calendar listing is Graph `GET /users/{caller}/calendars` (equivalent to `/me/calendars` for the signed-in user): the user's own calendars plus calendars shared with them that they accepted. Shared-mailbox **profiles** never call calendar tools — those profiles are ingestion-only.

See [Tools — Calendar](../technical/tools.md#Calendar) for ID namespaces and the tool reference, and [Authentication](./authentication.md) for the Entra app registration.

#### DELEGATED_ACCESS_SCAN

For step-by-step Microsoft 365 setup, see [Features — Delegated Access — Setup](../technical/features.md#Setup).

Set via `mcpConfig.delegatedAccess.scan`. Controls whether the service scans for delegated mailbox access granted between users at the Microsoft Exchange level. Three values are accepted:

- **`disabled`** (default) — delegated access scanning is off. No discovery or verification runs are scheduled. The server works with the signed-in user's own mailbox only. `draft_email`, `update_draft_email`, `add_attachments_to_draft_email`, `remove_attachments_from_draft_email` and `open_email` refuse a `mailbox` other than the user's own email address or user principal name (compared case-insensitively) with a tool error, before calling Microsoft Graph. `search_emails` searches only the mailboxes the user can access, so it skips another mailbox.
- **`full_access_only`** — discovers users who have been granted **Full Access (Read & Manage)** on a mailbox via Exchange admin. Uses the `/users/{email}/messages` endpoint to detect access. Requires `DELEGATED_ACCESS_DISCOVERY_CRON_SCHEDULE`.
- **`granular_access`** — discovers users who have been granted **folder-level access** (e.g., only "Inbox" or "RFQ" shared, not the entire mailbox). Uses the `/users/{email}/mailFolders` endpoint for discovery, followed by a verification pass to determine which folders are actually readable (since the folder listing can include parent folders of shared subfolders that are not themselves accessible). Requires both `DELEGATED_ACCESS_DISCOVERY_CRON_SCHEDULE` and `DELEGATED_ACCESS_VERIFICATION_CRON_SCHEDULE`.

`disabled` adds no shared-mailbox permission. `full_access_only` and `granular_access` add `User.Read.All` and `Mail.Read.Shared`, or `Mail.ReadWrite.Shared` instead of `Mail.Read.Shared` when a draft tool is listed in `MCP_TOOLS`. See [Requested Graph permissions](#Requested-Graph-permissions).

Earlier versions used any `mailbox` passed to those five tools, through `Mail.ReadWrite.Shared`, even with `disabled`. A deployment that drafts in or opens emails from shared mailboxes now sets `full_access_only` or `granular_access`.

**Choosing a mode:**

| Scenario | Recommended mode |
|----------|-----------------|
| No delegated mailbox access in your org | `disabled` |
| Users draft in or open emails from shared mailboxes | `full_access_only`, or `granular_access` for folder-level access |
| Users have Full Access (Read & Manage) granted via Exchange admin | `full_access_only` |
| Users share individual folders (e.g., Inbox, RFQ) with others | `granular_access` |

`granular_access` subsumes `full_access_only` — if your org uses both types of delegation, use `granular_access`.

!!! warning "`granular_access` requires Mode A — Mode B supports full access only"
    `granular_access` requires `MCP_BACKEND=microsoft_graph_and_unique_api` and will
    fail to start if configured with `microsoft_graph`. `full_access_only` is
    supported in both modes, but in Mode B only delegates with **full mailbox
    access** can search delegated mailboxes — honouring folder-level delegations
    would require querying every accessible folder individually, which is not
    implemented due to API rate limits.

> **Both users must be connected (ordinary user mailboxes, both modes).**
> Discovery only considers connected users — if the owner has not connected
> their account, there is nothing to discover or search regardless of mode. In
> Mode A the owner must also have completed the initial full sync for their
> emails to be available to the delegate. Shared mailboxes listed in
> `DELEGATED_ACCESS_SHARED_MAILBOX_EMAILS` may also sign in: their own token is
> then the primary credential and Full Access delegates are the backup. If they
> have not signed in, only the delegates must be connected. See
> [DELEGATED_ACCESS_SHARED_MAILBOX_EMAILS](#DELEGATED_ACCESS_SHARED_MAILBOX_EMAILS).

> **`full_access_only` — consider a more frequent discovery schedule.** When using
> `full_access_only`, discovery is the only revocation detection mechanism.
> Consider setting `DELEGATED_ACCESS_DISCOVERY_CRON_SCHEDULE` to run 4 times per
> day (e.g. `0 */6 * * *`) to reduce the window during which a revoked delegate
> can still search the owner's emails. In `granular_access` mode this is less
> critical because the verification job already runs every 4 hours.

#### DELEGATED_ACCESS_SHARED_MAILBOX_EMAILS

Comma-separated list of mailbox addresses to register as shared-mailbox profiles. Login as that mailbox is optional. Ignored when `DELEGATED_ACCESS_SCAN` is `disabled`. Helm: `mcpConfig.delegatedAccess.sharedMailboxEmails`.

Use this for:

1. A typical Microsoft 365 shared mailbox that has **no sign-in**. Nobody logs into the MCP as that mailbox; Full Access delegates query it.
2. A sign-in-eligible mailbox that several people use (including one that a founder occasionally logs into). List it here **even if** someone will complete MCP authorization as that account. When they sign in, the mailbox's own token is the primary credential and Full Access delegates are the backup. If nobody signs in, it behaves like (1).

If the identity is already connected as an OAuth user, the next shared-mailbox sync upgrades it to a dual profile (`shared-mailbox-with-login`) so it gains the delegate fallback. Removing an address from this list keeps a dual profile as a normal OAuth user and deletes ingested shared-mailbox content; a mailbox that never signed in is removed entirely.

Sync runs at startup when the list has changed, and on `DELEGATED_ACCESS_SHARED_MAILBOX_SYNC_CRON_SCHEDULE` (default every 6 hours). At least one connected user in the mailbox's domain is required so Graph `/users` can resolve the addresses. Mode A ingest and later Graph calls address these profiles as `users/{email}`. If the mailbox has signed in, its own token is tried first; otherwise (and on 401/403) a Full Access **delegate** is used — grant Full Access to everyone who needs access, and have those users connect their own accounts.

For setup steps see [Features — Shared mailboxes](../technical/features.md#3-shared-mailboxes).

#### Mail Filters

The `INGESTION_DEFAULT_MAIL_FILTERS` value controls which emails are synced during the initial import and ongoing sync. It is configured as a dictionary under `mcpConfig.ingestion.defaultMailFilters` and serialized to JSON automatically by the Helm chart.

> **Warning:** Changing `INGESTION_DEFAULT_MAIL_FILTERS` only affects newly synced emails. Emails that were already ingested under a previous filter configuration are **not** removed. To remove previously ingested emails, you must delete them manually.

| Field | Type | Description |
|-------|------|-------------|
| `retentionWindowInDays` | Positive integer | Number of days to retain emails. The effective cutoff rolls forward daily as `today - retentionWindowInDays`. Emails older than this window are excluded from sync and stamped with an `expiresAt` date for automatic expiry in the Knowledge Base. |
| `ignoredSenders` | Array of regex patterns | Regex patterns in `/pattern/flags` format tested against the sender's email address. Emails matching any pattern are excluded from sync. |
| `ignoredContents` | Array of regex patterns | Regex patterns in `/pattern/flags` format tested against both the email subject and body. Emails matching any pattern are excluded from sync. |

Patterns must be in `/pattern/flags` format (e.g. `/^noreply@example\.com$/i`, `/unsubscribe/i`). Patterns are validated against ReDoS attacks on ingestion — invalid or unsafe patterns are rejected.

We recommend setting `retentionWindowInDays` between **95 and 180 days** for most deployments:

- **High mail volume** (hundreds of emails per user per day): use a shorter window (closer to 95 days). A large window combined with high volume floods the Knowledge Base with content, degrades search quality, and increases ingestion costs.
- **Low mail volume** or deep-search requirements: a longer window (up to 180 days or beyond) is viable.

Values above 180 days are not recommended unless mail volume is low and the operational cost of a large Knowledge Base is acceptable.

```yaml
mcpConfig:
  ingestion:
    defaultMailFilters:
      retentionWindowInDays: 95
      ignoredContents:
        - "/unsubscribe/i"
      ignoredSenders:
        - "/^noreply@example\\.com$/i"
```

#### INGESTION_LIVE_CATCHUP_OVERLAPPING_WINDOW_MINUTES

Office 365 uses eventual consistency — messages can appear with a delayed `updatedAt` timestamp after the actual event. To avoid missing late-arriving messages, each live catch-up sync run re-queries an overlapping window of this many minutes. Default: `3` minutes. Minimum: `2`.

#### INGESTION_LIVE_CATCHUP_RECHECK_OVERLAPPING_WINDOW_MINUTES

Overlapping window (in minutes) for live catch-up ready-recheck runs. Uses a larger window than the standard run to account for higher latency during recheck scenarios. Minimum and default: `10`.
