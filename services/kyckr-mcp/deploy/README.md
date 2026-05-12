# Kyckr MCP — Deployment

## Helm chart

The Helm chart is at `deploy/helm-charts/kyckr-mcp/`. It uses the shared `backend-service` chart as a dependency.

To render and validate locally:

```bash
cd deploy/helm-charts
sh render.sh
```

## Secrets

Provide the following as Kubernetes Secrets via `server.envVars` in the Helm values:

| Secret key | Description |
|------------|-------------|
| `KYCKR_API_KEY` | Kyckr API key (Bearer token) |
| `MCP_API_KEY` | Required shared secret protecting the MCP endpoint. The server mounts at `/<MCP_API_KEY>/mcp`; clients use the api-key as the URL-path prefix. |
