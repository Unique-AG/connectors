<!-- confluence-page-id: 1803026436 -->
<!-- confluence-space-key: PUBDOC -->

## Overview

The Teams MCP Server requires a Microsoft Entra ID (formerly Azure AD) app registration with delegated permissions to access Microsoft Graph API on behalf of users.

For technical details about the OAuth flow and why client credentials are required, see:

- [Microsoft OAuth Setup Flow](../technical/flows.md#microsoft-oauth-setup-flow)
- [Authentication Architecture - Required App Registration Components](../technical/architecture.md#required-app-registration-components)
- [FAQ - Why do I need a client ID and client secret?](../faq.md#why-do-i-need-a-client-id-and-client-secret)

## App Registration

### Option 1: Terraform (Recommended)

Use the provided Terraform module:

```hcl
module "teams_mcp_app" {
  source = "./deploy/terraform/azure/teams-mcp-entra-application"

  display_name     = "Teams MCP Server"
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

   - **Name**: Teams MCP Server
   - **Supported account types**: Accounts in this organizational directory only
   - **Redirect URI**: Web - `https://teams.mcp.example.com/auth/callback`

3. **Add API Permissions**

   - Go to "API permissions"
   - Click "Add a permission" → "Microsoft Graph" → "Delegated permissions"
   - Add the following permissions:

   | Permission | Type | Admin Consent |
   |------------|------|---------------|
   | `User.Read` | Delegated | No |
   | `Calendars.Read` | Delegated | No |
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

All permissions are **delegated**, meaning they act on behalf of the signed-in user. See [Microsoft Graph Permissions](../technical/permissions.md) for the complete list with justifications.

**Required:**

- `User.Read` - Read user profile
- `Calendars.Read` - Read calendar events (for recurring meeting detection)
- `OnlineMeetings.Read` - Read meeting details
- `OnlineMeetingTranscript.Read.All` - Read transcripts (admin consent required)
- `offline_access` - Obtain refresh tokens

**Optional:**

- `OnlineMeetingRecording.Read.All` - Read recordings (admin consent required)

## Understanding Microsoft Consent Flows

**This is standard Microsoft behavior, not Teams MCP specific.** All Microsoft 365 apps use the same consent model.

### Standard Microsoft Consent Process

1. **Admin grants consent** for permissions requiring admin approval (`OnlineMeetingTranscript.Read.All`, `OnlineMeetingRecording.Read.All`)

   - Organization-wide OR per-user
2. **Admin approval workflow** (if enabled in tenant) - users request approval
3. **User consent** (always required for delegated permissions, even after admin consent)

**How to grant admin consent:**

1. Azure Portal → App Registration → API permissions
2. Click "Grant admin consent for [Your Organization]"
3. Or use [admin consent workflow](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/configure-admin-consent-workflow) for per-user approval

**Microsoft Documentation:**

- [User and admin consent overview](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/user-admin-consent-overview) - Standard Microsoft consent flows
- [Grant admin consent](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/grant-admin-consent) - Step-by-step guide
- [Admin consent workflow](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/configure-admin-consent-workflow) - Per-user approval process

For detailed explanation, see [Microsoft Graph Permissions - Understanding Consent Requirements](../technical/permissions.md#understanding-consent-requirements).

### User Reconnection Experience (The "Login Flicker")

**First-time connection:** User sees full Microsoft consent screen and approves permissions.

**Subsequent reconnections:** User sees a quick "flicker" (brief redirect sequence). This is **normal** - Microsoft validates the existing session through rapid OAuth redirects. Standard Microsoft OAuth behavior. See [FAQ - Login "Flicker"](../faq.md#what-is-the-login-flicker-when-users-reconnect) for details.

For troubleshooting consent issues, see [FAQ - Authentication & Permissions](../faq.md#authentication--permissions).

## Redirect URI Configuration

The redirect URI must match exactly what's configured in the app registration:

```
https://<your-domain>/auth/callback
```

Examples:

- Production: `https://teams.mcp.example.com/auth/callback`
- Development: `http://localhost:<port>/auth/callback`

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
2. **Enterprise Application Creation**: When each organization's admin grants consent, Microsoft creates an "Enterprise Application" in their tenant
3. **User Authentication Flow**: Users authenticate via the Enterprise Application in their tenant
4. **Shared Infrastructure**: One MCP deployment serves all tenants

**Considerations:**

- Data isolation: All tenant data stored in the same database (with tenant-scoped access controls)
- Enterprise Application management: Each tenant admin controls user assignment and access
- Compliance: Some organizations may require dedicated infrastructure for data residency

See [Authentication Architecture - Single App Registration Architecture](../technical/architecture.md#single-app-registration-architecture) for details.

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

For troubleshooting authentication issues, see [FAQ - Authentication & Permissions](../faq.md#authentication--permissions).

## Microsoft Documentation

### App Registration

- [Register an application](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app)
- [Configure permissions](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-configure-app-access-web-apis)

### Consent and Permissions

- [Grant admin consent to an application](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/grant-admin-consent)
- [Understanding user and admin consent](https://learn.microsoft.com/en-us/entra/identity-platform/howto-convert-app-to-be-multi-tenant#understand-user-and-admin-consent)
- [Configure user consent settings](https://learn.microsoft.com/en-us/entra/identity/manage-apps/configure-user-consent)
- [Admin consent workflow](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/configure-admin-consent-workflow)

### Reference

- [Microsoft Graph permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference)
- [Microsoft Graph API overview](https://learn.microsoft.com/en-us/graph/overview)