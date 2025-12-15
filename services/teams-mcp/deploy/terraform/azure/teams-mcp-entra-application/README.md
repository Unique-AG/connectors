# Teams MCP Entra Application Terraform Module

**Status: ALPHA / EXPERIMENTAL**

This Terraform module creates and configures an Azure Entra (formerly Azure AD) application for the Teams MCP service with the required Microsoft Graph API permissions.

## Purpose

This module provisions an Azure Entra application that can:
- Access Microsoft Teams meeting data via Microsoft Graph API
- Read user information, online meetings, recordings, and transcripts
- Authenticate users via OAuth 2.0 flow
- Support multiple authentication methods (client secret, workload identity)

## Features

- **Automatic Microsoft Graph API Permissions**: Configures all required application roles for Teams MCP
- **Admin Consent**: Optionally grants admin consent automatically via Terraform
- **OAuth Redirect URIs**: Configures web redirect URIs for OAuth flow
- **Multiple Auth Methods**: Supports client secrets and federated credentials (workload identity)
- **Workload Identity**: Full support for Azure AKS workload identity (OIDC)
- **Multi-tenant Support**: Configurable sign-in audience for single or multi-tenant scenarios

## Required Permissions

The module grants the following Microsoft Graph **application permissions** (not delegated):

| Permission | ID | Description |
|------------|-----|-------------|
| `User.Read.All` | df021288-bdef-4463-88db-98f22de89214 | Read all users' full profiles |
| `OnlineMeetings.Read.All` | c1684f21-1984-47fa-9d61-2dc8c296bb70 | Read all online meetings |
| `OnlineMeetingRecording.Read.All` | 190c2bb6-1fdd-4fec-9aa2-7d571b5e1fe3 | Read all online meeting recordings |
| `OnlineMeetingTranscript.Read.All` | 30b87d18-ebb1-45db-97f8-82ccb1f0190c | Read all online meeting transcripts |

> **Note**: These are **application permissions** which require admin consent and allow the app to act without a signed-in user.

## Usage

### Basic Usage (Client Secret Auth)

```hcl
module "teams_mcp_app" {
  source = "./azure/teams-mcp-entra-application"

  display_name = "Unique AI Teams MCP"
  redirect_uris = [
    "https://teams-mcp.example.com/auth/microsoft/callback"
  ]

  service_principal_configuration = {}
  create_client_secret           = true
}

output "client_id" {
  value = module.teams_mcp_app.client_id
}

output "client_secret" {
  value     = module.teams_mcp_app.client_secret_value
  sensitive = true
}
```

### Advanced Usage (Workload Identity)

```hcl
module "teams_mcp_app" {
  source = "./azure/teams-mcp-entra-application"

  display_name     = "Unique AI Teams MCP - Production"
  sign_in_audience = "AzureADMyOrg" # Single tenant
  notes            = "Teams MCP production application"

  redirect_uris = [
    "https://teams-mcp.example.com/auth/microsoft/callback",
    "https://teams-mcp-staging.example.com/auth/microsoft/callback"
  ]

  # Enable service principal and grant admin consent
  service_principal_configuration = {
    notes = "Service principal for Teams MCP"
  }

  # Configure federated identity for AKS
  federated_identity_credentials = {
    "production-aks" = {
      description = "Production AKS cluster workload identity"
      issuer      = "https://switzerlandnorth.oic.prod-aks.azure.com/<tenant_id>/<cluster_guid>/"
      subject     = "system:serviceaccount:teams-mcp:teams-mcp-sa"
    }
    "staging-aks" = {
      description = "Staging AKS cluster workload identity"
      issuer      = "https://switzerlandnorth.oic.prod-aks.azure.com/<tenant_id>/<cluster_guid>/"
      subject     = "system:serviceaccount:teams-mcp-staging:teams-mcp-sa"
    }
  }

  # Don't create client secret when using workload identity
  create_client_secret = false
}
```

## Variables

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|----------|
| `display_name` | Display name for the Azure AD application | `string` | `"Unique AI Teams MCP"` | no |
| `notes` | Notes for the Azure AD application | `string` | `null` | no |
| `sign_in_audience` | Microsoft identity platform audiences supported | `string` | `"AzureADMultipleOrgs"` | no |
| `redirect_uris` | List of OAuth redirect URIs | `list(string)` | `[]` | no |
| `service_principal_configuration` | Service principal configuration (set to `null` to skip creation) | `object` | `{}` | no |
| `federated_identity_credentials` | Map of federated identity credentials (OIDC) | `map(object)` | `{}` | no |
| `create_client_secret` | Whether to create a client secret | `bool` | `false` | no |
| `client_secret_end_date` | End date for the client secret | `string` | `null` | no |

## Outputs

| Name | Description | Sensitive |
|------|-------------|-----------|
| `client_id` | The application (client) ID | no |
| `application_id` | The application object ID | no |
| `object_id` | Service principal object ID (null if not created) | no |
| `client_secret_id` | Client secret key ID (null if not created) | yes |
| `client_secret_value` | Client secret value (null if not created) | yes |

## Authentication Methods

### 1. Client Secret
- Set `create_client_secret = true`
- Use output `client_secret_value` in your application
- Requires periodic rotation
- Suitable for development and production environments

### 2. Federated Credentials / Workload Identity (Recommended for Kubernetes)
- Configure via `federated_identity_credentials`
- No secrets to manage or rotate
- Requires AKS with workload identity enabled
- Most secure option for production deployments

## Post-Deployment

After applying this module:

1. **Verify Admin Consent**: Check in Azure Portal that all permissions show "Granted for \<tenant\>"
2. **Configure Application**: Use the `client_id` output in your Teams MCP configuration
3. **Store Secrets Securely**: If using client secret, store the output in Azure Key Vault
4. **Test Authentication**: Verify OAuth flow works with configured redirect URIs

## Limitations

- Module creates application permissions only (not delegated permissions)
- Service principal creation is optional but required for admin consent
- Automatic admin consent only works when `service_principal_configuration` is set
- Cross-tenant scenarios require manual consent (set `service_principal_configuration = null`)

## Requirements

| Name | Version |
|------|---------|
| terraform | ~> 1.10 |
| azuread | ~> 3 |
| time | ~> 0.13 |

## Notes

- Admin consent is automatically granted when `service_principal_configuration` is set
- The module waits 15 seconds after service principal creation for Azure AD propagation
- All Microsoft Graph permissions are **application-level** (app-only access)
- OAuth redirect URIs must match exactly what your application uses

## Related Documentation

- [Microsoft Graph Permissions Reference](https://learn.microsoft.com/en-us/graph/permissions-reference)
- [Azure Workload Identity](https://azure.github.io/azure-workload-identity/)
- [Entra Application Registration](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app)
