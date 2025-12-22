# Teams MCP Entra Application Terraform Module

**Status: ALPHA / EXPERIMENTAL**

This Terraform module creates and configures an Azure Entra (formerly Azure AD) application for the Teams MCP service with the required Microsoft Graph API permissions.

## Purpose

This module provisions an Azure Entra application that can:
- Access Microsoft Teams meeting data via Microsoft Graph API
- Read user information, online meetings, recordings, and transcripts
- Authenticate users via OAuth 2.0 delegated flow

## Features

- **Automatic Microsoft Graph API Permissions**: Configures all required delegated permissions for Teams MCP
- **Admin Consent**: Optionally grants admin consent automatically via Terraform
- **OAuth Redirect URIs**: Configures web redirect URIs for OAuth flow
- **Client Secret**: Creates a client secret for OAuth authentication
- **Multi-tenant Support**: Configurable sign-in audience for single or multi-tenant scenarios

## Required Permissions

The module grants the following Microsoft Graph **delegated permissions**:

| Permission | ID | Description |
|------------|-----|-------------|
| `User.Read` | e1fe6dd8-ba31-4d61-89e7-88639da4683d | Read signed-in user's profile |
| `OnlineMeetings.Read` | 9be106e1-f4e3-4df5-bdff-e4bc531cbe43 | Read user's online meetings |
| `OnlineMeetingRecording.Read.All` | 190c2bb6-1fdd-4fec-9aa2-7d571b5e1fe3 | Read all online meeting recordings |
| `OnlineMeetingTranscript.Read.All` | 30b87d18-ebb1-45db-97f8-82ccb1f0190c | Read all online meeting transcripts |

> **Note**: These are **delegated permissions** which act on behalf of the signed-in user. Admin consent may still be required for some permissions.

## Usage

### Basic Usage

```hcl
module "teams_mcp_app" {
  source = "./azure/teams-mcp-entra-application"

  display_name = "Unique AI Teams MCP"
  redirect_uris = [
    "https://teams-mcp.example.com/auth/microsoft/callback"
  ]

  service_principal_configuration = {}
  create_client_secret            = true
}

output "client_id" {
  value = module.teams_mcp_app.client_id
}

output "client_secret" {
  value     = module.teams_mcp_app.client_secret_value
  sensitive = true
}
```

### Production Usage

```hcl
module "teams_mcp_app" {
  source = "./azure/teams-mcp-entra-application"

  display_name     = "Unique AI Teams MCP - Production"
  sign_in_audience = "AzureADMyOrg" # Single tenant
  notes            = "Teams MCP production application"

  redirect_uris = [
    "https://teams-mcp.example.com/auth/microsoft/callback"
  ]

  # Enable service principal and grant admin consent
  service_principal_configuration = {
    notes = "Service principal for Teams MCP"
  }

  create_client_secret   = true
  client_secret_end_date = "2026-12-31T23:59:59Z"
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
| `create_client_secret` | Whether to create a client secret | `bool` | `true` | no |
| `client_secret_end_date` | End date for the client secret | `string` | `null` | no |

## Outputs

| Name | Description | Sensitive |
|------|-------------|-----------|
| `client_id` | The application (client) ID | no |
| `application_id` | The application object ID | no |
| `object_id` | Service principal object ID (null if not created) | no |
| `client_secret_id` | Client secret key ID (null if not created) | yes |
| `client_secret_value` | Client secret value (null if not created) | yes |

## Post-Deployment

After applying this module:

1. **Verify Admin Consent**: Check in Azure Portal that all permissions show "Granted for \<tenant\>"
2. **Configure Application**: Use the `client_id` output in your Teams MCP configuration
3. **Store Secrets Securely**: If using client secret, store the output in Azure Key Vault
4. **Test Authentication**: Verify OAuth flow works with configured redirect URIs

## Limitations

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
- All Microsoft Graph permissions are **delegated** (act on behalf of signed-in user)
- OAuth redirect URIs must match exactly what your application uses
- Client secrets should be rotated periodically (set `client_secret_end_date` appropriately)

## Related Documentation

- [Microsoft Graph Permissions Reference](https://learn.microsoft.com/en-us/graph/permissions-reference)
- [Entra Application Registration](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app)
