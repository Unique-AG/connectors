<!-- confluence-page-id: 2064449566 -->
<!-- confluence-space-key: PUBDOC -->

# Deployment

## Prerequisites

Before deploying the Outlook Semantic MCP Server, ensure you have:

- Kubernetes cluster (1.25+)
- Helm 3.x installed
- PostgreSQL 17+ database
- RabbitMQ 4+ instance
- Kong Gateway 3+ with public access configured
- Microsoft Entra ID app registration ([Authentication Guide](./authentication.md))
- Public DNS hostname for webhook callbacks

## Helm Chart

The Outlook Semantic MCP Server is deployed using a Helm chart that wraps the `backend-service` chart.

### Add Helm Repository

```bash
helm registry login ghcr.io
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

For external auth mode, also create:

```bash
# For external auth mode, also create:
kubectl create secret generic outlook-semantic-mcp-zitadel-secret \
  --namespace outlook-semantic-mcp \
  --from-literal=UNIQUE_ZITADEL_CLIENT_SECRET="<your-zitadel-client-secret>"
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
```

**Note:** Ingress is disabled by default. Traffic routing is handled by Kong Gateway. Enable and configure ingress in `values.yaml` for your deployment.

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
| `/probe` | Kubernetes liveness and readiness probe |

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

Cilium network policies are enforced in QA and UAT clusters under a default-deny ingress and egress model. New deployments must declare all allowed connections.

Allowed ingress traffic:

- Kong Gateway (HTTP/HTTPS)
- Prometheus scraper (port `51346`)
- kubelet (health check probes)

Allowed egress traffic:

- DNS (UDP/TCP port 53)
- PostgreSQL (port 5432)
- RabbitMQ (port 5672)
- Microsoft Graph APIs (HTTPS)
- Unique internal services (`node-ingestion`, `node-scope-management`)

See [`../../../deploy/README.md`](../../../deploy/README.md) for details on the network policy configuration.

## Terraform Modules

Terraform modules are available for:

- **Entra Application**: `deploy/terraform/azure/outlook-semantic-mcp-entra-application/`
- **Secrets Management**: `deploy/terraform/azure/outlook-semantic-mcp-secrets/` (for external deployments without ESO)

See [Authentication Guide](./authentication.md) for Terraform usage.
