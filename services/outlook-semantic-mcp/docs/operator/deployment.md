<!-- confluence-page-id: -1 -->
<!-- confluence-space-key: PUBDOC -->

## Prerequisites

Before deploying the Outlook Fat MCP Server, ensure you have:

- Kubernetes cluster (1.25+)
- Helm 3.x installed
- PostgreSQL 14+ database
- RabbitMQ 3.12+ instance
- Kong Gateway with public access configured
- Microsoft Entra ID app registration ([Authentication Guide](./authentication.md))
- Public DNS hostname for webhook callbacks

## Helm Chart

The Outlook Fat MCP Server is deployed using a Helm chart that wraps the `backend-service` chart.

### Add Helm Repository

```bash
helm registry login ghcr.io/unique-ag/helm-charts
```

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

Create the following Kubernetes secrets before deployment:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: outlook-semantic-mcp-secrets
  namespace: outlook-semantic-mcp
type: Opaque
stringData:
  DATABASE_URL: "postgresql://user:password@host:5432/outlook_fat_mcp"
  AMQP_URL: "amqp://user:password@rabbitmq:5672/outlook-semantic-mcp"
  MICROSOFT_CLIENT_SECRET: "<from-entra-app-registration>"
  MICROSOFT_WEBHOOK_SECRET: "<128-char-random-string>"
  AUTH_HMAC_SECRET: "<64-char-hex-string>"
  ENCRYPTION_KEY: "<64-char-hex-string>"
```

### Generating Secrets

```bash
# Generate MICROSOFT_WEBHOOK_SECRET (128 characters)
openssl rand -hex 64

# Generate AUTH_HMAC_SECRET (64 characters hex = 256 bits)
openssl rand -hex 32

# Generate ENCRYPTION_KEY (64 characters hex = 256 bits)
openssl rand -hex 32
```

## Minimal Values Configuration

```yaml
server:
  envVars:
    - secretRef:
        name: outlook-semantic-mcp-secrets

mcpConfig:
  app:
    selfUrl: https://outlook.mcp.example.com

  microsoft:
    clientId: "12345678-1234-1234-1234-123456789012"

  unique:
    apiBaseUrl: http://api-gateway.unique:8080
    ingestionServiceBaseUrl: http://node-ingestion.unique:8091
```

**Note:** Ingress is disabled by default. Traffic routing is handled by Kong Gateway via HTTPRoute or KongIngress resources configured separately.

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
kubectl exec -it deploy/outlook-semantic-mcp -- pnpm run db:migrate
```

## Health Checks

The service exposes health endpoints:

| Endpoint | Purpose |
|----------|---------|
| `/health` | Kubernetes liveness probe |
| `/ready` | Kubernetes readiness probe |

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

```yaml
alerts:
  enabled: true
  defaultAlerts:
    graphql:
      enabled: true
    uniqueApi:
      enabled: true
```

## Network Policies

Network policies are enabled by default to restrict ingress traffic:

```yaml
server:
  networkPolicy:
    enabled: true
    policyTypes:
      - Ingress
```

## Terraform Modules

Terraform modules are available for:

- **Entra Application**: `deploy/terraform/azure/outlook-semantic-mcp-entra-application/`
- **Secrets Management**: `deploy/terraform/azure/outlook-semantic-mcp-secrets/`

See [Authentication Guide](./authentication.md) for Terraform usage.

## Troubleshooting

See [FAQ](../faq.md) for common questions and deployment issues.
