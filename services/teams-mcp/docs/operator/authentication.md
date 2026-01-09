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
   
   **Important**: Admin consent is required for `OnlineMeetingTranscript.Read.All` and `OnlineMeetingRecording.Read.All` permissions. Without admin consent, users will see an error when trying to connect. See [Understanding Admin Consent](#understanding-admin-consent-and-user-consent) below for details.

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

## Understanding Microsoft Consent Flows

**This is standard Microsoft behavior, not Teams MCP specific.** All Microsoft 365 apps use the same consent model.

### Standard Microsoft Consent Process

**Step 1: Admin adds the app and grants admin-required permissions**
- Admin registers the app in Microsoft Entra ID
- Admin grants consent for permissions requiring admin approval:
  - **Organization-wide**: All users can use the app
  - **Per-user**: Only specific users can use the app
- For Teams MCP: `OnlineMeetingTranscript.Read.All` and `OnlineMeetingRecording.Read.All` require admin consent

**Step 2: Admin approval workflow (if enabled in tenant)**
- If tenant has "requires approval flow" enabled, users must request admin approval
- Admin reviews and approves the app for that user
- This is in addition to Step 1

**Step 3: User consent (always required for delegated permissions)**
- Each user must sign in and consent individually
- This is required even after admin consent (Microsoft's requirement for delegated permissions)
- User sees consent screen on first connection

**How to grant admin consent:**
1. Azure Portal → App Registration → API permissions
2. Click "Grant admin consent for [Your Organization]" (organization-wide)
3. Or use [admin consent workflow](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/configure-admin-consent-workflow) for per-user approval

**Microsoft Documentation:**
- [User and admin consent overview](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/user-admin-consent-overview) - Standard Microsoft consent flows
- [Grant admin consent](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/grant-admin-consent) - Step-by-step guide
- [Admin consent workflow](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/configure-admin-consent-workflow) - Per-user approval process

### User Reconnection Experience (The "Login Flicker")

**First-time connection:** User sees full Microsoft consent screen and approves permissions.

**Subsequent reconnections:** User sees a quick "flicker" (brief redirect sequence). This is **normal** - Microsoft validates the existing session through rapid OAuth redirects. Standard Microsoft OAuth behavior.

### Consent Flow Summary

**Required for Teams MCP:**
1. Admin grants consent for admin-required permissions (`OnlineMeetingTranscript.Read.All`, `OnlineMeetingRecording.Read.All`)
   - Organization-wide OR per-user
2. If tenant has approval workflow enabled: Admin approves app for each requesting user
3. User consents individually (always required for delegated permissions, even after admin consent)

**Tenant settings control:**
- Whether users can consent to certain permissions
- Whether admin approval workflow is required
- Configured in Microsoft Entra ID → Enterprise applications → User settings

### Troubleshooting Consent Issues

| Error | Cause | Solution |
|-------|-------|----------|
| `AADSTS65001` | Consent not granted | Grant admin consent in Azure Portal, then have user sign in again |
| `AADSTS65005` | User consent required | User must sign in and approve the consent screen |
| `AADSTS90094` | Admin consent required | Administrator must grant consent for permissions marked "Admin Consent: Yes" |

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

### App Registration
- [Register an application](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app)
- [Configure permissions](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-configure-app-access-web-apis)

### Consent and Permissions
- [Grant admin consent to an application](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/grant-admin-consent) - **Required reading**: How to grant admin consent
- [Understanding user and admin consent](https://learn.microsoft.com/en-us/entra/identity-platform/howto-convert-app-to-be-multi-tenant#understand-user-and-admin-consent) - **Required reading**: Explains the difference between user and admin consent
- [Configure user consent settings](https://learn.microsoft.com/en-us/entra/identity/manage-apps/configure-user-consent) - How to configure what users can consent to
- [Admin consent workflow](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/configure-admin-consent-workflow) - How to set up consent request workflows

### Reference
- [Microsoft Graph permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference)
