# Design: Confluence Connector Terraform Secrets

## Problem

The confluence-connector-v2 ExternalSecret references `confluence-connector-api-token` in `kv-app-common`, but no Terraform provisions this secret. Without Terraform, the secret must be created manually in Azure Key Vault, bypassing infrastructure-as-code and audit trails. Following the SharePoint connector pattern, secrets should be managed through a dedicated Terraform module.

Additionally, the current ExternalSecret `remoteRef.key` doesn't follow the `manual-` prefix convention used by the SharePoint connector's `secrets_placeholders` pattern.

## Solution

### Overview

Create a Terraform module in the connectors repo at `services/confluence-connector/deploy/terraform/azure/confluence-connector-secrets/` following the SharePoint connector pattern. The module creates placeholder secrets in Key Vault (values set manually by ops). Reference the module from `76-connectors.tf` in the QA infrastructure. Fix the ExternalSecret naming to use the `manual-` prefix.

### Architecture

The module is simpler than SharePoint's — no TLS certificate generation, just `secrets_placeholders`:

**Module structure:**
```
services/confluence-connector/deploy/terraform/azure/confluence-connector-secrets/
├── main.tf        # azurerm_key_vault_secret with lifecycle ignore_changes
├── variables.tf   # key_vault_id + secrets_placeholders (default: confluence-connector-api-token)
└── outputs.tf     # Secret names for reference
```

**`main.tf`** creates `azurerm_key_vault_secret` resources with `manual-` prefix and `lifecycle { ignore_changes = [value] }` so Terraform won't overwrite manually-set values.

**`variables.tf`** defines:
- `key_vault_id` (required) — ID of the Key Vault
- `secrets_placeholders` (map) — defaults to `{ confluence-connector-api-token = {} }`

**Infrastructure reference** in `76-connectors.tf` (QA):
```terraform
module "confluence_connector" {
  source       = "github.com/unique-ag/connectors.git//services/confluence-connector/deploy/terraform/azure/confluence-connector-secrets?depth=1&ref=confluence-connector@2.0.0-alpha.1"
  key_vault_id = module.core-infra.key_vault_id_app_common
}
```

**ExternalSecret fix** — Update `secrets.yaml` `remoteRef.key` from `confluence-connector-api-token` to `manual-confluence-connector-api-token`.

### Error Handling

If the Key Vault secret doesn't exist yet after Terraform apply, the ExternalSecret will fail to sync. The pod will crash-loop until the value is manually set via `az keyvault secret set`. This is the same behavior as the SharePoint connector.

### Testing Strategy

No automated tests — Terraform modules are validated by `terraform plan` and `terraform apply` in the target environment.

## Out of Scope

- TLS certificate generation (not needed for Confluence API token auth)
- Zitadel client secret provisioning (future work when `external` auth mode is needed)
- Prod environment infrastructure changes (QA only for now)
- Enterprise sandbox (`sb-camastral`) changes
- Running `terraform apply` (done by ops team)

## Tasks

1. **Create Terraform module in connectors repo** — Create `services/confluence-connector/deploy/terraform/azure/confluence-connector-secrets/` with `main.tf`, `variables.tf`, and `outputs.tf`. Follow the SharePoint module pattern but without TLS certificate resources.

2. **Add module reference in QA infrastructure** — Add `module "confluence_connector"` to `infrastructure/providers/azure/unique-ag/tenants/unique/qa/lz/76-connectors.tf` referencing the new module.

3. **Fix ExternalSecret remoteRef key** — Update `secrets.yaml` `remoteRef.key` from `confluence-connector-api-token` to `manual-confluence-connector-api-token` to match the Terraform naming convention.
