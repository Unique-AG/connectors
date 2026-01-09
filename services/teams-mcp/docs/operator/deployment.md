# Deployment Guide

## Prerequisites

Before deploying the Teams MCP Connector, ensure you have:

- Kubernetes cluster (1.25+)
- Helm 3.x installed
- PostgreSQL 14+ database
- RabbitMQ 3.12+ instance
- Kong Gateway with public access configured
- Microsoft Entra ID app registration ([Authentication Guide](./authentication.md))
- Public DNS hostname for webhook callbacks

## Helm Chart

The Teams MCP Connector is deployed using a Helm chart that wraps the `backend-service` chart.

### Add Helm Repository

```bash
helm registry login ghcr.io/unique-ag/helm-charts
```

### Install

```bash
helm install teams-mcp oci://ghcr.io/unique-ag/helm-charts/teams-mcp \
  --namespace teams-mcp \
  --create-namespace \
  --values values.yaml
```

### Upgrade

```bash
helm upgrade teams-mcp oci://ghcr.io/unique-ag/helm-charts/teams-mcp \
  --namespace teams-mcp \
  --values values.yaml
```

## Required Secrets

Create the following Kubernetes secrets before deployment:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: teams-mcp-secrets
  namespace: teams-mcp
type: Opaque
stringData:
  DATABASE_URL: "postgresql://user:password@host:5432/teams_mcp"
  AMQP_URL: "amqp://user:password@rabbitmq:5672/teams-mcp"
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
        name: teams-mcp-secrets

mcpConfig:
  app:
    selfUrl: https://teams.mcp.example.com

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
kubectl exec -it deploy/teams-mcp -- pnpm run db:migrate
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

- **Entra Application**: `deploy/terraform/azure/teams-mcp-entra-application/`
- **Secrets Management**: `deploy/terraform/azure/teams-mcp-secrets/`

See [Authentication Guide](./authentication.md) for Terraform usage.

## Troubleshooting Deployment

See [FAQ](../faq.md) for common questions and deployment issues.
