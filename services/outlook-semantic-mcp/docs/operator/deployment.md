<!-- confluence-page-id: 2064449566 -->
<!-- confluence-space-key: PUBDOC -->

# Deployment

## Prerequisites

Before deploying the Outlook Semantic MCP Server, ensure you have:

- Kubernetes cluster (1.25+)
- Helm 3.x installed
- PostgreSQL 17+ database
- RabbitMQ 4+ instance
- Kong Gateway 3+ with public access configured (Kong is the default but any ingress controller that supports the required routing will work)
- Microsoft Entra ID app registration ([Authentication Guide](./authentication.md))
- Public DNS hostname for webhook callbacks

## Helm Chart

The Outlook Semantic MCP Server is deployed using a Helm chart that wraps the [`backend-service`](https://github.com/Unique-AG/helm-charts/tree/main/charts/backend-service) chart.

### Add Helm Repository

```bash
helm registry login ghcr.io
```

Use a GitHub Personal Access Token (PAT) with `read:packages` scope as the password.

### Install

```bash
helm install outlook-semantic-mcp oci://ghcr.io/unique-ag/helm-charts/outlook-semantic-mcp \
  --namespace outlook-semantic-mcp \
  --create-namespace \
  --values values.yaml
```

### Upgrade

```bash
helm upgrade outlook-semantic-mcp oci://ghcr.io/unique-ag/helm-charts/outlook-semantic-mcp \
  --namespace outlook-semantic-mcp \
  --values values.yaml
```

## Required Secrets

The service requires seven Kubernetes secrets to be present before deployment. For the full reference (format, description, and generation commands), see [Configuration — Required Secrets](./configuration.md#required-secrets).

### Provisioning with Terraform (recommended)

A Terraform module is provided to provision all secrets in Azure Key Vault:

```
deploy/terraform/azure/outlook-semantic-mcp-secrets/
```

This module:

- **Auto-generates** cryptographic secrets (`AUTH_HMAC_SECRET`, `ENCRYPTION_KEY`, `MICROSOFT_WEBHOOK_SECRET`) using secure random bytes and stores them in Azure Key Vault.
- **Creates placeholders** for manually managed secrets (`DATABASE_URL`, `AMQP_URL`, `MICROSOFT_CLIENT_SECRET`, `UNIQUE_ZITADEL_CLIENT_SECRET`) that must be set directly in Azure Key Vault after provisioning.
- Supports **secret rotation** via a `rotation_counter` variable.

Once secrets are in Azure Key Vault, sync them to Kubernetes using the [External Secrets Operator](https://external-secrets.io/) (ESO). Create an `ExternalSecret` resource that references each Key Vault entry and produces the corresponding Kubernetes secret.

See [Authentication Guide](./authentication.md) for Terraform usage details on the Entra application module.

### Manual provisioning

If you are not using Terraform and ESO, create the Kubernetes secrets directly:

```bash
kubectl create secret generic outlook-semantic-mcp-secrets \
  --namespace outlook-semantic-mcp \
  --from-literal=DATABASE_URL="postgresql://user:password@host:5432/outlook_semantic_mcp" \
  --from-literal=AMQP_URL="amqp://user:password@rabbitmq:5672/outlook-semantic-mcp" \
  --from-literal=MICROSOFT_CLIENT_SECRET="<from-entra-app-registration>" \
  --from-literal=MICROSOFT_WEBHOOK_SECRET="$(openssl rand -hex 64)" \
  --from-literal=AUTH_HMAC_SECRET="$(openssl rand -hex 32)" \
  --from-literal=ENCRYPTION_KEY="$(openssl rand -hex 32)"
```

```bash
kubectl create secret generic outlook-semantic-mcp-zitadel-secret \
  --namespace outlook-semantic-mcp \
  --from-literal=UNIQUE_ZITADEL_CLIENT_SECRET="<your-zitadel-client-secret>"
```

## Minimal Values Configuration

The following example uses `cluster_local` service auth mode. Each secret is referenced individually using `secretKeyRef`.

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
  app:
    selfUrl: https://outlook.semantic.mcp.example.com

  microsoft:
    clientId: "12345678-1234-1234-1234-123456789012"

  unique:
    serviceAuthMode: cluster_local
    ingestionServiceBaseUrl: http://node-ingestion.unique:8091
    scopeManagementServiceBaseUrl: http://node-scope-management.unique:8092
    serviceExtraHeaders:
      x-company-id: "<your-company-id>"
      x-user-id: "<your-service-account-user-id>"

  # IMPORTANT: `ignoredBefore` is mandatory — the application will not start without it.
  # Adjust it to control how far back the initial email sync goes. Setting this date far
  # in the past can cause very large initial syncs for users with large mailboxes,
  # potentially taking hours and consuming significant Microsoft Graph API quota.
  defaultMailFilters: '{"ignoredBefore":"2025-06-06","ignoredContents":[],"ignoredSenders":[]}'
```

**PostgreSQL backups:** Strongly recommended. Without a backup, all users must re-authenticate and full sync restarts from scratch. See [Disaster Recovery — Backup Recommendations](./disaster-recovery.md#backup-recommendations).

**Note:** Ingress is disabled by default. Enable it and configure hosts/TLS in the `ingress` section of your `values.yaml`. The chart defaults to `ingressClassName: kong` but any ingress controller can be used. The application listens on port `51345` (set via `server.ports.application` in the Helm values; the default `9542` only applies outside Helm). MCP servers need to be hosted on their own domain because the OAuth redirect URI (`<SELF_URL>/auth/callback`) must resolve to this service — sharing a domain with other services would cause routing conflicts. Ensure your ingress allows large request bodies (for attachment uploads) and has appropriate timeouts for long-running OAuth flows.

## Database Migration

Database migrations run automatically on deployment via a Helm hook:

```yaml
server:
  hooks:
    migration:
      enabled: true
      command: |
        pnpm run db:migrate
```

To run migrations manually:

```bash
kubectl exec -it deploy/outlook-semantic-mcp -n outlook-semantic-mcp -- pnpm run db:migrate
```

## Health Checks

The service exposes health endpoints:

| Endpoint | Purpose |
|----------|---------|
| `/probe` | Kubernetes liveness and readiness probe (configured via the Helm chart's probe settings) |

## Monitoring

### Prometheus Metrics

Metrics are exposed on port `51346` at `/metrics`.

```yaml
server:
  ports:
    metrics: 51346
  env:
    OTEL_EXPORTER_PROMETHEUS_HOST: "0.0.0.0"
    OTEL_EXPORTER_PROMETHEUS_PORT: "51346"
    OTEL_METRICS_EXPORTER: "prometheus"
```

### Grafana Dashboard

A Grafana dashboard is automatically created when enabled:

```yaml
grafana:
  dashboard:
    enabled: true
    folder: mcp-servers
```

### Prometheus Alerts

Default alerts are included for GraphQL and Unique API errors:

Alerts are disabled by default. Enable them in your `values.yaml`:

```yaml
alerts:
  enabled: true  # disabled by default — enable for production
  defaultAlerts:
    graphql:
      enabled: true
    uniqueApi:
      enabled: true
```

## Network Policies

If your cluster enforces network policies, the following traffic must be allowed for the service to function correctly.

### Ingress (who calls the service)

| Source | Port | Purpose |
|--------|------|---------|
| API Gateway (e.g. Kong) | `51345` (TCP) | Inbound HTTP traffic including Microsoft OAuth callbacks and webhook notifications |
| Prometheus | `51346` (TCP) | Metrics scraping |
| kubelet | `51345` (TCP) | Startup, liveness, and readiness probes |

### Egress (what the service calls)

| Destination | Port | Purpose |
|-------------|------|---------|
| DNS (kube-dns) | `53` (UDP/TCP) | Cluster DNS resolution |
| PostgreSQL | `5432` (TCP) | Database access |
| RabbitMQ | `5672` (TCP) | Message queue |
| `node-ingestion` | `8091` (TCP) | Unique ingestion service |
| `node-scope-management` | `8092` (TCP) | Unique scope management service |
| `login.microsoftonline.com`, `graph.microsoft.com` | `443` (TCP) | Microsoft OAuth and Graph API |
| `outlook.office.com`, `outlook.office365.com` | `443` (TCP) | Attachment upload sessions (Microsoft Graph) |

The [`backend-service`](https://github.com/Unique-AG/helm-charts/tree/main/charts/backend-service) Helm chart supports Cilium network policies via the `server.networkPolicy` values. See the chart documentation for configuration details.

## Terraform Modules

Terraform modules are available for:

- **Entra Application**: `deploy/terraform/azure/outlook-semantic-mcp-entra-application/`
- **Secrets Management**: `deploy/terraform/azure/outlook-semantic-mcp-secrets/` (for external deployments without ESO)

See [Authentication Guide](./authentication.md) for Terraform usage.
