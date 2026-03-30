<!-- confluence-page-id: -->
<!-- confluence-space-key: PUBDOC -->

## Content

The Confluence Connector is delivered as part of the [Unique Connectors](https://github.com/Unique-AG/connectors) repository. Each release includes:

- Container images with the application code
- Helm charts for Kubernetes deployment
- Terraform module for Azure Key Vault secret placeholders
- Versioned documentation

## Container Image

Container images are available from GitHub Container Registry:

```
ghcr.io/unique-ag/connectors/services/confluence-connector:<version>
```

The image contains the application code plus all necessary runtime dependencies.

## Helm Chart

The Helm chart wraps the [`backend-service`](https://artifacthub.io/packages/helm/unique/backend-service) subchart (aliased as `connector`), so image, env, resources, and volumes are nested under the `connector` key. Tenant-specific configuration lives under `connectorConfig`.

### Installation

Chart and app versions are maintained in:

- [`Chart.yaml`](https://github.com/Unique-AG/connectors/blob/main/services/confluence-connector/deploy/helm-charts/confluence-connector/Chart.yaml) for the current chart and app versions
- [`values.yaml`](https://github.com/Unique-AG/connectors/blob/main/services/confluence-connector/deploy/helm-charts/confluence-connector/values.yaml) for the current default values

**Helm (via `helm-git` plugin):**

> **Prerequisite:** The [`helm-git`](https://github.com/aslafy-z/helm-git) plugin is required for `git+https://` chart references. Install it with:
>
> ```bash
> helm plugin install https://github.com/aslafy-z/helm-git
> ```

```bash
helm repo add cfc git+https://github.com/Unique-AG/connectors@services/confluence-connector/deploy/helm-charts?ref=<release-tag>&depupdate=1
helm install confluence-connector cfc/confluence-connector \
  --version <version> \
  --namespace confluence-connector \
  --create-namespace \
  --values values.yaml
```

### Helm Values Example

For the current Helm defaults, use [`values.yaml`](https://github.com/Unique-AG/connectors/blob/main/services/confluence-connector/deploy/helm-charts/confluence-connector/values.yaml). For chart metadata, use [`Chart.yaml`](https://github.com/Unique-AG/connectors/blob/main/services/confluence-connector/deploy/helm-charts/confluence-connector/Chart.yaml). For detailed configuration reference, see [Configuration](./configuration.md).

```yaml
connector:
  image:
    repository: ghcr.io/unique-ag/connectors/services/confluence-connector
    tag: "<version>"
  env:
    LOG_LEVEL: info
  envVars: []
  resources:
    limits:
      memory: 1Gi
    requests:
      cpu: 1
      memory: 512Mi

# Tenant configuration (rendered into a ConfigMap and mounted as YAML)
connectorConfig:
  enabled: true
  tenants:
    - name: default
      confluence:
        instanceType: cloud
        cloudId: "your-cloud-id"
        baseUrl: https://your-domain.atlassian.net
        auth:
          mode: oauth_2lo
          clientId: "your-oauth-client-id"
          clientSecret: "os.environ/CONFLUENCE_CLIENT_SECRET"
        apiRateLimitPerMinute: 1200
        ingestSingleLabel: ai-ingest
        ingestAllLabel: ai-ingest-all
      unique:
        authMode: cluster_local
        ingestionServiceBaseUrl: "http://node-ingestion.<namespace>:8091"
        scopeManagementServiceBaseUrl: "http://node-scope-management.<namespace>:8094"
        apiRateLimitPerMinute: 100
        serviceExtraHeaders:
          x-company-id: "your-company-id"
          x-user-id: "your-service-user-id"
      processing:
        concurrency: 1
        scanIntervalCron: "*/15 * * * *"
      ingestion:
        ingestionMode: flat
        scopeId: "your-scope-id"
        storeInternally: enabled
```

**Note:** The Helm chart uses `unique.authMode`, which the Helm template maps to `serviceAuthMode` in the generated tenant config YAML. See [Authentication -- Helm Chart Field Mapping](./authentication.md#helm-chart-field-mapping).

## Terraform Modules

Each release contains a Terraform module for secret provisioning:

### Secrets Module

The secrets module provisions Azure Key Vault secret placeholders for the connector's credentials (OAuth client secret, or PAT for Data Center below 10.1 only). The secret values are set to `<TO BE SET MANUALLY>` on creation and must be populated by the operator. The `lifecycle.ignore_changes` block ensures Terraform does not overwrite manually set values on subsequent applies.

```hcl
module "confluence_connector_secrets" {
  source = "github.com/Unique-AG/connectors//services/confluence-connector/deploy/terraform/azure/confluence-connector-secrets"

  key_vault_id = var.key_vault_id

  # Optional: override default secret placeholders
  # secrets_placeholders = {
  #   confluence-connector-pat-dc              = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
  #   confluence-connector-client-secret-cloud = { create = true, expiration_date = "2099-12-31T23:59:59Z" }
  # }
}
```

| Variable | Type | Required | Description |
|---|---|---|---|
| `key_vault_id` | `string` | Yes | The ID of the Azure Key Vault where secrets will be created |
| `secrets_placeholders` | `map(object)` | No | Map of secret names to create. Each entry supports `create` (bool) and `expiration_date` (string). Defaults include `confluence-connector-pat-dc` and `confluence-connector-client-secret-cloud` |

**Output:** `secret_names` -- list of created Key Vault secret names (each prefixed with `manual-`).

**Requirements:** Terraform `~> 1.10`, `hashicorp/azurerm` provider `~> 4`.

## Releases

All releases (including pre-releases) are available at: [https://github.com/Unique-AG/connectors/releases](https://github.com/Unique-AG/connectors/releases)

### Version Numbering

The connector follows [Semantic Versioning](https://semver.org/):

- **Major**: Breaking changes requiring migration
- **Minor**: New features, backward compatible
- **Patch**: Bug fixes, backward compatible

### Pre-Release Versions

Pre-release versions are marked with suffixes like `-alpha` or `-beta`:

```
2.0.0-alpha.1
2.0.0-beta.1
2.0.0  (GA)
```

### Release Tags

Release tags in the repository follow the format:

```
confluence-connector@<version>
```

## Version Support and Maintenance Policy

The Confluence Connector follows Unique's standard release lifecycle and maintenance expectations. The canonical source is [Upgrade and Release Process](https://unique-ch.atlassian.net/wiki/spaces/PUBDOC/pages/1385366775/Upgrade+and+Release+Process).

In short, plan operations around the latest release line and the previous supported line. Always verify current support boundaries and rollout expectations in the linked policy before upgrading production environments.

## Compatibility

The Confluence Connector is compatible with:

- Atlassian Confluence Cloud
- Atlassian Confluence Data Center

See [Configuration -- Confluence Connection Settings](./configuration.md#confluence-connection-settings) for instance type details and [Authentication](./authentication.md) for supported authentication methods per instance type.

### Unique Platform Compatibility

| Connector Version | Minimum Unique Version |
|---|---|
| 2.x | TBD |

## Upgrading

### Pre-Upgrade Checklist

- [ ] Review release notes for breaking changes
- [ ] Backup current Helm values
- [ ] Test upgrade in non-production environment
- [ ] Plan maintenance window if needed

### Upgrade Process

```bash
# Review changes before upgrading
helm diff upgrade confluence-connector cfc/confluence-connector \
  --version <new-version> \
  --namespace confluence-connector \
  --values values.yaml

# Perform upgrade
helm upgrade confluence-connector cfc/confluence-connector \
  --version <new-version> \
  --namespace confluence-connector \
  --values values.yaml
```

### Rollback

```bash
# List release history
helm history confluence-connector -n confluence-connector

# Rollback to previous version
helm rollback confluence-connector <revision> -n confluence-connector
```

## Troubleshooting

### Pod Not Starting

1. Check pod events:

   ```bash
   kubectl describe pod -l app=confluence-connector -n confluence-connector
   ```

2. Check logs:

   ```bash
   kubectl logs -l app=confluence-connector -n confluence-connector
   ```

### Configuration Validation Errors

The connector validates all tenant configuration at startup. Common validation failures include:

- Missing required fields (`ingestSingleLabel`, `ingestAllLabel`, `apiRateLimitPerMinute`, `scopeId`)
- Empty or unset environment variables referenced via `os.environ/`
- Duplicate tenant names across configuration files
- No active tenants found

Check the pod logs for specific validation error messages. See [Configuration](./configuration.md) for required fields and defaults.

### Authentication Errors

- Verify OAuth client credentials (or PAT for Data Center below 10.1) are valid
- Confirm the `os.environ/` references resolve to non-empty environment variables
- Check Kubernetes Secrets exist and contain the expected keys
- For `cluster_local` mode, ensure `x-company-id` and `x-user-id` headers are set

See [Authentication -- Troubleshooting](./authentication.md#troubleshooting) for detailed diagnosis steps.

### Network Connectivity

- Verify egress to Confluence endpoints is allowed (Cloud: `api.atlassian.com`; Data Center: your instance host)
- Check DNS resolution works
- Confirm firewall rules permit HTTPS traffic on port 443
- For `external` mode, verify egress to the Zitadel IdP

See the network requirements table in the [Operator Guide](./README.md#network-requirements) for the full list of required endpoints.

See [FAQ](../faq.md) for more troubleshooting guidance.
