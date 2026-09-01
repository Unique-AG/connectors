<!-- confluence-page-id: 1801846803 -->
<!-- confluence-space-key: PUBDOC -->

## General

### What type of MCP server is this?

**Answer:** The Teams MCP Server is an **interactive MCP server**. It exposes a tool surface that AI clients call on demand to read, search, and send Microsoft Teams chat and channel messages. Every call is served live from the Microsoft Graph API — **nothing is copied into the Unique knowledge base**.

**What it does:**

- Exposes **8 chat and messaging tools**: `list_teams`, `list_channels`, `list_chats`, `get_chat_messages`, `get_channel_messages`, `search_messages`, `send_channel_message`, `send_chat_message`
- Chat and channel tools take ids obtained from the `list_*` tools (e.g. `list_chats` → `chatId` → `get_chat_messages`)

**What the user sees:**

- An initial OAuth consent screen to connect their Microsoft account
- All chat and messaging tools available immediately after connection

**Optional: meeting transcript capture.** Deployments that set `UNIQUE_INTEGRATION=enabled` additionally capture meeting transcripts and recordings into the Unique knowledge base and register four more tools. That is a separate, opt-in capability — see [Recordings & Transcripts](https://unique-ch.atlassian.net/wiki/spaces/PUBDOC/pages/2534866977/Recordings+Transcripts). Most deployments do not enable it.

The chat tools can also be turned off independently: `CHAT_INTEGRATION=disabled` with `UNIQUE_INTEGRATION=enabled` produces an **ingestion-only** deployment (transcript capture, no chat tools, no messaging permissions). See [Configuration — Chat Integration](./operator/configuration.md#chat-integration).

**See also:** [Technical Reference — Tools](./technical/tools.md)

## Authentication & Permissions

### Do I need admin consent?

**Answer:** Yes, for one scope. `ChannelMessage.Read.All` — which `get_channel_messages` and `search_messages` need to read channel message content — requires admin consent because channel messages may contain sensitive organisational content. Every other chat and messaging scope is user-consentable.

Enabling meeting transcript capture adds two more admin-consent scopes, `OnlineMeetingTranscript.Read.All` and `OnlineMeetingRecording.Read.All`. See [Recordings & Transcripts — Operator Manual](https://unique-ch.atlassian.net/wiki/spaces/PUBDOC/pages/2535522323/Recordings+Transcripts+-+Operator+Manual).

**See also:** [Understanding Admin Consent](./operator/authentication.md#understanding-consent-flows)

### Why do users still need to consent after admin consent?

**Answer:** This is standard Microsoft behavior for delegated permissions. Even after admin consent, each user must individually consent because delegated permissions act on behalf of the signed-in user. This ensures users are aware of what data the app can access.

**This is not a bug** - it's how Microsoft OAuth works for all Microsoft 365 apps.

**See also:** [Understanding Consent Requirements](./technical/permissions.md#understanding-consent-requirements)

### What is the "login flicker" when users reconnect?

**Answer:** After a user has connected once, Microsoft Entra ID uses silent authentication on subsequent connections. The browser quickly redirects through the OAuth flow to validate the existing session, creating a brief "flicker" effect. This is **normal Microsoft OAuth behavior**, not a bug.

**See also:** [User Reconnection Experience](./operator/authentication.md#understanding-consent-flows)

### Why can't I use certificate authentication?

**Answer:** While it's technically possible to use certificate authentication with the Authorization Code flow, it would require significant additional implementation effort in our OAuth packages. The standard approach for delegated permissions is to use a client secret, which is simpler to implement and maintain.

**See also:**

- [Authentication Architecture - Unsupported Authentication Methods](./technical/architecture.md#unsupported-authentication-methods)
- [Microsoft Entra ID - Authentication flows](https://learn.microsoft.com/en-us/entra/identity-platform/msal-authentication-flows)

### Why do I need a client ID and client secret?

**Answer:** Microsoft Graph API uses OAuth 2.0 for authentication, which requires a `CLIENT_ID` to identify and authorize applications. The `CLIENT_SECRET` proves to Microsoft that your server is the legitimate application (not an imposter). It's used during the OAuth token exchange to securely obtain Microsoft access and refresh tokens.

The `CLIENT_ID` enables Microsoft to verify application identity, enforce permissions, enable consent flows, track and audit API usage, and ensure delegated authorization is scoped to data the signed-in user can access.

**Security note:** The client secret is never sent to clients - it's only used server-side during the OAuth flow.

**See also:**

- [Authentication Architecture - Required App Registration Components](./technical/architecture.md#required-app-registration-components)
- [Microsoft Graph API - Get access on behalf of a user](https://learn.microsoft.com/en-us/graph/auth-v2-user)

### Why can't I use application permissions instead of delegated?

**Answer:** Application permissions would require tenant administrators to create Application Access Policies via PowerShell for each user. This defeats the self-service MCP model where users connect their own accounts without IT involvement.

**See also:** [Why Delegated (Not Application) Permissions](./technical/permissions.md#why-delegated-not-application-permissions)

### What's the difference between delegated and application permissions?

**Answer:**

- **Delegated:** Acts on behalf of the signed-in user, only accesses data that user can access
- **Application:** Acts as the application itself, requires admin-configured policies per user

Teams MCP uses delegated permissions for self-service user connections.

**See also:** [Why Delegated (Not Application) Permissions](./technical/permissions.md#why-delegated-not-application-permissions)

### Why can't I use Client Credentials flow?

**Answer:** Client Credentials flow only supports application permissions, which would require tenant admins to create Application Access Policies per user via PowerShell. This is impractical for self-service MCP connections. Delegated permissions require the Authorization Code flow.

**See also:**

- [Authentication Architecture - Unsupported Authentication Methods](./technical/architecture.md#unsupported-authentication-methods)
- [Microsoft Entra ID - Authentication flows](https://learn.microsoft.com/en-us/entra/identity-platform/msal-authentication-flows)

### Why can't I use multiple app registrations?

**Answer:** Each Teams MCP deployment uses one Microsoft Entra ID app registration. The app can be configured as multi-tenant to serve users from multiple organizations, but you don't need separate app registrations per tenant.

**Single App Registration Architecture:**

- **Single App Registration**: One `CLIENT_ID`/`CLIENT_SECRET` pair per deployment
- **Multi-Tenant Capable**: The app registration can be configured to accept users from multiple Microsoft tenants
- **Cross-Tenant Authentication**: Users from different organizations authenticate via Enterprise Applications in their tenant that reference the original app registration
- **Enterprise Application Creation**: When tenant admin grants consent, Microsoft creates an Enterprise Application in their tenant as a proxy to the original app registration

This design uses a single OAuth application that can serve users across multiple tenants, rather than requiring separate app registrations per organization.

**See also:**

- [Authentication Architecture - Single App Registration Architecture](./technical/architecture.md#single-app-registration-architecture)
- [Microsoft Entra ID Documentation](https://learn.microsoft.com/en-us/entra/identity/) - Authentication and authorization

## Configuration

### What's the redirect URI format?

**Answer:** The redirect URI must match exactly:
```
https://<your-domain>/auth/callback
```

**Common mistakes:**

- Missing trailing slash (if configured with one)
- Using `http://` instead of `https://` in production
- Wrong path (must be `/auth/callback`)

**See also:** [Redirect URI Configuration](./operator/authentication.md#redirect-uri-configuration)

### Why do I need a webhook secret?

**Answer:** `MICROSOFT_WEBHOOK_SECRET` is only used by meeting transcript capture. It validates that incoming webhook notifications really come from Microsoft Graph: the value is sent to Microsoft as `clientState` when creating a subscription and returned in every notification for validation. A chat-only deployment receives no webhooks and does not need it.

**Generate:** `openssl rand -hex 64` (128 characters)

**See also:** [Webhook Secret](./operator/authentication.md#webhook-secret)

### What happens if I change the encryption key?

**Answer:** All stored Microsoft tokens become unreadable. All users must reconnect to the MCP server to re-authenticate. There is no zero-downtime rotation for the encryption key.

**Best practice:** Plan for a maintenance window and notify users before rotating the encryption key.

**See also:** [ENCRYPTION_KEY Rotation](./technical/security.md#rotation-procedures)

### What happens if I change the client secret?

**Answer:** Update the Kubernetes secret and restart the pods. Users don't need to reconnect - the server will use the new secret for token refresh operations.

**Rotation process:**

1. Create new secret in Entra ID
2. Update Kubernetes secret
3. Restart pods
4. Verify authentication works
5. Delete old secret from Entra ID

**See also:** [Client Secret Management](./operator/authentication.md#client-secret)

### What happens if I change the webhook secret?

**Answer:** Rotation is currently not possible, because every existing transcript subscription carries the old value. This only affects deployments with transcript capture enabled — see [Recordings & Transcripts — FAQ](https://unique-ch.atlassian.net/wiki/spaces/PUBDOC/pages/2535129116/Recordings+Transcripts+-+FAQ#What-happens-if-the-webhook-secret-changes?).

## Architecture & Design

### Why are Microsoft tokens never sent to clients?

**Answer:** This is a critical security design. Microsoft OAuth tokens (access and refresh) are exchanged entirely on the server and stored encrypted. The server then issues separate opaque JWT tokens to clients for MCP API authentication. This ensures:
- Microsoft tokens never leave the server
- Clients cannot access Microsoft Graph API directly
- All Microsoft API calls are made by the server on behalf of authenticated users

**Token Isolation Design:**

1. **Microsoft OAuth Flow**: User authenticates with Microsoft Entra ID
2. **Token Exchange**: Server exchanges authorization code for Microsoft tokens (using `CLIENT_SECRET`)
3. **Token Storage**: Microsoft tokens are encrypted and stored on the server only
4. **Client Authentication**: Server issues separate opaque JWT tokens to the client for MCP API access

**See also:**

- [Authentication Architecture - Token Isolation](./technical/architecture.md#token-isolation)
- [Authentication Architecture - Token Storage](./technical/architecture.md#token-storage)

### Why are MCP tokens hashed but Microsoft tokens encrypted?

**Answer:**

- **MCP tokens:** Opaque JWTs that the server doesn't need to read - hash comparison is sufficient for validation
- **Microsoft tokens:** Must be decrypted to use for Graph API calls - encryption allows retrieval

Hashing reduces attack surface (no decryption key needed for MCP tokens), while encryption enables token retrieval for Microsoft API calls.

**See also:** [Token Security](./technical/security.md#token-security)

### Why use AES-GCM for token encryption?

**Answer:** AES-GCM provides authenticated encryption - both confidentiality and integrity. It prevents tampering with ciphertext and is an industry standard for token encryption.

**See also:** [Microsoft Tokens (Encrypted at Rest)](./technical/security.md#microsoft-tokens-encrypted-at-rest)

### Why refresh tokens rotate?

**Answer:** Refresh token rotation with family-based revocation detects token theft. If a refresh token is reused (indicating possible theft), the entire token family is revoked. This prevents attackers from using stolen tokens while the legitimate client continues working.

**See also:** [Refresh Token Rotation](./technical/security.md#refresh-token-rotation)

## Token Management

### What happens if token refresh fails?

**Possible causes:**

- Microsoft refresh token expired (~90 days of inactivity)
- User revoked consent in Microsoft account settings
- Network issues reaching Microsoft token endpoint
- Client secret was rotated without updating the configuration

**Resolution:** User must reconnect to MCP server to re-authenticate.

**See also:**

- [Microsoft Token Refresh Flow](./technical/flows.md#microsoft-token-refresh-flow)
- [Microsoft Entra ID Troubleshooting](https://learn.microsoft.com/en-us/entra/identity-platform/troubleshoot-authentication)

### What happens if a token family is revoked?

**Answer:** All refresh operations fail for that user. The user must re-authenticate completely. This happens automatically when refresh token reuse is detected (possible token theft).

**See also:**

- [Architecture - Token Family Tracking](./technical/architecture.md#postgresql)
- [Security - Refresh Token Rotation](./technical/security.md#refresh-token-rotation)

### What happens if the encryption key changes?

**Answer:** All stored Microsoft tokens become unreadable. All users must reconnect to obtain fresh tokens. There is no zero-downtime rotation for the encryption key.

**See also:**

- [Authentication Architecture - Token Encryption](./technical/architecture.md#token-encryption)
- [Security - ENCRYPTION_KEY Rotation](./technical/security.md#rotation-procedures)

### Why are MCP access tokens so short-lived (60 seconds)?

**Answer:** Short-lived access tokens reduce the impact of token theft. If an access token is compromised, it expires quickly. Refresh tokens are used to obtain new access tokens without user re-authentication.

**See also:**

- [Authentication Architecture - MCP OAuth (Internal)](./technical/architecture.md#mcp-oauth-internal)
- [MCP Authorization](https://modelcontextprotocol.io/specification/2025-03-26/basic/authorization) - MCP protocol authorization spec

## Webhooks & Processing

Webhooks are only used by meeting transcript capture. A chat-only deployment exposes no webhook endpoint and needs no RabbitMQ. For the queue, dead-letter handling, and processing pipeline, see [Recordings & Transcripts — Technical Manual](https://unique-ch.atlassian.net/wiki/spaces/PUBDOC/pages/2399993877/Recordings+Transcripts+-+Technical+Manual#Ingestion-pipeline).

### How does webhook validation work?

**Answer:** When creating a subscription, the server sends `MICROSOFT_WEBHOOK_SECRET` as `clientState` to Microsoft. Microsoft returns this value in every webhook payload. The server validates that the received `clientState` matches the configured secret, rejecting invalid requests.

**See also:** [Webhook Validation](./technical/security.md#webhook-validation)

### What happens if webhook validation fails?

**Answer:** The request is rejected with 401 Unauthorized. Microsoft will retry the notification. If validation consistently fails, Microsoft may stop sending notifications for that subscription.

**See also:** [Webhook Validation](./technical/security.md#webhook-validation)

## Deployment

### What happens if the database is full?

**Answer:** Write operations will fail. Solutions:

- Run token cleanup job manually
- Increase database storage
- Archive old data

## Data Model

### Why track token families?

**Answer:** Token family tracking enables theft detection. Each OAuth session has a `token_family` identifier. If a refresh token is reused (indicating possible theft), the entire family is revoked. This prevents attackers from using stolen tokens while the legitimate client continues working.

**See also:** [Token Family Tracking](./technical/architecture.md#postgresql)

### Why store MCP tokens as hashes?

**Answer:** MCP tokens are opaque JWTs - the server doesn't need to read them, only validate them. Hash comparison is sufficient for validation and reduces attack surface (no decryption key needed).

**See also:** [MCP Tokens (Hashed for Validation)](./technical/security.md#mcp-tokens-hashed-for-validation)

### Why encrypt Microsoft tokens instead of hashing?

**Answer:** Microsoft tokens must be decrypted to use for Graph API calls. Encryption allows retrieval, while hashing is one-way and would prevent token usage.

**See also:** [Microsoft Tokens (Encrypted at Rest)](./technical/security.md#microsoft-tokens-encrypted-at-rest)

## Security

### How are Microsoft tokens stored?

**Answer:** Microsoft access and refresh tokens are encrypted at rest using AES-256-GCM and stored in the `user_profiles` table. They are **never sent to clients** - only opaque JWT tokens are issued to clients for MCP authentication.

**See also:** [Token Security](./technical/security.md#token-security)

### What happens if a refresh token is stolen?

**Answer:** If a refresh token is reused (indicating possible theft), the entire token family is revoked. The user must re-authenticate completely. This is detected automatically by the refresh token rotation mechanism.

**See also:** [Refresh Token Rotation](./technical/security.md#refresh-token-rotation)

### Why use PKCE?

**Answer:** PKCE (Proof Key for Code Exchange) prevents authorization code interception attacks. It's required for all OAuth flows in OAuth 2.1 and uses `S256` challenge method (SHA-256).

**See also:** [OAuth 2.1 with PKCE](./technical/security.md#oauth-21-with-pkce)

### Why separate MCP tokens from Microsoft tokens?

**Answer:** This design ensures:

- Microsoft tokens never leave the server
- Clients cannot access Microsoft Graph API directly
- All Microsoft API calls are made by the server on behalf of authenticated users
- Client tokens are opaque JWTs that only authenticate with the MCP server

**See also:**

- [Authentication Architecture - Token Isolation](./technical/architecture.md#token-isolation)
- [Microsoft Graph - Get access on behalf of a user](https://learn.microsoft.com/en-us/graph/auth-v2-user)

### What's the threat model?

**Answer:** The security architecture protects against:

- Token theft (refresh token rotation, family-based revocation)
- Authorization code interception (PKCE)
- Webhook spoofing (clientState validation)
- Token tampering (AES-GCM authenticated encryption)

**See also:** [Security](./technical/security.md)

## Microsoft Graph Integration

### Why single app registration architecture?

**Answer:** Each MCP deployment uses one Microsoft Entra ID app registration that can serve users from multiple Microsoft tenants. When tenant admins grant consent, Microsoft creates Enterprise Applications in their tenants. This is simpler than managing multiple app registrations.

**See also:**

- [Authentication Architecture - Single App Registration Architecture](./technical/architecture.md#single-app-registration-architecture)
- [Microsoft Entra ID Documentation](https://learn.microsoft.com/en-us/entra/identity/)

### How does multi-tenant authentication work?

**Answer:**

1. App registration configured as multi-tenant ("Accounts in any organizational directory")
2. Tenant admin grants consent → Microsoft creates Enterprise Application in their tenant
3. Users authenticate via Enterprise Application in their tenant
4. One MCP deployment serves all tenants

**See also:**

- [Authentication Architecture - Single App Registration Architecture](./technical/architecture.md#single-app-registration-architecture)
- [Microsoft Entra ID Documentation](https://learn.microsoft.com/en-us/entra/identity/)

## Multi-Tenant

### Can a user connect multiple Microsoft tenants?

**Answer:** Not in a single session. One OAuth login covers exactly one Microsoft tenant. If a user belongs to multiple tenants (e.g., their home tenant plus a guest tenant), they must authenticate separately for each tenant they want to reach.

Each tenant authentication creates an independent user profile in Teams MCP, and every tool call is scoped to the identity used to connect that tenant.

**See also:** [Single App Registration Architecture](./technical/architecture.md#single-app-registration-architecture)

### Can one deployment serve multiple Microsoft tenants?

**Answer:** Yes. Configure the app registration with "Accounts in any organizational directory" (multi-tenant). When each organization's admin grants consent, Microsoft creates an Enterprise Application in their tenant. One MCP deployment serves all tenants.

**Considerations:**

- Data isolation: All tenant data stored in same database (with tenant-scoped access controls)
- Enterprise Application management: Each tenant admin controls user assignment
- Compliance: Some organizations may require dedicated infrastructure

**See also:** [Multi-Tenant App Registration](./operator/authentication.md#multi-tenant)

### Why do I get AADSTS50194 when signing in?

**Answer:** Login used `/common`, but the Enterprise Application (service principal) only exists in one directory, so Microsoft rejected the authority.

Set `MICROSOFT_SIGN_IN_TENANT` (Helm `mcpConfig.microsoft.signInTenant`) to that directory's GUID so the login window opens the foreign tenant's service principal. Leave it as `common` when users should choose their directory at login.

**See also:** [OAuth authority](./operator/authentication.md#oauth-authority-microsoft_sign_in_tenant)

## Related Documentation

- [Architecture](./technical/architecture.md) - System components and infrastructure
- [Security](./technical/security.md) - Encryption, authentication, and threat model
- [Flows](./technical/flows.md) - User connection, OAuth, token refresh, and chat tool sequences
- [Permissions](./technical/permissions.md) - Required scopes and least-privilege justification
- [Operator Guide](./operator/README.md) - Deployment and operations
- [Recordings & Transcripts - FAQ](https://unique-ch.atlassian.net/wiki/spaces/PUBDOC/pages/2535129116/Recordings+Transcripts+-+FAQ) - Meeting transcript capture, subscriptions, and the Recordings area

## Standard References

- [Microsoft Graph API](https://learn.microsoft.com/en-us/graph/overview) - Graph API overview
- [Microsoft Entra ID Troubleshooting](https://learn.microsoft.com/en-us/entra/identity-platform/troubleshoot-authentication) - Authentication troubleshooting
- [Kubernetes Documentation](https://kubernetes.io/docs/) - Kubernetes official docs
