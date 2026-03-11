<!-- confluence-page-id: 1952907339 -->
<!-- confluence-space-key: PUBDOC -->

## Content

The SharePoint Connector is delivered as part of the [Unique Connectors](https://github.com/Unique-AG/connectors) repository. Each release includes:

- Container images with the application code
- Helm charts for Kubernetes deployment
- Terraform modules for infrastructure provisioning
- Versioned documentation

## Container Image

Container images are available from container registries, including `uniquecr` and GitHub Container Registry:

```
ghcr.io/unique-ag/connectors/services/sharepoint-connector:<version>
```

**Note:** With `2.0.0` GA and higher, images are available via the `uniquecr` OCI registry.

### Image Contents

The images contain the application code plus all necessary dependencies. See [Software Bill Of Materials (SBOM)](../technical/security.md) for detailed contents.

## Helm Chart

### Installation

You can find installation instructions in the [connectors repo Helm chart](https://github.com/Unique-AG/connectors/tree/main/services/sharepoint-connector/deploy/helm-charts/sharepoint-connector#installation).

**Note:** With `2.0.0` GA and higher, charts are available via the `uniquecr` OCI registry.

### Basic Installation

```bash
# Add the Helm repository (if using OCI)
helm registry login ghcr.io

# Install the chart
helm install sharepoint-connector oci://ghcr.io/unique-ag/charts/sharepoint-connector \
  --version <version> \
  --namespace sharepoint-connector \
  --create-namespace \
  --values values.yaml
```

### Helm Values Example

The chart wraps the [`backend-service`](https://github.com/unique-ag/helm-charts) subchart (aliased as `connector`), so image, env, resources, and volumes are nested under the `connector` key. Connector-specific configuration lives under `connectorConfig` and `proxyConfig`.

```yaml
connector:
  image:
    repository: ghcr.io/unique-ag/connectors/services/sharepoint-connector
    tag: "2.2.0"
  env:
    LOG_LEVEL: info
  envVars: []
  resources:
    limits:
      memory: 2048Mi
    requests:
      cpu: 1
      memory: 1984Mi

# Tenant configuration (rendered into a ConfigMap and mounted as YAML)
connectorConfig:
  enabled: true
  sharepoint:
    tenantId: "your-tenant-id"
    baseUrl: "https://acme.sharepoint.com"
    auth:
      mode: certificate
      clientId: "your-client-id"
      privateKeyPath: /app/key.pem
      thumbprintSha1: "AB12CD34..."
    sitesSource: config_file
    # sites:
    #   - siteId: "site-id-1"
    #     syncColumnName: FinanceGPTKnowledge
    #     ingestionMode: recursive
    #     scopeId: scope_xxx
    #     syncMode: content_and_permissions
  unique:
    authMode: cluster_local
    ingestionServiceBaseUrl: "http://node-ingestion.finance-gpt:8091"
    scopeManagementServiceBaseUrl: "http://node-scope-management.finance-gpt:8094"
    serviceExtraHeaders:
      x-company-id: "company-id"
      x-user-id: "service-user-id"
  processing:
    scanIntervalCron: "*/15 * * * *"
    concurrency: 1
    allowedMimeTypes:
      - application/pdf
      - application/vnd.openxmlformats-officedocument.wordprocessingml.document
      - application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
      - application/vnd.openxmlformats-officedocument.presentationml.presentation

# Proxy configuration (optional)
proxyConfig:
  enabled: true
  authMode: none
```

## Terraform Modules

Each release contains matching Terraform modules that offer the needed functionality to run the connector:

- **Entra Application module** — registers the Azure AD app with the required Graph/SharePoint permissions
- **Secrets module** — provisions Key Vault secrets and optionally generates a TLS certificate

### Entra Application Module

```hcl
module "sharepoint_connector_app" {
  source = "github.com/Unique-AG/connectors//services/sharepoint-connector/deploy/terraform/azure/sharepoint-connector-entra-application"

  display_name         = "Unique AI SharePoint Connector"
  sync_mode_role_preset = "content_and_permissions"
}
```

Outputs: `client_id`, `object_id`.

### Secrets Module

```hcl
module "sharepoint_connector_secrets" {
  source = "github.com/Unique-AG/connectors//services/sharepoint-connector/deploy/terraform/azure/sharepoint-connector-secrets"

  key_vault_id = var.key_vault_id

  # Optional: auto-generate a TLS certificate (pass null to disable)
  # tls_certificate = {
  #   subject = "sharepoint-connector"
  # }
}
```

Outputs: `certificate` (with `pem`, `validity_end_time`, `thumbprint_sha1` when TLS generation is enabled).

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

## Version Support and Maintenance Policy

The SharePoint Connector follows Unique's standard release lifecycle and maintenance expectations. The canonical source is [Upgrade and Release Process](https://unique-ch.atlassian.net/wiki/spaces/PUBDOC/pages/1385366775/Upgrade+and+Release+Process).

In short, plan operations around the latest release line and the previous supported line. Always verify current support boundaries and rollout expectations in the linked policy before upgrading production environments.

## Compatibility

The SharePoint Connector is compatible with:

- Microsoft SharePoint 365 / Online

Further compatibilities (Data Center, On Premise, or other variants) are on the roadmap but not committed. Contact Unique for more information.

### Unique Platform Compatibility

| Connector Version | Minimum Unique Version |
| ----------------- | ---------------------- |
| 2.x               | TBD                    |

## Upgrading

### Pre-Upgrade Checklist

- [ ] Review release notes for breaking changes
- [ ] Backup current Helm values
- [ ] Test upgrade in non-production environment
- [ ] Plan maintenance window if needed

### Upgrade Process

```bash
# Update Helm repository
helm repo update

# Review changes
helm diff upgrade sharepoint-connector oci://ghcr.io/unique-ag/charts/sharepoint-connector \
  --version <new-version> \
  --namespace sharepoint-connector \
  --values values.yaml

# Perform upgrade
helm upgrade sharepoint-connector oci://ghcr.io/unique-ag/charts/sharepoint-connector \
  --version <new-version> \
  --namespace sharepoint-connector \
  --values values.yaml
```

### Rollback

```bash
# List release history
helm history sharepoint-connector -n sharepoint-connector

# Rollback to previous version
helm rollback sharepoint-connector <revision> -n sharepoint-connector
```

## Troubleshooting

### Pod Not Starting

1. Check pod events:

   ```bash
   kubectl describe pod -l app=sharepoint-connector -n sharepoint-connector
   ```

2. Check logs:
   ```bash
   kubectl logs -l app=sharepoint-connector -n sharepoint-connector
   ```

### Authentication Errors

- Verify certificate is valid and not expired
- Confirm client ID matches app registration
- Check tenant ID is correct
- Verify site-specific permissions are granted

### Network Connectivity

- Verify egress to `graph.microsoft.com` is allowed
- Check DNS resolution works
- Confirm firewall rules permit HTTPS traffic

See [FAQ](../faq.md) for more troubleshooting guidance.
