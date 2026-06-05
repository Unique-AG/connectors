<!-- confluence-page-id: 2061664301 -->
<!-- confluence-space-key: PUBDOC -->

# Authentication

How the app registration is provisioned depends on your deployment model.

## Required Permissions

All permissions are **delegated** — they act on behalf of the signed-in user. None require admin consent. `Mail.ReadWrite.Shared` is always requested at OAuth time (even when `DELEGATED_ACCESS_SCAN=disabled`).

| Permission | Type | Admin Consent |
|------------|------|---------------|
| `User.Read` | Delegated | No |
| `Mail.ReadWrite` | Delegated | No |
| `Mail.ReadWrite.Shared` | Delegated | No |
| `MailboxSettings.Read` | Delegated | No |
| `People.Read` | Delegated | No |
| `offline_access` | Delegated | No |

For full justifications, see [Microsoft Graph Permissions](../technical/permissions.md).

## Unique SaaS

**Recommended for most clients.** When Unique runs Outlook Semantic MCP, Unique provisions the Entra ID app registration for you. You only need to grant admin consent:

```
https://login.microsoftonline.com/organizations/adminconsent?client_id=ba326974-edcf-49ef-bf7a-74b3e0ea450a
```

The consent prompt lists the [Required Permissions](#required-permissions) above. None require admin consent — users can also approve permissions themselves on first connection. Granting admin consent up front is optional but skips the per-user consent prompt.

If your organization uses multiple Azure tenants, confirm you are granting consent for the correct directory. See [Grant tenant-wide admin consent to an application](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/grant-admin-consent) for a tenant-specific admin consent URL; use application (client) ID `ba326974-edcf-49ef-bf7a-74b3e0ea450a`.

## Self-Hosted

When your organization hosts Outlook Semantic MCP, your team manages the full setup: Entra app registration, redirect URIs, secret rotation, and server configuration.

### App Registration

#### Option 1: Terraform (Recommended)

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

#### Option 2: Azure Portal (Manual)

1. Go to [Azure Portal](https://portal.azure.com) → **Azure Active Directory** → **App registrations** → **New registration**:
   - **Name**: Outlook Semantic MCP Server
   - **Supported account types**: Accounts in this organizational directory only
   - **Redirect URI**: Web — `https://outlook.semantic.mcp.example.com/auth/callback`

2. Go to **API permissions** → **Add a permission** → **Microsoft Graph** → **Delegated permissions**:
   - Add all permissions listed under [Required Permissions](#required-permissions)

3. Go to **Certificates & secrets** → **New client secret**:
   - Set description and expiration
   - **Copy the secret value immediately** (shown only once)

4. Go to **Overview** and note the **Application (client) ID** and **Directory (tenant) ID**

### Redirect URI Configuration

The redirect URI must match exactly what's configured in the app registration:

```
https://<your-domain>/auth/callback
```

Examples:

- Production: `https://outlook.semantic.mcp.example.com/auth/callback`
- Local development: `http://localhost:9542/auth/callback`

**Multiple redirect URIs** can be configured for different environments. If you run multiple server instances (e.g. staging and production), add each instance's redirect URI to the same app registration — you do not need a separate app registration per instance.

The redirect URI is derived from `SELF_URL`: the app registration redirect URI must be `<SELF_URL>/auth/callback`. This is unrelated to the `MICROSOFT_PUBLIC_WEBHOOK_URL` variable, which controls webhook callbacks only.

### Tenant Configuration

The Entra ID app registration's **sign-in audience** controls which users can authenticate. The service works identically in both modes — there is no code-level difference, no `MICROSOFT_TENANT_ID` environment variable, and no runtime tenant configuration. The choice is made once at app registration time.

| Question | → Pick |
|----------|--------|
| Will **only users from your own Microsoft 365 organization** connect? | **Single Tenant** |
| Will **users from multiple organizations** (e.g. customer tenants) connect to the same deployment? | **Multi-Tenant** |

#### Single Tenant

| Setting | Value |
|---------|-------|
| Azure Portal → "Supported account types" | **Accounts in this organizational directory only** |
| Terraform `sign_in_audience` | `"AzureADMyOrg"` |

Only users from the tenant where the app is registered can sign in. Admin consent is optional: set the `service_principal_configuration` Terraform variable to pre-grant permissions tenant-wide and skip per-user prompts.

#### Multi-Tenant

| Setting | Value |
|---------|-------|
| Azure Portal → "Supported account types" | **Accounts in any organizational directory** |
| Terraform `sign_in_audience` | `"AzureADMultipleOrgs"` (Terraform default) |

Users from any Microsoft 365 organization can sign in. When a user authenticates, Microsoft's OAuth flow automatically routes them to their home tenant.

**Customer onboarding:**

1. Create a single app registration in your own tenant with one `MICROSOFT_CLIENT_ID` and `MICROSOFT_CLIENT_SECRET`.
2. Each customer tenant admin grants consent for their organization:
   ```
   https://login.microsoftonline.com/{customer-tenant-id}/adminconsent?client_id={your-client-id}
   ```
   When approved, Microsoft creates an Enterprise Application in their tenant and grants the delegated permissions tenant-wide.
3. After consent, users from that tenant can sign in and connect their mailbox.

**Considerations:**

- **No `service_principal_configuration`**: Set to `null` for multi-tenant — service principals are created per-customer-tenant via the admin consent URL, not Terraform.
- **Data isolation**: All tenants share the same database. Data is scoped per-user; there is no tenant-level isolation boundary within the service.
- **Enterprise Application management**: Each customer tenant admin can independently control user assignment and revoke access from their Azure Portal.
- **Compliance**: Some organizations require dedicated infrastructure for data residency — deploy a separate instance per tenant with single-tenant configuration in that case.

### Secret Management

The service requires four secrets for authentication and data protection. All must be stored in Kubernetes Secrets (not ConfigMaps).

| Variable | Format | Generation | Purpose |
|----------|--------|------------|---------|
| `MICROSOFT_CLIENT_SECRET` | Azure-generated string | Created in Entra ID app registration | Authenticates the server to Microsoft Entra ID during OAuth flows |
| `MICROSOFT_WEBHOOK_SECRET` | 128-char hex string | `openssl rand -hex 64` | Validates that incoming webhook notifications come from Microsoft Graph |
| `AUTH_HMAC_SECRET` | 64-char hex string | `openssl rand -hex 32` | Signs OAuth session state during the MCP client authentication flow (HMAC-SHA256) |
| `ENCRYPTION_KEY` | 64-char hex string | `openssl rand -hex 32` | Encrypts Microsoft OAuth tokens (access + refresh) at rest in PostgreSQL using AES-256-GCM |

#### `MICROSOFT_CLIENT_SECRET`

**What happens if it expires or is deleted:** All OAuth flows fail immediately — no new users can connect, and existing users' tokens cannot be refreshed. Once an access token expires (~1 hour), that user's sync and tool calls stop working.

**How to rotate:**

1. Create a new client secret in the Entra ID app registration (keep the old one active during transition)
2. Update the Kubernetes secret with the new value
3. Restart pods to pick up the new secret
4. Verify authentication works (connect a test user)
5. Delete the old secret from Entra ID

Zero-downtime rotation is supported because Microsoft allows multiple active client secrets simultaneously.

**Best practices:** Set an appropriate expiration; rotate before expiration; store in Key Vault (the Terraform module does this automatically); set up Azure alerts for upcoming expiration.

#### `MICROSOFT_WEBHOOK_SECRET`

Passed to Microsoft as the `clientState` field when creating Graph subscriptions. Microsoft returns it unchanged in every webhook payload — the server rejects any notification where the value does not match.

**What happens if it is changed:** All existing subscriptions break.

- **Live catch-up stops** — all incoming email notifications are rejected until subscriptions are recreated.
- **Full sync is unaffected** — it pulls directly from Microsoft Graph and does not use webhooks.
- **Emails received during the gap** are not ingested until subscriptions are recreated. Once a user calls `reconnect_inbox`, live catch-up picks them up from the last watermark.

**How to rotate:**

1. Generate a new secret: `openssl rand -hex 64`
2. Update the Kubernetes secret and redeploy the service
3. All users must call `reconnect_inbox` to recreate their subscriptions with the new secret

Plan this as a maintenance window — there is no zero-downtime rotation path.

#### `ENCRYPTION_KEY`

Encrypts Microsoft OAuth tokens at rest in PostgreSQL using AES-256-GCM. Tokens are decrypted in memory when the server needs to call Microsoft Graph.

**What happens if it is changed:** All stored tokens become unreadable. Every user's sync stops and all tool calls fail. Users must re-authenticate by calling `reconnect_inbox`.

**How to rotate:**

1. Generate a new key: `openssl rand -hex 32`
2. Update the Kubernetes secret and redeploy
3. All users must call `reconnect_inbox` to re-authenticate

Plan this as a maintenance window — there is no zero-downtime rotation path.

#### `AUTH_HMAC_SECRET`

Signs and validates OAuth session state during the MCP client authentication flow (HMAC-SHA256), preventing CSRF and session tampering during the OAuth redirect sequence.

**What happens if it is changed:** Only in-flight OAuth sessions are invalidated. Already-connected users are not affected — their existing tokens and subscriptions continue to work.

**How to rotate:**

1. Generate a new secret: `openssl rand -hex 32`
2. Update the Kubernetes secret and redeploy
3. Users mid-OAuth-flow will see an error and need to restart the flow; already-authenticated users are unaffected

This is the lowest-impact secret to rotate.

For the full security context, see [Secret Management](../technical/security.md#Secret-Management).

### Understanding Consent Flows

**This is standard Microsoft behavior, not Outlook Semantic MCP specific.** All Microsoft 365 apps use the same consent model.

Because no permission in this app requires admin consent, users can complete the full consent flow independently:

1. **User consent** — on first connection, the user sees the Microsoft consent screen and approves the listed permissions
2. **Optional admin pre-consent** — an admin can grant consent organisation-wide via Azure Portal to skip the per-user consent prompt

**User Reconnection Experience (The "Login Flicker"):**

After first connection, subsequent reconnections show a quick "flicker" (brief redirect sequence). This is **normal** — Microsoft validates the existing session through rapid OAuth redirects. See [FAQ - Login "Flicker"](../faq.md#Authentication-&-Permissions) for details.

For detailed explanation, see [Microsoft Graph Permissions - Understanding Consent Requirements](../technical/permissions.md#Understanding-Consent-Requirements).

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
