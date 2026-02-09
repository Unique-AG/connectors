# PR Proposal

## Title
fix(confluence-connector): replace sharepoint config with confluence tenant config YAML

## Description
- Replace copied SharePoint tenant config YAML with correct Confluence-format config matching the existing Zod schema
- Add `example-cloud-tenant-config.yaml` demonstrating Cloud + API token + External Zitadel auth
- Add `example-onprem-tenant-config.yaml` demonstrating On-prem + PAT + Cluster-local auth
