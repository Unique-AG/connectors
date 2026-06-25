<!-- confluence-page-id: 1803026436 -->
<!-- confluence-space-key: PUBDOC -->

## Overview

The Teams MCP Server requires a Microsoft Entra ID (formerly Azure AD) app registration with **delegated permissions** to access Microsoft Graph API on behalf of users.

How the app registration is provisioned depends on your deployment model:

- **Unique SaaS** — Unique provisions and manages the registration; you grant admin consent
- **Self-Hosted** — your organization provisions the registration, manages secrets, and operates the server

For technical details about the OAuth flow, see [Microsoft OAuth Setup Flow](../technical/flows.md#microsoft-oauth-setup-flow) and [FAQ - Why do I need a client ID and client secret?](../faq.md#why-do-i-need-a-client-id-and-client-secret).

## Required Permissions

All permissions are **delegated** — they act on behalf of the signed-in user. Three permissions require admin consent before users can connect.

| Permission | Type | Admin Consent |
|------------|------|---------------|
| `User.Read` | Delegated | No |
| `Calendars.Read` | Delegated | No |
| `OnlineMeetings.Read` | Delegated | No |
| `OnlineMeetingRecording.Read.All` | Delegated | **Yes** |
| `OnlineMeetingTranscript.Read.All` | Delegated | **Yes** |
| `offline_access` | Delegated | No |
| `ChannelMessage.Send` | Delegated | No |
| `ChatMessage.Send` | Delegated | No |
| `Chat.ReadBasic` | Delegated | No |
| `Chat.Read` | Delegated | No |
| `Team.ReadBasic.All` | Delegated | No |
| `Channel.ReadBasic.All` | Delegated | No |
| `ChannelMessage.Read.All` | Delegated | **Yes** |

For full justifications, see [Microsoft Graph Permissions](../technical/permissions.md).

## Unique SaaS

**Recommended for most clients.** When Unique runs Teams MCP, Unique provisions the Entra ID app registration for you. You only need to grant admin consent:

```
https://login.microsoftonline.com/organizations/adminconsent?client_id=8ddffb12-1579-4fa8-8844-ca122e4308bc
```

The consent prompt lists the [Required Permissions](#required-permissions) above. Note that `OnlineMeetingRecording.Read.All`, `OnlineMeetingTranscript.Read.All`, and `ChannelMessage.Read.All` require admin consent — the URL above handles all three in one step. Without it, users will see an error when trying to connect.

If your organization uses multiple Azure tenants, confirm you are granting consent for the correct directory. See [Grant tenant-wide admin consent to an application](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/grant-admin-consent) for a tenant-specific admin consent URL; use application (client) ID `8ddffb12-1579-4fa8-8844-ca122e4308bc`.

## Self-Hosted

When your organization hosts Teams MCP, your team manages the full setup: Entra app registration, redirect URIs, secret management, and server configuration.

### App Registration

#### Option 1: Terraform (Recommended)

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

#### Option 2: Azure Portal (Manual)

1. Go to [Azure Portal](https://portal.azure.com) → **Azure Active Directory** → **App registrations** → **New registration**:
   - **Name**: Teams MCP Server
   - **Supported account types**: Accounts in this organizational directory only
   - **Redirect URI**: Web — `https://teams.mcp.example.com/auth/callback`

2. Go to **API permissions** → **Add a permission** → **Microsoft Graph** → **Delegated permissions**:
   - Add all permissions listed under [Required Permissions](#required-permissions)

3. Click **Grant admin consent for [Tenant]** and confirm.
   `OnlineMeetingRecording.Read.All`, `OnlineMeetingTranscript.Read.All`, and `ChannelMessage.Read.All` require this step — without it users cannot connect.

4. Go to **Certificates & secrets** → **New client secret**:
   - Set description and expiration
   - **Copy the secret value immediately** (shown only once)

5. Go to **Overview** and note the **Application (client) ID** and **Directory (tenant) ID**

### Redirect URI Configuration

The redirect URI must match exactly what's configured in the app registration:

```
https://<your-domain>/auth/callback
```

Examples:

- Production: `https://teams.mcp.example.com/auth/callback`
- Development: `http://localhost:<port>/auth/callback`

**Multiple redirect URIs** can be configured for different environments.

### Tenant Configuration

#### Single Tenant (Recommended)

For enterprise deployments within one organization:

| Setting | Value |
|---------|-------|
| Azure Portal → "Supported account types" | **Accounts in this organizational directory only** |
| Terraform `sign_in_audience` | `"AzureADMyOrg"` |

#### Multi-Tenant

For SaaS deployments serving users from multiple Microsoft 365 organizations:

| Setting | Value |
|---------|-------|
| Azure Portal → "Supported account types" | **Accounts in any organizational directory** |
| Terraform `sign_in_audience` | `"AzureADMultipleOrgs"` |

**How it works:** One app registration serves all tenants. When each organization's admin grants consent, Microsoft creates an Enterprise Application in their tenant. Users then authenticate via that Enterprise Application.

**Considerations:**

- Data isolation: All tenant data stored in the same database (with tenant-scoped access controls)
- Enterprise Application management: Each tenant admin controls user assignment and access
- Compliance: Some organizations may require dedicated infrastructure for data residency

See [Authentication Architecture - Single App Registration Architecture](../technical/architecture.md#single-app-registration-architecture) for details.

### Secret Management

#### Client Secret

**Best practices:**

1. Set appropriate expiration — balance security vs. operational overhead
2. Rotate before expiration — create the new secret before the old one expires
3. Use Key Vault — store secrets in Azure Key Vault, not directly in Kubernetes
4. Monitor expiration — set up alerts for upcoming secret expiration

**Rotation process:**

1. Create new client secret in Entra app registration
2. Update Kubernetes secret with new value
3. Restart pods to pick up new secret
4. Verify authentication works
5. Delete old client secret from Entra

#### Webhook Secret

The `MICROSOFT_WEBHOOK_SECRET` validates incoming webhook notifications from Microsoft Graph:

- **Length**: 128 characters (recommended)
- **Format**: Random alphanumeric string
- **Generation**: `openssl rand -hex 64`

This secret is passed to Microsoft when creating Graph subscriptions and returned in webhook payloads for validation.

### Understanding Consent Flows

**This is standard Microsoft behavior, not Teams MCP specific.** All Microsoft 365 apps use the same consent model.

Because three permissions require admin consent (`OnlineMeetingRecording.Read.All`, `OnlineMeetingTranscript.Read.All`, and `ChannelMessage.Read.All`), the consent sequence is:

1. **Admin grants consent** for those three permissions (organisation-wide or per-user). The remaining 10 permissions — including all other chat scopes (`ChannelMessage.Send`, `ChatMessage.Send`, `Chat.ReadBasic`, `Chat.Read`, `Team.ReadBasic.All`, `Channel.ReadBasic.All`) — are user-consentable and do not require admin action.
2. **User consent** — on first connection, the user sees the Microsoft consent screen and approves the remaining permissions

**How to grant admin consent:**

1. Azure Portal → App Registration → API permissions
2. Click "Grant admin consent for [Your Organization]"
3. Or use the [admin consent workflow](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/configure-admin-consent-workflow) for per-user approval

**User Reconnection Experience (The "Login Flicker"):**

After first connection, subsequent reconnections show a quick "flicker" (brief redirect sequence). This is **normal** — Microsoft validates the existing session through rapid OAuth redirects. See [FAQ - Login "Flicker"](../faq.md#what-is-the-login-flicker-when-users-reconnect) for details.

For troubleshooting consent issues, see [FAQ - Authentication & Permissions](../faq.md#authentication--permissions).

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
