# PR Proposal

## Title
feat(confluence-connector): add Terraform module for Key Vault secret provisioning

## Description
- Create `confluence-connector-secrets` Terraform module following the SharePoint connector pattern
- Module provisions placeholder secret `manual-confluence-connector-api-token` in `kv-app-common`
- Add module reference in QA `76-connectors.tf`
- Fix ExternalSecret `remoteRef.key` to use `manual-` prefix convention
