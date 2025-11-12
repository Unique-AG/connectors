# SharePoint Connector Entra Application Module

> [!WARNING]
> This module is **EXPERIMENTAL**. Unique reserves the right to move, breakingly refactor, or deprecate the module at any stage without notice.

This module might also eventually evolve into [Unique-AG/terraform-modules](https://github.com/Unique-AG/terraform-modules).

## Overview

This Terraform module creates and configures an Azure Entra ID (formerly Azure AD) application registration and optional service principal for the Unique AI SharePoint Connector. It serves as living documentation for the minimal required permissions and configuration needed to run the connector.

**Key Features:**
- Automated application registration with minimal required permissions
- Optional service principal creation (useful for cross-tenant scenarios)
- Support for workload identity via federated identity credentials
- Support for certificate-based authentication
- Configurable sync modes: `content_only` or `content_and_permissions`
- Automatic admin consent for API permissions
- Tags and notes support with inheritance

## Resources Created

This module creates the following resources:

1. **Azure AD Application** - The application registration
2. **Service Principal** (optional) - Service principal for the application
3. **API Permissions** - Microsoft Graph and SharePoint permissions based on sync mode
4. **Admin Consent** - Automatic role assignments for granted permissions
5. **Federated Identity Credentials** (optional) - For workload identity authentication
6. **Application Certificates** (optional) - For certificate-based authentication

## Requirements

- Terraform >= 1.0
- Azure AD/Entra ID provider
- Appropriate permissions to create applications and service principals
- The workload must be deployed separately (this module only creates the identity)

## Variables

### Core Configuration

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `display_name` | `string` | `"Unique AI SharePoint Connector"` | Display name for the application registration |
| `sign_in_audience` | `string` | `"AzureADMultipleOrgs"` | Microsoft identity platform audience (`AzureADMyOrg`, `AzureADMultipleOrgs`, `AzureADandPersonalMicrosoftAccount`, `PersonalMicrosoftAccount`) |
| `tags` | `list(string)` | `[]` | Tags for the application (inherited by service principal) |
| `notes` | `string` | `""` | Notes for the application (inherited by service principal) |

### Service Principal Configuration

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `service_principal_configuration` | `object({ tags = optional(list(string)), notes = optional(string) })` | `{}` | Configuration for service principal. Set to `null` to skip creation. Tags and notes can override application-level values |

### Permissions

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `sync_mode_role_preset` | `string` | `"content_and_permissions"` | Sync mode preset determining required permissions. Valid values: `content_only`, `content_and_permissions` |

**Sync Mode Permissions:**
- `content_only`: Microsoft Graph `Files.Read.All`
- `content_and_permissions`: Microsoft Graph `Files.Read.All`, `GroupMember.Read.All`, `User.ReadBasic.All` + SharePoint `Sites.Selected`

### Authentication

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `federated_identity_credentials` | `map(object)` | `{}` | Map of federated identity credentials for workload identity (OIDC) |
| `certificates` | `map(object)` | `{}` | Map of X.509 certificates for certificate-based authentication |

## Usage Examples

### Basic Usage

```hcl
module "sharepoint_connector" {
  source = "./sharepoint-connector-entra-application"

  display_name = "My SharePoint Connector"
  tags         = ["production", "sharepoint"]
  notes        = "SharePoint connector for production environment"
}
```

### Content Only Mode

```hcl
module "sharepoint_connector" {
  source = "./sharepoint-connector-entra-application"

  display_name           = "SharePoint Connector - Content Only"
  sync_mode_role_preset  = "content_only"
}
```

### Cross-Tenant Scenario (No Service Principal)

When deploying to a different tenant that will create its own service principal:

```hcl
module "sharepoint_connector" {
  source = "./sharepoint-connector-entra-application"

  display_name                     = "SharePoint Connector"
  service_principal_configuration  = null  # Skip service principal creation
}
```

### Custom Service Principal Tags

Override tags and notes specifically for the service principal:

```hcl
module "sharepoint_connector" {
  source = "./sharepoint-connector-entra-application"

  display_name = "SharePoint Connector"
  tags         = ["application-level"]
  notes        = "Application notes"

  service_principal_configuration = {
    tags  = ["service-principal-specific", "production"]
    notes = "Different notes for service principal"
  }
}
```

### With Workload Identity (Kubernetes)

```hcl
module "sharepoint_connector" {
  source = "./sharepoint-connector-entra-application"

  display_name = "SharePoint Connector"

  federated_identity_credentials = {
    "aks-production-cluster" = {
      description = "AKS production cluster workload identity"
      issuer      = "https://switzerlandnorth.oic.prod-aks.azure.com/<tenant_id>/<cluster_id>/"
      subject     = "system:serviceaccount:sharepoint-connector:sharepoint-connector-sa"
      audiences   = ["api://AzureADTokenExchange"]
    }
  }
}
```

### With Certificate Authentication

```hcl
module "sharepoint_connector" {
  source = "./sharepoint-connector-entra-application"

  display_name = "SharePoint Connector"

  certificates = {
    "primary-cert" = {
      certificate = file("path/to/cert.pem")
      end_date    = "2025-12-31T23:59:59Z"
      start_date  = "2024-01-01T00:00:00Z"
    }
  }
}
```

## Outputs

| Output | Description |
|--------|-------------|
| `client_id` | Application (client) ID - use with Tenant ID for workload/managed identity |
| `object_id` | Service principal object ID (null if service principal not created) |

## Tags and Notes Inheritance

The module supports a three-level hierarchy for tags and notes:

1. **Application Level** - Set via `tags` and `notes` variables
2. **Service Principal Inheritance** - Service principal inherits application tags/notes by default
3. **Service Principal Override** - Explicitly set via `service_principal_configuration.tags` and `service_principal_configuration.notes`

```hcl
# Application has tags ["app"], service principal inherits ["app"]
tags = ["app"]

# Application has tags ["app"], service principal overrides to ["sp"]
tags = ["app"]
service_principal_configuration = {
  tags = ["sp"]
}
```

## Setup and Verification Steps

1. **Apply the module**
   ```bash
   terraform init
   terraform plan
   terraform apply
   ```

2. **Verify permissions in Azure Portal**
   - Navigate to Azure Portal → Entra ID → App registrations
   - Find your application by display name
   - Check "API permissions" - should show "Configured permissions"
   - Verify all permissions show status "Granted for [tenant]"
   
3. **If permissions are not granted**
   - Click "Grant admin consent for [tenant]"
   - If this fails, open an issue with error details

4. **Deploy the workload separately**
   - This module only creates the identity
   - Deploy the actual SharePoint Connector workload using Helm or other means

## Cross-Tenant Scenarios

In some multi-tenant deployments, the application registration exists in one tenant, but the service principal must be created in a different tenant. For these scenarios:

1. Set `service_principal_configuration = null` when creating the application
2. The other tenant will create the service principal separately
3. Only the `client_id` output is needed for this scenario

## Troubleshooting

### Permissions Not Granted

If permissions show as "Not granted" after terraform apply:
- Ensure you have sufficient privileges (Global Administrator or Privileged Role Administrator)
- Wait 15 seconds for Azure AD propagation (module includes automatic wait)
- Manually grant admin consent via Azure Portal
- Check Azure AD audit logs for errors

### Service Principal Already Exists

If you get an error about service principal existing:
- The module uses `use_existing = true` to handle this
- Verify the service principal is not managed by another Terraform state
- Consider importing the existing service principal into state

## Notes

- Clients are not required to use this module - any method of creating the application works
- This module serves as versioned documentation for required permissions
- The workload deployment is separate from this identity configuration
- Admin consent for permissions happens automatically via role assignments