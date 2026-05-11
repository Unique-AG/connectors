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
| `MCP_ACCESS_TOKEN` | Required shared secret protecting the `/mcp` endpoint |
