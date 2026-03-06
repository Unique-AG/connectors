# Confluence Connector — Deployment Infrastructure

## Prerequisites

Before proceeding with a deployment, ensure familiarity with the following tools:

1. [Kubernetes](https://kubernetes.io/docs/home/) — container orchestration
2. [Terraform](https://developer.hashicorp.com/terraform/docs) — infrastructure as code
3. [Helm](https://helm.sh/docs/) — Kubernetes package manager

---

## Repository Structure

The deployment configuration is distributed across two repositories (no Infrastructure PR needed):

### 1. [Connectors](https://github.com/Unique-AG/connectors/tree/main/services/confluence-connector/deploy)

Contains the core deployment artifacts:

- **Docker build** — container image for the application
- **Terraform modules**:
  - `confluence-connector-secrets` — provisions placeholder secrets in Azure Key Vault for manual credential management. Creates secrets with a `manual-` prefix and ignores subsequent value changes so that manually set credentials are not overwritten by Terraform.
- **Helm charts** — define the Kubernetes deployment of the application, including multi-tenant configuration via `connectorConfig.tenants[]`

### 2. [Monorepo](https://github.com/Unique-AG/monorepo/tree/master/gitops-resources/argocd/clusters/unique/qa/application-specs/connectors/confluence-connector)

References the Helm charts from the Connectors repository and provides environment-specific static configuration:

- `app.yaml` — ArgoCD Application spec with Helm values (tenant configs, network policy, alerts, Grafana)
- `secrets.yaml` — ExternalSecret syncing OAuth 2.0 client secrets from Azure Key Vault into Kubernetes Secrets

### Infrastructure

**Not required.** Unlike outlook-semantic-mcp or sharepoint-connector, confluence-connector does not need an Azure Entra ID App Registration. Authentication is handled directly via Confluence OAuth 2.0 (2LO) client credentials or Personal Access Tokens (PAT), with secrets stored manually in Azure Key Vault.

---

## Secret Management

Secrets are managed via Azure Key Vault with manual provisioning:

### Azure Key Vault (via Terraform + manual)

The `confluence-connector-secrets` Terraform module creates **placeholder** secrets in Azure Key Vault with the value `<TO BE SET MANUALLY>`. The `lifecycle { ignore_changes }` block ensures Terraform never overwrites manually set values.

Default placeholders (per-tenant):
- `manual-confluence-connector-pat-dc` — PAT for the Data Center tenant
- `manual-confluence-connector-client-secret-cloud` — OAuth 2.0 client secret for the Cloud tenant

After Terraform provisions the placeholders, set the real values manually:

```sh
az keyvault secret set \
  --vault-name qa-app-common \
  --name manual-confluence-connector-pat-dc \
  --value "<actual-PAT>"

az keyvault secret set \
  --vault-name qa-app-common \
  --name manual-confluence-connector-client-secret-cloud \
  --value "<actual-client-secret>"
```

### Kubernetes Secrets (via ESO)

The `secrets.yaml` ExternalSecret in the Monorepo syncs the Key Vault secrets into a single Kubernetes Secret (`confluence-connector-v2-secret`) using the External Secrets Operator (ESO) with the `kv-app-common` ClusterSecretStore.

### End-to-end secrets chain

| Terraform placeholder | Key Vault name | ESO remoteRef | K8s secret key | Pod env var | Tenant config value |
|---|---|---|---|---|---|
| `confluence-connector-pat-dc` | `manual-confluence-connector-pat-dc` | `manual-confluence-connector-pat-dc` | `CONFLUENCE_PAT_DC` | `CONFLUENCE_PAT_DC` | `os.environ/CONFLUENCE_PAT_DC` |
| `confluence-connector-client-secret-cloud` | `manual-confluence-connector-client-secret-cloud` | `manual-confluence-connector-client-secret-cloud` | `CONFLUENCE_CLIENT_SECRET_CLOUD` | `CONFLUENCE_CLIENT_SECRET_CLOUD` | `os.environ/CONFLUENCE_CLIENT_SECRET_CLOUD` |

---

## Multi-Tenant Configuration

The connector supports multiple Confluence tenants in a single deployment. Each tenant is configured via `connectorConfig.tenants[]` in the Helm values and rendered into a separate YAML file mounted as a ConfigMap.

### Authentication modes

| Mode | Field | Description |
|------|-------|-------------|
| `oauth_2lo` | `clientSecret` | **Required.** OAuth 2.0 client secret. Use `os.environ/ENV_VAR_NAME` to read from an environment variable at runtime. |
| `pat` | `token` | **Required.** Personal Access Token. Use `os.environ/ENV_VAR_NAME` to read from an environment variable at runtime. |

Secrets are resolved at runtime via the `os.environ/` prefix convention — the value is read from the named environment variable when the config is loaded.

### Instance types

| Type | Description | OAuth token endpoint |
|------|-------------|---------------------|
| `cloud` | Atlassian Cloud. Requires `cloudId`. API calls go via `api.atlassian.com` | `https://api.atlassian.com/oauth/token` |
| `data-center` | Self-hosted Confluence. API calls go via the configured `baseUrl` | `{baseUrl}/rest/oauth2/latest/token` |

---

## Initial Deployment

An initial deployment requires two sequential pull requests:

1. **[Connectors](https://github.com/Unique-AG/connectors/tree/main/services/confluence-connector/deploy)** — implement the deployment configuration (Terraform module, Helm charts)
2. **[Monorepo](https://github.com/Unique-AG/monorepo/tree/master/gitops-resources/argocd/clusters/unique/qa/application-specs/connectors/confluence-connector)** — after the Connectors PR is merged and a release tag exists, open the Monorepo PR to wire the ArgoCD application specs

### Deployment Flow

1. Merge the Connectors PR — this triggers release-please to create a release PR
2. Merge the release PR — this creates the git tag (e.g., `confluence-connector@2.0.0-alpha.1`)
3. Merge the Monorepo PR — Atlantis runs `terraform apply` on `76-connectors.tf` to provision Key Vault placeholders, ArgoCD picks up the application spec
4. Set the real secret values in Azure Key Vault (see [Secret Management](#secret-management))
5. Sync the ArgoCD application — ESO pulls the Key Vault secrets, the workload starts

---

## Network Policy Setup

QA (and UAT1) clusters enforce **Cilium Network Policies** with default-deny for both ingress and egress.
New services must explicitly declare every allowed connection or they will time out silently.

Reference: [Confluence — Fixing Cilium Network Policies](https://unique-ch.atlassian.net/wiki/spaces/ptf/pages/1891860560/Fixing+Cilium+Network+Policies)
— see **Fix Network Policy on QA** section and **HubblePolicyDropsImmediate** for debugging.

### Required egress rules

| Destination | Port | Purpose |
|-------------|------|---------|
| `kube-system` / `kube-dns` | 53 (ANY) | DNS resolution |
| `finance-gpt` / `node-scope-management` | 8080 (TCP) | Scope management API |
| `finance-gpt` / `node-ingestion` | 8080 (TCP) | Ingestion API |
| `confluence.qa.unique.app` | 443 (TCP) | Data Center Confluence API + OAuth token |
| `api.atlassian.com` | 443 (TCP) | Cloud Confluence API + OAuth token |
| `*.atlassian.net` | 443 (TCP) | Cloud Confluence base URL |

### Required ingress rules

| Source | Port | Purpose |
|--------|------|---------|
| `system` / `prometheus` | 51350 (TCP) | Prometheus metrics scraping |
| `world` (ephemeral ports 32768-60999) | TCP | Return traffic from external services |

### Debugging

If the pod starts but cannot reach external services or internal APIs:

1. Check the `HubblePolicyDropsImmediate` alert in Prometheus/Alertmanager
2. Use Hubble CLI or UI to identify dropped flows
3. Add the missing egress/ingress rules to the network policy in the monorepo `app.yaml`
4. Expect to iterate — the outlook-semantic-mcp deployment required two follow-up PRs to get network policies right

---

## Key Files

| File | Purpose |
|------|---------|
| `deploy/Dockerfile` | Multi-stage Docker build |
| `deploy/terraform/azure/confluence-connector-secrets/` | Terraform module for Key Vault secret placeholders |
| `deploy/helm-charts/confluence-connector/` | Helm chart with multi-tenant configuration |
| `deploy/helm-charts/confluence-connector/templates/tenant-config.yaml` | Generates per-tenant ConfigMap YAML files |
| `monorepo: .../connectors/confluence-connector/app.yaml` | ArgoCD Application spec with Helm values and network policy |
| `monorepo: .../connectors/confluence-connector/secrets.yaml` | ESO ExternalSecret — syncs Key Vault secrets into Kubernetes |

---

## References

- Connectors PR (Terraform + Helm): https://github.com/Unique-AG/connectors/pull/339
- Monorepo PR (ArgoCD + secrets + network policy): https://github.com/Unique-AG/monorepo/pull/21122
- Analogous deployment: `services/outlook-semantic-mcp/deploy/README.md`
- ESO ExternalSecret docs: https://external-secrets.io/latest/api/externalsecret/

---

## Tips and Tricks

- **Validate Helm charts locally** — from `services/confluence-connector/deploy/helm-charts`, run:
  ```sh
  helm template confluence-connector ./confluence-connector -f confluence-connector/ci/data-center-oauth2lo-values.yaml
  ```
  Requires [Helm](https://helm.sh/docs/intro/install/) to be installed.

- **Dry-run Terraform locally** — from `services/confluence-connector/deploy/terraform/azure/confluence-connector-secrets`:
  ```sh
  terraform init
  terraform plan -var 'key_vault_id=/subscriptions/.../resourceGroups/.../providers/Microsoft.KeyVault/vaults/qa-app-common'
  ```

- **Check tenant config rendering** — after deploying, exec into the pod and verify:
  ```sh
  kubectl exec -n finance-gpt deploy/confluence-connector-v2 -- cat /app/tenant-configs/dogfood-data-center-tenant-config.yaml
  kubectl exec -n finance-gpt deploy/confluence-connector-v2 -- cat /app/tenant-configs/dogfood-cloud-tenant-config.yaml
  ```
