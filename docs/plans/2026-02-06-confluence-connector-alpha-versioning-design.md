# Design: Confluence Connector Alpha Versioning

## Problem

The confluence-connector v2 is currently versioned at `0.1.0` with `prerelease-type: "beta"` in release-please config. Since this is a v2 rewrite of the existing v1 connector, the version should start at `2.0.0-alpha.1` to reflect this. The prerelease type should be `alpha` (not `beta`) since the connector is in early development.

Six files across two repos have version references that must be aligned.

## Solution

### Overview

Seed release-please with `2.0.0-alpha.0` as the current version and switch `prerelease-type` to `"alpha"`. When release-please runs on the next merge to `main`, it will create a release PR bumping to `2.0.0-alpha.1`. Update all version references in the connectors repo to `2.0.0-alpha.0` (the seed). Update the GitOps `app.yaml` targetRevision to `2.0.0-alpha.1` (the first actual release target).

### Changes

**Connectors repo** (all set to `2.0.0-alpha.0` — the seed):

- `release-please-config.json` — Change `prerelease-type` from `"beta"` to `"alpha"` for `services/confluence-connector`
- `.release-please-manifest.json` — Change `services/confluence-connector` from `"0.1.0"` to `"2.0.0-alpha.0"`
- `services/confluence-connector/package.json` — Change `version` from `"0.0.1"` to `"2.0.0-alpha.0"`
- `services/confluence-connector/deploy/helm-charts/confluence-connector/Chart.yaml` — Change `version` and `appVersion` from `0.1.0` to `2.0.0-alpha.0`
- `services/confluence-connector/deploy/helm-charts/confluence-connector/values.yaml` — Change image tag from `0.1.0` to `2.0.0-alpha.0` (preserving `# x-release-please-version` marker)

**Monorepo** (set to `2.0.0-alpha.1` — the first release target):

- `gitops-resources/argocd/clusters/unique/qa/application-specs/connectors/confluence-connector/app.yaml` — Change `targetRevision` from `confluence-connector@0.1.0` to `confluence-connector@2.0.0-alpha.1` and update the comment marker

### Error Handling

N/A — these are configuration file changes. If the version seed is wrong, release-please will simply create a release from the seeded version.

### Testing Strategy

No automated tests. Verify by checking that the next release-please PR on `main` proposes version `2.0.0-alpha.1`.

## Out of Scope

- Changing SharePoint connector's prerelease type (stays as `beta`)
- Creating the actual `2.0.0-alpha.1` release (happens automatically via release-please)
- Updating prod GitOps (only QA for now)

## Tasks

1. **Update connectors repo version references** — Change `prerelease-type` to `"alpha"` in `release-please-config.json`. Set version to `2.0.0-alpha.0` in `.release-please-manifest.json`, `package.json`, `Chart.yaml`, and `values.yaml`.

2. **Update GitOps targetRevision** — Change `app.yaml` targetRevision from `confluence-connector@0.1.0` to `confluence-connector@2.0.0-alpha.1`.
