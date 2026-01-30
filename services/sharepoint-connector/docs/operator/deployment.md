<!-- confluence-space-key: PUBDOC -->

## Content

The SharePoint Connector is delivered as part of the [Unique Connectors](https://github.com/Unique-AG/connectors) repository. Each release includes:

- Container images with the application code
- Helm charts for Kubernetes deployment
- Terraform modules for infrastructure provisioning
- Versioned documentation

## Container Image

Container images are available from GitHub Container Registry:

```
ghcr.io/unique-ag/sharepoint-connector:<version>
```

**Note:** After version `2.0.0` becomes generally available, images will also be provided via the `uniquecr` OCI registry.

### Image Contents

The images contain the application code plus all necessary dependencies. See [Software Bill Of Materials (SBOM)](../technical/security.md#software-bill-of-materials-sbom) for detailed contents.

## Helm Chart

### Installation

You can find installation instructions in the [connectors repo Helm chart](https://github.com/Unique-AG/connectors/tree/main/services/sharepoint-connector/deploy/helm-charts/sharepoint-connector#installation).

**Note:** After version `2.0.0` becomes generally available, charts will also be provided via the `uniquecr` OCI registry.

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

```yaml
image:
  repository: ghcr.io/unique-ag/sharepoint-connector
  tag: "2.0.0"
  pullPolicy: IfNotPresent

# Environment variables from secrets
envVars:
  - secretRef:
      name: sharepoint-connector-secrets

# Static environment variables
env:
  LOG_LEVEL: info
  SYNC_INTERVAL_MINUTES: "15"

# Resource limits
resources:
  limits:
    memory: 2048Mi
  requests:
    cpu: 1
    memory: 2048Mi

# SharePoint configuration
sharepointConfig:
  tenantId: "your-tenant-id"
  clientId: "your-client-id"
  siteIds:
    - "site-id-1"
    - "site-id-2"
  syncColumnName: "UniqueAI"

# Unique configuration
uniqueConfig:
  apiBaseUrl: "http://api-gateway.unique:8080"
  ingestionBaseUrl: "http://node-ingestion.unique:8091"
  rootScopeId: "scope_xxx"
  companyId: "company-id"
  userId: "service-user-id"
```

## Terraform Modules

Each release contains matching Terraform modules that offer the needed functionality to run the connector:

- Azure AD App Registration module
- Kubernetes deployment module
- Certificate generation module

### Azure AD Module

```hcl
module "sharepoint_connector_app" {
  source = "github.com/Unique-AG/connectors//services/sharepoint-connector/deploy/terraform/azure-ad"

  display_name = "Unique SharePoint Connector"
  tenant_id    = var.tenant_id
  
  # Sites to grant access to
  site_ids = var.sharepoint_site_ids
}
```

### Kubernetes Module

```hcl
module "sharepoint_connector" {
  source = "github.com/Unique-AG/connectors//services/sharepoint-connector/deploy/terraform/kubernetes"

  namespace    = "sharepoint-connector"
  image_tag    = "2.0.0"
  
  # Azure AD configuration
  tenant_id    = var.tenant_id
  client_id    = module.sharepoint_connector_app.client_id
  
  # Certificate from Azure AD module
  certificate_pem = module.sharepoint_connector_app.certificate_pem
  private_key_pem = module.sharepoint_connector_app.private_key_pem
}
```

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

## Compatibility

The SharePoint Connector is compatible with:

- Microsoft SharePoint 365 / Online

Further compatibilities (Data Center, On Premise, or other variants) are on the roadmap but not committed. Contact Unique for more information.

### Unique Platform Compatibility

| Connector Version | Minimum Unique Version |
|-------------------|------------------------|
| 2.0.x | TBD |

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
