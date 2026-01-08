# Authentication Setup

## Overview

The Teams MCP Connector requires a Microsoft Entra ID (formerly Azure AD) app registration with delegated permissions to access Microsoft Graph API on behalf of users.

For technical details about the OAuth flow and why client credentials are required, see [Token and Authentication Flows](../technical/token-auth-flows.md).

## App Registration

### Option 1: Terraform (Recommended)

Use the provided Terraform module:

```hcl
module "teams_mcp_app" {
  source = "./deploy/terraform/azure/teams-mcp-entra-application"

  display_name     = "Teams MCP Connector"
  sign_in_audience = "AzureADMyOrg"  # Single tenant
  notes            = "MCP server for Teams transcript capture"

  redirect_uris = [
    "https://teams.mcp.example.com/auth/callback"
  ]

  confidential_clients = {
    production = {
      client_secret = {
        key_vault_id     = azurerm_key_vault.main.id
        end_date         = "2026-01-01T00:00:00Z"
        rotation_counter = 1
      }
    }
  }
}
```

### Option 2: Azure Portal (Manual)

1. **Navigate to App Registrations**
   - Go to [Azure Portal](https://portal.azure.com)
   - Search for "App registrations"
   - Click "New registration"

2. **Configure Basic Settings**
   - **Name**: Teams MCP Connector
   - **Supported account types**: Accounts in this organizational directory only
   - **Redirect URI**: Web - `https://teams.mcp.example.com/auth/callback`

3. **Add API Permissions**
   - Go to "API permissions"
   - Click "Add a permission" → "Microsoft Graph" → "Delegated permissions"
   - Add the following permissions:

   | Permission | Type | Admin Consent |
   |------------|------|---------------|
   | `User.Read` | Delegated | No |
   | `OnlineMeetings.Read` | Delegated | No |
   | `OnlineMeetingTranscript.Read.All` | Delegated | **Yes** |
   | `OnlineMeetingRecording.Read.All` | Delegated | **Yes** |
   | `offline_access` | Delegated | No |

4. **Grant Admin Consent**
   - Click "Grant admin consent for [Tenant]"
   - Confirm the action

5. **Create Client Secret**
   - Go to "Certificates & secrets"
   - Click "New client secret"
   - Set description and expiration
   - **Copy the secret value immediately** (shown only once)

6. **Note Application Details**
   - Go to "Overview"
   - Copy the **Application (client) ID**
   - Copy the **Directory (tenant) ID**

## Required Permissions

All permissions are **delegated**, meaning they act on behalf of the signed-in user:

| Permission | Purpose | Admin Consent |
|------------|---------|---------------|
| `User.Read` | Read user profile for identification | No |
| `OnlineMeetings.Read` | Read meeting details and participants | No |
| `OnlineMeetingTranscript.Read.All` | Read meeting transcripts | **Yes** |
| `OnlineMeetingRecording.Read.All` | Read meeting recordings (optional) | **Yes** |
| `offline_access` | Obtain refresh tokens for long-lived access | No |

For detailed permission justifications, see [Permissions Documentation](../technical/permissions.md).

## Redirect URI Configuration

The redirect URI must match exactly what's configured in the app registration:

```
https://<your-domain>/auth/callback
```

Examples:
- Production: `https://teams.mcp.example.com/auth/callback`
- Development: `http://localhost:3000/auth/callback`

**Multiple redirect URIs** can be configured for different environments.

## Tenant Configuration

### Single Tenant (Recommended)

For enterprise deployments within one organization, use single-tenant configuration:

- **Sign-in audience**: "Accounts in this organizational directory only"
- **Terraform**: `sign_in_audience = "AzureADMyOrg"`

### Multi-Tenant App Registration

You can configure the Entra ID app registration to serve **multiple Microsoft tenants** with a single MCP server deployment:

- **Sign-in audience**: "Accounts in any organizational directory"
- **Terraform**: `sign_in_audience = "AzureADMultipleOrgs"`

#### Multi-Tenant Configuration

For SaaS deployments serving multiple organizations:

1. **Single App Registration**: Created in your tenant with one `CLIENT_ID` and `CLIENT_SECRET`
2. **Enterprise Application Creation**: When each organization's admin grants consent, Microsoft creates an "Enterprise Application" in their tenant that references your app registration
3. **User Authentication Flow**: Users authenticate via the Enterprise Application in their tenant, which redirects to your app registration for token issuance
4. **Shared Infrastructure**: One MCP deployment serves all tenants through their respective Enterprise Applications

#### Considerations for Multi-Tenant

**How Admin Consent Works:**

1. **Initial Setup**: You create a multi-tenant app registration in your Entra ID tenant
2. **Consent Request**: Share the admin consent URL with each organization's admin
3. **Enterprise App Creation**: When admin grants consent, Microsoft automatically creates an Enterprise Application in their tenant
4. **User Access**: Users in that tenant can now authenticate via their Enterprise Application to your MCP server

**Considerations:**  
- **Data isolation**: All tenant data stored in the same database (with tenant-scoped access controls)
- **Enterprise Application management**: Each tenant admin controls user assignment and access via their Enterprise Application
- **Compliance**: Some organizations may require dedicated infrastructure for data residency

**Recommendation**: Multi-tenant configuration works well for SaaS scenarios where organizations are comfortable with shared infrastructure and proper data isolation controls.

## Client Secret Management

### Best Practices

1. **Set appropriate expiration** - Balance security vs. operational overhead
2. **Rotate before expiration** - Create new secret before old one expires
3. **Use Key Vault** - Store secrets in Azure Key Vault, not directly in Kubernetes
4. **Monitor expiration** - Set up alerts for upcoming secret expiration

### Rotation Process

1. Create new client secret in Entra app registration
2. Update Kubernetes secret with new value
3. Restart pods to pick up new secret
4. Verify authentication works
5. Delete old client secret from Entra

## Webhook Secret

The `MICROSOFT_WEBHOOK_SECRET` is used to validate incoming webhook notifications from Microsoft Graph:

- **Length**: 128 characters (recommended)
- **Format**: Random alphanumeric string
- **Generation**: `openssl rand -hex 64`

This secret is passed to Microsoft when creating Graph subscriptions and returned in webhook payloads for validation.

## Troubleshooting Authentication

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| `AADSTS700016` | Client ID not found | Verify `MICROSOFT_CLIENT_ID` matches app registration |
| `AADSTS7000215` | Invalid client secret | Rotate client secret and update `MICROSOFT_CLIENT_SECRET` |
| `AADSTS65001` | Consent not granted | User or admin must consent to permissions |
| `AADSTS50011` | Redirect URI mismatch | Verify redirect URI matches exactly |

### Verify Configuration

```bash
# Check app registration details
az ad app show --id <client-id> --query "{name:displayName,appId:appId,signInAudience:signInAudience}"

# List configured permissions
az ad app permission list --id <client-id> --query "[].resourceAccess[].id"

# Check admin consent status
az ad app permission list-grants --id <client-id>
```

## Microsoft Documentation

- [Register an application](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app)
- [Configure permissions](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-configure-app-access-web-apis)
- [Admin consent](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/grant-admin-consent)
- [Microsoft Graph permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference)
