<!-- confluence-page-id: 2061664301 -->
<!-- confluence-space-key: PUBDOC -->

# Authentication

## Overview

The Outlook Semantic MCP Server requires a Microsoft Entra ID (formerly Azure AD) app registration with delegated permissions to access Microsoft Graph API on behalf of users.

For technical details about the OAuth flow and why client credentials are required, see:

- [Authentication Flows](../technical/flows.md)
- [Microsoft Graph Permissions](../technical/permissions.md)
- [FAQ - Why do I need a client ID and client secret?](../faq.md#Why-do-I-need-a-client-ID-and-client-secret)

## App Registration

### Option 1: Terraform (Recommended)

Use the provided Terraform module:

> **Prerequisite:** Assumes an existing Azure Key Vault resource (referenced as `azurerm_key_vault.main` below). The Terraform module writes the client secret to Key Vault automatically.

```hcl
module "outlook_semantic_mcp_app" {
  # Adjust path based on your working directory — see note below
  source = "<path-to-connectors-repo>/services/outlook-semantic-mcp/deploy/terraform/azure/outlook-semantic-mcp-entra-application"

  display_name     = "Outlook Semantic MCP Server"
  sign_in_audience = "AzureADMyOrg"  # Single tenant
  notes            = "MCP server for Outlook email access"

  redirect_uris = [
    "https://outlook.semantic.mcp.example.com/auth/callback"
  ]

  confidential_clients = {
    production = {
      client_secret = {
        key_vault_id     = azurerm_key_vault.main.id
        end_date         = "2027-01-01T00:00:00Z"
        rotation_counter = 1
      }
    }
  }
}
```

> **Note:** Run Terraform from the `services/outlook-semantic-mcp/` directory, or adjust the source path to the full path from your repository root (e.g., `./services/outlook-semantic-mcp/deploy/terraform/azure/outlook-semantic-mcp-entra-application`).

> **`service_principal_configuration` (optional):** When set, the module creates a service principal and pre-grants delegated permissions tenant-wide via `azuread_service_principal_delegated_permission_grant`. Omit this variable for multi-tenant deployments where admin consent is granted by each customer tenant individually.

### Option 2: Azure Portal (Manual)

1. **Navigate to App Registrations**

   - Go to [Azure Portal](https://portal.azure.com)
   - Search for "App registrations"
   - Click "New registration"

2. **Configure Basic Settings**

   - **Name**: Outlook Semantic MCP Server
   - **Supported account types**: Accounts in this organizational directory only
   - **Redirect URI**: Web - `https://outlook.semantic.mcp.example.com/auth/callback`

3. **Add API Permissions**

   - Go to "API permissions"
   - Click "Add a permission" → "Microsoft Graph" → "Delegated permissions"
   - Add the following permissions:

   | Permission | Type | Admin Consent |
   |------------|------|---------------|
   | `User.Read` | Delegated | No |
   | `Mail.ReadWrite` | Delegated | No |
   | `MailboxSettings.Read` | Delegated | No |
   | `People.Read` | Delegated | No |
   | `offline_access` | Delegated | No |

4. **Create Client Secret**

   - Go to "Certificates & secrets"
   - Click "New client secret"
   - Set description and expiration
   - **Copy the secret value immediately** (shown only once)

5. **Note Application Details**

   - Go to "Overview"
   - Copy the **Application (client) ID**
   - Copy the **Directory (tenant) ID**

## Required Permissions

All five permissions (`User.Read`, `Mail.ReadWrite`, `MailboxSettings.Read`, `People.Read`, `offline_access`) are **delegated** and **do not require admin consent**.

For the complete permissions reference with justifications for each permission, see [Permissions](../technical/permissions.md).

## Understanding Microsoft Consent Flows

**This is standard Microsoft behavior, not Outlook Semantic MCP specific.** All Microsoft 365 apps use the same consent model.

### Standard Microsoft Consent Process

Because no permission in this app requires admin consent, users can complete the full consent flow independently:

1. **User consent** — on first connection, the user sees the Microsoft consent screen and approves the listed permissions
2. **Optional admin pre-consent** — an admin can grant consent organisation-wide via Azure Portal to skip the per-user consent prompt

**How to grant admin consent (optional):**

1. Azure Portal → App Registration → API permissions
2. Click "Grant admin consent for [Your Organization]"
3. Or use the [admin consent workflow](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/configure-admin-consent-workflow) for per-user approval

**Microsoft Documentation:**

- [User and admin consent overview](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/user-admin-consent-overview) - Standard Microsoft consent flows
- [Grant admin consent](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/grant-admin-consent) - Step-by-step guide
- [Admin consent workflow](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/configure-admin-consent-workflow) - Per-user approval process

For detailed explanation, see [Microsoft Graph Permissions - Understanding Consent Requirements](../technical/permissions.md#Understanding-Consent-Requirements).

### User Reconnection Experience (The "Login Flicker")

**First-time connection:** User sees full Microsoft consent screen and approves permissions.

**Subsequent reconnections:** User sees a quick "flicker" (brief redirect sequence). This is **normal** — Microsoft validates the existing session through rapid OAuth redirects. Standard Microsoft OAuth behavior.

For troubleshooting consent issues, see [FAQ - Authentication & Permissions](../faq.md#Authentication-&-Permissions).

## Redirect URI Configuration

The redirect URI must match exactly what's configured in the app registration:

```
https://<your-domain>/auth/callback
```

Examples:

- Production: `https://outlook.semantic.mcp.example.com/auth/callback`
- Local development: `http://localhost:9542/auth/callback`

**Multiple redirect URIs** can be configured for different environments. If you run multiple server instances (e.g., staging and production), add each instance's redirect URI to the same app registration — you do not need a separate app registration per instance.

The redirect URI is derived from `SELF_URL`: the app registration redirect URI must be `<SELF_URL>/auth/callback`. This is unrelated to the `MICROSOFT_PUBLIC_WEBHOOK_URL` variable, which controls webhook callbacks only.

## Tenant Configuration

The Entra ID app registration's **sign-in audience** controls which users can authenticate. The service itself works identically in both modes — there is no code-level difference, no `MICROSOFT_TENANT_ID` environment variable, and no runtime tenant configuration. The choice is made once at app registration time.

### Which option to pick

| Question | → Pick |
|----------|--------|
| Will **only users from your own Microsoft 365 organization** connect? | **Single Tenant** |
| Will **users from multiple organizations** (e.g. customer tenants) connect to the same deployment? | **Multi-Tenant** |

### Single Tenant

Use this when the MCP server serves one organization only.

| Setting | Value |
|---------|-------|
| Azure Portal → "Supported account types" | **Accounts in this organizational directory only** |
| Terraform `sign_in_audience` | `"AzureADMyOrg"` |

**What happens:** Only users from the tenant where the app is registered can sign in. No additional setup is needed for other tenants (they simply cannot authenticate).

**Admin consent (optional):** You can pre-grant permissions tenant-wide so users are not prompted individually. In Terraform, set the `service_principal_configuration` variable to create a service principal and grant delegated permissions automatically.

### Multi-Tenant

Use this when one MCP server deployment serves users from multiple Microsoft 365 organizations (e.g. a SaaS deployment).

| Setting | Value |
|---------|-------|
| Azure Portal → "Supported account types" | **Accounts in any organizational directory** |
| Terraform `sign_in_audience` | `"AzureADMultipleOrgs"` (this is the Terraform default) |

**What happens:** Users from any Microsoft 365 organization can sign in. When a user authenticates, Microsoft's OAuth flow automatically routes them to their home tenant.

**How customer onboarding works:**

1. You create a single app registration in your own tenant with one `MICROSOFT_CLIENT_ID` and `MICROSOFT_CLIENT_SECRET`.
2. Each customer tenant admin must grant consent for their organization. Share this URL with them:
   ```
   https://login.microsoftonline.com/{customer-tenant-id}/adminconsent?client_id={your-client-id}
   ```
   When the admin approves, Microsoft creates an **Enterprise Application** in their tenant and grants the delegated permissions tenant-wide.
3. After consent, users from that tenant can sign in and connect their mailbox — the server handles them the same as any other user.

**Important considerations:**

- **No Terraform `service_principal_configuration`**: For multi-tenant, set this to `null`. Service principals and delegated permission grants are created per-customer-tenant through the admin consent URL above, not via Terraform.
- **Data isolation**: All tenants share the same database. Data is scoped per-user (each user gets their own inbox configuration, tokens, and Knowledge Base root scope). There is no tenant-level isolation boundary within the service.
- **Enterprise Application management**: Each customer tenant admin can independently control user assignment and revoke access from their Azure Portal.
- **Compliance**: Some organizations may require dedicated infrastructure for data residency — in that case, deploy a separate instance per tenant with single-tenant configuration instead.

## Secret Rotation

The service requires four secrets for authentication and data protection. All must be stored in Kubernetes Secrets (not ConfigMaps).

| Secret | Format | Generation | Purpose |
|--------|--------|------------|---------|
| `MICROSOFT_CLIENT_SECRET` | Azure-generated string | Created in Entra ID app registration | Authenticates the server to Microsoft Entra ID during OAuth flows |
| `MICROSOFT_WEBHOOK_SECRET` | 128-char hex string | `openssl rand -hex 64` | Validates that incoming webhook notifications come from Microsoft Graph |
| `ENCRYPTION_KEY` | 64-char hex string | `openssl rand -hex 32` | Encrypts Microsoft OAuth tokens (access + refresh) at rest in PostgreSQL using AES-256-GCM |
| `AUTH_HMAC_SECRET` | 64-char hex string | `openssl rand -hex 32` | Signs OAuth session state during the MCP client authentication flow (HMAC-SHA256) |

### `MICROSOFT_CLIENT_SECRET`

The client secret from the Entra ID app registration. The server uses it to exchange authorization codes for tokens and to refresh expired access tokens.

**What happens if it expires or is deleted:** All OAuth flows fail immediately — no new users can connect, and existing users' tokens cannot be refreshed. Once an access token expires (~1 hour), that user's sync and tool calls stop working.

**How to rotate:**

1. Create a new client secret in the Entra ID app registration (keep the old one active during transition)
2. Update the Kubernetes secret with the new value
3. Restart pods to pick up the new secret
4. Verify authentication works (connect a test user)
5. Delete the old secret from Entra ID

This supports zero-downtime rotation because Microsoft allows multiple active client secrets simultaneously.

**Best practices:**

- Set appropriate expiration — balance security vs. operational overhead
- Rotate before expiration — create the new secret well in advance
- Use Key Vault — the Terraform module writes the secret to Key Vault automatically
- Monitor expiration — set up Azure alerts for upcoming secret expiration

### `MICROSOFT_WEBHOOK_SECRET`

Passed to Microsoft as the `clientState` field when creating Graph subscriptions. Microsoft returns it unchanged in every webhook payload, and the server rejects any notification where the value does not match.

**What happens if it is changed:** All existing subscriptions break. Every webhook notification from Microsoft will carry the old `clientState` and the server will reject it. This means:

- **Live catch-up stops** — all incoming email notifications are rejected until subscriptions are recreated.
- **Full sync is unaffected** — it pulls directly from Microsoft Graph and does not use webhooks.
- **Emails received during the gap will not be ingested into the Knowledge Base** until subscriptions are recreated. Once a user calls `reconnect_inbox` and the next live catch-up runs (triggered by a new notification or the 15-minute cron), it queries from the last watermark and picks up any emails missed during the gap.

**How to rotate:**

1. Generate a new secret: `openssl rand -hex 64`
2. Update the Kubernetes secret and redeploy the service
3. All users must call `reconnect_inbox` to recreate their subscriptions with the new secret
4. Emails arriving during the gap will not be ingested until `reconnect_inbox` is called. After that, live catch-up picks them up automatically on the next notification or 15-minute cron cycle (it queries from the last watermark)

Plan this as a maintenance window — there is no zero-downtime rotation path.

### `ENCRYPTION_KEY`

Used to encrypt Microsoft OAuth tokens (access and refresh tokens) before storing them in PostgreSQL with AES-256-GCM. Tokens are decrypted in memory when the server needs to call Microsoft Graph.

**What happens if it is changed:** All stored Microsoft tokens become unreadable. Every user's sync stops and all tool calls that require Microsoft Graph access fail. Users must re-authenticate by calling `reconnect_inbox`.

**How to rotate:**

1. Generate a new key: `openssl rand -hex 32`
2. Update the Kubernetes secret and redeploy
3. All users must call `reconnect_inbox` to re-authenticate — their stored tokens are no longer decryptable

Plan this as a maintenance window and notify users in advance — there is no zero-downtime rotation path.

### `AUTH_HMAC_SECRET`

Used to sign and validate OAuth session state during the MCP client authentication flow (HMAC-SHA256). This prevents CSRF and session tampering during the OAuth redirect sequence.

**What happens if it is changed:** All in-flight OAuth sessions are immediately invalidated. Users who are in the middle of connecting will see an error and need to restart the flow. Already-connected users are not affected — their existing tokens and subscriptions continue to work.

**How to rotate:**

1. Generate a new secret: `openssl rand -hex 32`
2. Update the Kubernetes secret and redeploy
3. Already-authenticated users are **not** affected — their existing MCP tokens and Microsoft tokens continue to work. Only users who are mid-OAuth-flow at the moment of rotation will see an error and need to restart the flow. When an MCP access token expires (60 seconds), the MCP refresh token (unaffected by the HMAC change) is used to obtain a new one — no user action needed.

This is the lowest-impact secret to rotate. Existing connections are unaffected.

For the full security context, see [Secret Management](../technical/security.md#Secret-Management).

For troubleshooting authentication issues, see [FAQ - Authentication & Permissions](../faq.md#Authentication-&-Permissions).

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
