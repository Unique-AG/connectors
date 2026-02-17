# Confluence Connector v2 — QA Deployment Checklist

Tracks open items across the three deployment PRs before merging.

## PRs

| # | Repo | Title | Branch |
|---|------|-------|--------|
| [#259](https://github.com/Unique-AG/connectors/pull/259) | connectors | Terraform module for Key Vault secrets | `confluence-connector/feat/terraform-secrets` |
| [#19872](https://github.com/Unique-AG/monorepo/pull/19872) | monorepo | QA GitOps resources (ArgoCD + ExternalSecret) | `gitops-resources/argocd/feat/confluence-connector-v2-qa` |
| [#19876](https://github.com/Unique-AG/monorepo/pull/19876) | monorepo | Terraform module reference in `76-connectors.tf` | `infrastructure/feat/confluence-connector-secrets` |

## Merge order

1. **PR #259** (connectors) — must merge first so the Terraform module source exists at the tag
2. **Wait for release-please** to create the `confluence-connector@2.0.0-alpha.1` tag
3. **PR #19876** (monorepo/infrastructure) — references the tag from step 2
4. **Run `terraform apply`** — provisions `manual-confluence-connector-pat` placeholder in Key Vault
5. **Ops: set the actual secret value** via `az keyvault secret set`
6. **PR #19872** (monorepo/gitops-resources) — ArgoCD picks up the Helm chart and ExternalSecret

## Open items

### 1. Verify `x-company-id` and `x-user-id` are correct for QA (PR #19872)

- **Status:** Likely fine (matches SharePoint connector QA values)
- **Values:** `x-company-id: "225319369280852798"`, `x-user-id: "335951437550850059"`
- **Action:** Confirm these are the intended QA service account IDs.

## Resolved items

### Switched from Cloud to On-Prem configuration (PR #19872)

Based on the local tenant config (`local-tenant-config.yaml`) the QA instance is on-prem. Updated `app.yaml`:
- `instanceType`: `cloud` -> `onprem`
- `baseUrl`: `https://example.atlassian.net/wiki` -> `https://confluence.qa.unique.app`
- `auth.mode`: `api_token` -> `pat`
- `apiRateLimitPerMinute`: added `100` (matching local config)
- `envVars`: `CONFLUENCE_API_TOKEN` -> `CONFLUENCE_PAT` (code reads `CONFLUENCE_PAT` for `pat` mode)
- Network policy egress: `*.atlassian.net`/`*.atlassian.com`/`auth.atlassian.com` -> `confluence.qa.unique.app`

Updated `secrets.yaml`:
- `secretKey`: `CONFLUENCE_API_TOKEN` -> `CONFLUENCE_PAT`
- `remoteRef.key`: `manual-confluence-connector-api-token` -> `manual-confluence-connector-pat`

### `auth.email` no longer needed

Was flagged as missing, but `email` is only required for `api_token` mode (Cloud). PAT mode doesn't need it.

### `module.core-infra.key_vault_id_app_common` reference (PR #19876)

- Initially looked broken because `unique/qa/lz/` appeared empty locally.
- **Root cause:** The `76-connectors.tf` lives in the **monorepo** `infrastructure/` directory (not the separate `infrastructure` repo). The SharePoint connector uses the exact same `module.core-infra.key_vault_id_app_common` reference in the same file. No issue.

### `envVars` pattern differs from SharePoint QA (PR #19872)

- SharePoint QA `app.yaml` doesn't use `connector.envVars` because it uses certificate-based auth (mounts `key.pem` from the secret).
- Confluence uses PAT auth injected via `envVars` + `secretKeyRef`. Both Helm charts support `connector.envVars` identically (backed by the shared `backend-service` library chart).

### Prometheus port 51348 (PR #19872)

- Confirmed correct. The confluence-connector Helm chart defaults `OTEL_EXPORTER_PROMETHEUS_PORT` to `51348` (SharePoint uses `51346`). Network policy matches.

### Dead code in Terraform module (PR #259)

- SharePoint module has the exact same unused `create` field and `content_type` lookup pattern. Not a problem.

### Renamed Terraform default secret from `api-token` to `pat` (PR #259)

- Changed default key in `variables.tf` from `confluence-connector-api-token` to `confluence-connector-pat`.
- Terraform now creates `manual-confluence-connector-pat` in Key Vault, matching the ExternalSecret `remoteRef.key`.

### `targetRevision` uses release tag instead of `ref=main` (PR #19876)

- The SharePoint connector in `76-connectors.tf` also pins to a release tag (`sharepoint-connector@2.0.0-beta.8`), not `ref=main`. The confluence connector follows the same convention. Starting from `alpha.1` is fine as long as the release exists before `terraform init`.
