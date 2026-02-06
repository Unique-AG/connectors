# Design: Confluence Connector Helm CI Test Values

## Problem

The confluence-connector Helm chart has multiple template branches in `tenant-config.yaml` (auth modes, instance types, optional fields) but `ct lint` in CI only tests the default `values.yaml`. Non-default paths — external Zitadel auth, on-prem basic auth, optional fields like labels/spaces — are never rendered in CI, meaning template bugs could slip through unnoticed.

## Solution

### Overview

Add three `ci/*-values.yaml` files to the confluence-connector Helm chart. The `ct lint` tool automatically discovers files in the `ci/` directory and renders the chart once per file, catching template rendering errors across all configuration paths.

### Files

1. **`ci/onprem-basic-auth-values.yaml`** — Exercises: `instanceType: onprem`, `auth.mode: basic`, `auth.username` conditional. Uses default `cluster_local` unique auth.

2. **`ci/external-zitadel-values.yaml`** — Exercises: `authMode: external` with Zitadel fields (`clientId`, `oauthTokenUrl`, `projectId`). Uses `auth.mode: pat` for Confluence auth to cover that path as well.

3. **`ci/all-optional-fields-values.yaml`** — Exercises all optional/conditional fields: `maxPagesToScan`, `ingestionConfig`, `labels`, `spaces`. Uses default auth modes but populates every optional field.

### Coverage Matrix

| Template branch              | defaults | onprem-basic | external-zitadel | all-optional |
|------------------------------|----------|--------------|-------------------|--------------|
| cloud + api_token            | x        |              |                   |              |
| onprem + basic + username    |          | x            |                   |              |
| onprem + pat                 |          |              | x                 |              |
| cluster_local (extraHeaders) | x        | x            |                   | x            |
| external (Zitadel fields)    |          |              | x                 |              |
| maxPagesToScan               |          |              |                   | x            |
| ingestionConfig              |          |              |                   | x            |
| labels / spaces              |          |              |                   | x            |

## Out of Scope

- Helm unit tests (`tests/` directory) — can be added later
- Alert-specific CI values — alerts are disabled by default and template is straightforward
- `ct install` (kind cluster testing) — currently commented out in CI for all connectors

## Tasks

1. **Create `ci/onprem-basic-auth-values.yaml`** — Minimal values file overriding `instanceType`, `auth.mode`, and `auth.username` to test the on-prem basic auth template path.

2. **Create `ci/external-zitadel-values.yaml`** — Values file setting `authMode: external` with Zitadel config and `auth.mode: pat` to test the external auth and PAT template paths.

3. **Create `ci/all-optional-fields-values.yaml`** — Values file populating all optional fields (`maxPagesToScan`, `ingestionConfig`, `labels`, `spaces`) to test conditional template rendering.

4. **Verify with `ct lint`** — Run `ct lint` locally to confirm all three values files render without errors.
