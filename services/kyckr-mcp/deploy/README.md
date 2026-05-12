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

| Secret key | KV slot | Source | Description |
|------------|---------|--------|-------------|
| `KYCKR_API_KEY` | `manual-kyckr-api-key` | Kyckr portal | Kyckr REST API Bearer token. |
| `MCP_API_KEY` | `manual-kyckr-mcp-key` | Operator-generated, once: `openssl rand -hex 32` | Shared secret protecting the MCP endpoint. The server mounts at `/<MCP_API_KEY>/mcp`; clients use the api-key as the URL-path prefix. |

Both slots are created empty by the `kyckr-mcp-secrets` Terraform module; the operator pastes the actual values into Azure Key Vault post-apply.
