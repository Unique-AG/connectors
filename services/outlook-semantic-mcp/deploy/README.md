# Outlook Semantic MCP — Deployment Infrastructure

## Prerequisites

Before proceeding with a deployment, ensure familiarity with the following tools:

1. [Kubernetes](https://kubernetes.io/docs/home/) — container orchestration
2. [Terraform](https://developer.hashicorp.com/terraform/docs) — infrastructure as code
3. [Helm](https://helm.sh/docs/) — Kubernetes package manager

---

## Repository Structure

The deployment configuration is distributed across three repositories:

### 1. [Connectors](https://github.com/Unique-AG/connectors/tree/main/services/outlook-semantic-mcp/deploy)

Contains the core deployment artifacts:

- **Docker build** — container image for the application
- **Terraform modules** — two modules are defined:
  - `outlook-semantic-mcp-entra-application` — provisions the Microsoft Entra App Registration and all associated configuration required by the MCP service
  - `outlook-semantic-mcp-secrets` — **not used** in the QA environment. This module is intended for external clients without ESO. Internally, secrets are provisioned via ESO generators (see [Secret Management](#secret-management) below)
- **Helm charts** — define the Kubernetes deployment of the application

### 2. [Monorepo](https://github.com/Unique-AG/monorepo/tree/master/gitops-resources/argocd/clusters/unique/qa/application-specs/mcp/outlook-semantic)

References the Helm charts from the Connectors repository and provides environment-specific static configuration. Additionally manages one-time secret provisioning via the External Secrets Operator (ESO):

- `outlook-semantic-mcp-hmac-secret`
- `outlook-semantic-mcp-webhook-secret`
- `outlook-semantic-mcp-encryption-key`

### 3. [Infrastructure](https://github.com/Unique-AG/infrastructure/blob/main/providers/azure/unique-ag/identity/52-outlook-semantic-mcp.preview.application.tf)

References the required Terraform modules from the Connectors repository. Once applied, the outputs (e.g., `client_id`, `tenant_id`) must be inlined into the [Monorepo](https://github.com/Unique-AG/monorepo/tree/master/gitops-resources/argocd/clusters/unique/qa/application-specs/mcp/outlook-semantic) configuration — these are non-sensitive static values that do not change after provisioning.

---

## Secret Management

Secrets are managed in two layers:

### Azure Key Vault (via Terraform)

The `outlook-semantic-mcp-entra-application` Terraform module (analogous to `teams-mcp-entra-application`) creates the Azure App Registration and writes the generated `client_secret` into Azure Key Vault (`kv-uq-identity-001.vault.azure.net`).

The `kv.secrets.yaml` ExternalSecret in the Monorepo syncs this secret from Key Vault into a Kubernetes Secret using the External Secrets Operator (ESO).

### Generated Secrets (via ESO Password Generator)

Random secrets (`AUTH_HMAC_SECRET`, `ENCRYPTION_KEY`, `MICROSOFT_WEBHOOK_SECRET`) are generated in-cluster using the ESO `Password` generator resource (see `passwords.secrets.yaml`). These exist only as Kubernetes Secrets and are **not** stored in Azure Key Vault.

### Why we do not use `outlook-semantic-mcp-secrets` Terraform module for all secrets in QA?

The `outlook-semantic-mcp-secrets` module is designed for **external clients** that do not have ESO installed. Internally, ESO generators are used instead, which removes the need for a separate Terraform apply and reduces deployment complexity.

---

## Initial Deployment

An initial deployment requires three sequential pull requests:

1. **[Connectors](https://github.com/Unique-AG/connectors/tree/main/services/outlook-semantic-mcp/deploy)** — implement the deployment configuration (Terraform modules, Helm charts)
2. **[Infrastructure](https://github.com/Unique-AG/infrastructure/blob/main/providers/azure/unique-ag/identity/)** — once the Connectors PR is merged, open an Infrastructure PR to provision the required Azure resources using the Terraform modules from the Connectors repository
3. **[Monorepo](https://github.com/Unique-AG/monorepo/tree/master/gitops-resources/argocd/clusters/unique/qa/application-specs/mcp/outlook-semantic)** — after the Infrastructure PR is merged and Terraform has applied the changes, open the Monorepo PR to wire the ArgoCD application specs to the Helm charts defined in the Connectors repository

### Deployment Flow

1. Merge the Connectors PR — this triggers release please to create a Release pr
1. Merge the Infrastructure PR — this triggers a GitHub Actions pipeline (no Atlantis) that provisions the App Registration and writes the Key Vault secret
2. Collect the GitHub Actions output values required to finalize the Monorepo PR
3. Merge the Monorepo PR to deploy the ArgoCD application specs
4. ArgoCD syncs the cluster: ESO pulls the Key Vault secret, the Password generators create the random secrets, and the workload starts

> **Note:** If you want to point the service to the **dogfood tenant** in QA, not the `unique` tenant you can add the Terraform provisioned app from `unique` qa to the dogfood tenant using this magic link: https://login.microsoftonline.com/{tenant-id}/v2.0/adminconsent?client_id={client-id}&scope=https://graph.microsoft.com/.default
---

## Naming Conventions

Azure resource names follow the existing project conventions. Key Vault names must comply with Azure naming constraints (length and allowed characters). Use a suffix or prefix to distinguish the Outlook MCP identity store from other resources — avoid encoding the full service name if it exceeds Azure limits.

---

## Key Files

| File | Purpose |
|------|---------|
| `deploy/terraform/azure/outlook-semantic-mcp-entra-application/` | Provisions the App Registration and writes `client_secret` to Key Vault |
| `monorepo: .../mcp/outlook/kv.secrets.yaml` | ESO ExternalSecret — syncs the Key Vault secret into a Kubernetes Secret |
| `monorepo: .../mcp/outlook/passwords.secrets.yaml` | ESO Password generators — creates random secrets as Kubernetes Secrets |

---

## References

- Infrastructure PR: https://github.com/Unique-AG/infrastructure/pull/1817
- Monorepo PR: https://github.com/Unique-AG/monorepo/pull/20744
- Connectors PR (Terraform for `unique` tenant, not used in QA): https://github.com/Unique-AG/connectors/pull/310
- ESO Password Generator docs: https://external-secrets.io/v0.8.1/api/generator/password/
- Analogous module: `services/teams-mcp/deploy/terraform/azure/teams-mcp-entra-application/main.tf`


## Tips and Tricks

- **Validate Helm charts locally** — from `services/outlook-semantic-mcp/deploy/helm-charts`, run `sh render.sh` to render and validate the chart templates. Requires [Helm](https://helm.sh/docs/intro/install/) to be installed.
- **Dry-run Terraform locally** — create a `<name>.tfvars` file with the variable values you want to supply, then run:
  ```sh
  terraform plan -var-file="<name>.tfvars"
  ```
  To apply against a test tenant:
  ```sh
  terraform apply -var-file="<name>.tfvars"
  ```
  Requires the [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) to be installed and authenticated.


## Network policy setup

QA (and UAT1) clusters enforce **Cilium Network Policies** with default-deny for both ingress and egress.
New services must explicitly declare every allowed connection or they will time out silently.

This document captures the investigation and fixes made in March 2026 when `outlook-semantic-mcp`
was first deployed to QA and could not reach `node-ingestion`, `node-scope-management`, or RabbitMQ.

Reference: [Confluence — Fixing Cilium Network Policies](https://unique-ch.atlassian.net/wiki/spaces/ptf/pages/1891860560/Fixing+Cilium+Network+Policies)
see **Fix Network Policy on QA** section and **HubblePolicyDropsImmediate** for debugging.

### 1. Network policy values added to monorepo

**PR #20999** — initial network policy rules (ingress from Kong/Prometheus/kubelet, egress to DNS,
Postgres, internal services, Microsoft Graph APIs).

**PR #21027** — critical follow-up: added the missing egress rule for **RabbitMQ** (`eventing`
namespace, port `5672`). The pod was crashing at startup because it could not connect to AMQP and
the startup probe timed out. Also if you compare the pr with the final version there was a mistake
on allowing access to rabbitmq instance.

Network policy for outlook semnatic mcp:

```
[gitops-resources/argocd/clusters/unique/qa/application-specs/mcp/outlook-semantic/network-policy.values.yaml](https://github.com/Unique-AG/monorepo/blob/master/gitops-resources/argocd/clusters/unique/qa/application-specs/mcp/outlook-semantic/network-policy.values.yaml)
```
