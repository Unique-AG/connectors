# PR Proposal

## Title
ci(confluence-connector): add Helm chart CI test values for non-default config paths

## Description
- Add 3 `ci/*-values.yaml` files to the confluence-connector Helm chart for `ct lint` to exercise all template branches
- Cover on-prem basic auth, external Zitadel auth, and all optional fields (labels, spaces, maxPagesToScan, ingestionConfig)
- Ensures template rendering bugs in non-default paths are caught in CI
