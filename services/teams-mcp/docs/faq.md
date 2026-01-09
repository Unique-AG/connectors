# Frequently Asked Questions

## General

### What type of MCP server is this?

**Answer:** The Teams MCP Connector is a connector-style MCP server, not a traditional MCP server. Unlike traditional MCP servers that provide tools, prompts, resources, or other interactive capabilities, this connector operates automatically in the background once connected.

**What it does:**
- Once a user connects their Microsoft account, the connector automatically ingests meeting transcripts into the Unique knowledge base
- It does not expose any MCP tools, prompts, or resources
- It does not require any tool calls or additional interaction after the initial connection
- It operates continuously in the background, processing transcripts as they become available

**What it does not do:**
- Provide MCP tools for querying or manipulating data
- Offer prompts or prompt templates
- Expose resources for browsing or accessing
- Require any interaction beyond the initial connection

**Architecture:**
- Uses MCP OAuth for user authentication and connection
- Does not implement MCP tools, prompts, or resources
- Operates as a background service that automatically ingests transcripts
- Processes webhook notifications from Microsoft Graph API
- Ingests content into Unique knowledge base without requiring tool calls

**Design rationale:**
- The connector model allows for automatic, continuous data ingestion
- Users connect once and transcripts are automatically captured
- No need for interactive tool calls or resource browsing
- Simplifies the user experience by removing the need for ongoing interaction

This is a data ingestion connector that uses the MCP protocol for authentication and connection management, but functions as a background service rather than an interactive MCP server.

## Authentication & Permissions

### Why do I need admin consent?

**Answer:** `OnlineMeetingTranscript.Read.All` and `OnlineMeetingRecording.Read.All` require admin consent because they access sensitive meeting content. This is a Microsoft requirement, not a Teams MCP requirement.

**What to do:**
1. Go to Azure Portal → App Registration → API permissions
2. Click "Grant admin consent for [Your Organization]"
3. Users can then connect and grant their own consent

**See also:** [Understanding Admin Consent](./operator/authentication.md#understanding-microsoft-consent-flows)

### Why do users still need to consent after admin consent?

**Answer:** This is standard Microsoft behavior for delegated permissions. Even after admin consent, each user must individually consent because delegated permissions act on behalf of the signed-in user. This ensures users are aware of what data the app can access.

**This is not a bug** - it's how Microsoft OAuth works for all Microsoft 365 apps.

**See also:** [Understanding Consent Requirements](./technical/permissions.md#understanding-consent-requirements)

### What is the "login flicker" when users reconnect?

**Answer:** After a user has connected once, Microsoft Entra ID uses silent authentication on subsequent connections. The browser quickly redirects through the OAuth flow to validate the existing session, creating a brief "flicker" effect. This is **normal Microsoft OAuth behavior**, not a bug.

**See also:** [User Reconnection Experience](./operator/authentication.md#user-reconnection-experience-the-login-flicker)

### Why can't I use certificate authentication?

**Answer:** Certificate authentication only works with the Client Credentials flow, which requires application permissions. Teams MCP uses delegated permissions (user-specific access), which require the Authorization Code flow with a client secret.

**See also:** [Unsupported Authentication Methods](./technical/token-auth-flows.md#unsupported-authentication-methods)

### Why do I need a client secret?

**Answer:** The client secret proves to Microsoft that your server is the legitimate application (not an imposter). It's used during the OAuth token exchange to securely obtain Microsoft access and refresh tokens.

**Security note:** The client secret is never sent to clients - it's only used server-side during the OAuth flow.

**See also:** [Why Client ID is Required](./technical/token-auth-flows.md#why-client-id-is-required)

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

**See also:** [Unsupported Authentication Methods](./technical/token-auth-flows.md#unsupported-authentication-methods)

### Why can't I use multiple app registrations?

**Answer:** Each Teams MCP deployment uses one Microsoft Entra ID app registration. The app can be configured as multi-tenant to serve users from multiple organizations, but you don't need separate app registrations per tenant.

**See also:** [Single App Registration Architecture](./technical/token-auth-flows.md#single-app-registration-architecture)

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

**Answer:** The `MICROSOFT_WEBHOOK_SECRET` validates that incoming webhook notifications are actually from Microsoft Graph, not from an attacker. It's sent to Microsoft when creating subscriptions and returned in every webhook payload for validation.

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

**See also:** [Client Secret Management](./operator/authentication.md#client-secret-management)

## Architecture & Design

### Why are Microsoft tokens never sent to clients?

**Answer:** This is a critical security design. Microsoft OAuth tokens (access and refresh) are exchanged entirely on the server and stored encrypted. The server then issues separate opaque JWT tokens to clients for MCP API authentication. This ensures:
- Microsoft tokens never leave the server
- Clients cannot access Microsoft Graph API directly
- All Microsoft API calls are made by the server on behalf of authenticated users

**See also:** [Token Isolation](./technical/token-auth-flows.md#token-isolation)

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

### Why are subscriptions renewed instead of recreated?

**Answer:** Renewal (PATCH) is more efficient than recreation (DELETE + POST). It preserves the subscription ID and reduces API calls. Renewal happens automatically before expiration (default: 3 AM UTC daily) to ensure token validity is checked consistently.

**See also:** [Subscription Lifecycle](./technical/flows.md#subscription-lifecycle)

## Token Management

### What happens if token refresh fails?

**Possible causes:**
- Microsoft refresh token expired (~90 days of inactivity)
- User revoked consent in Microsoft account settings
- Network issues reaching Microsoft token endpoint
- Client secret was rotated without updating the configuration

**Resolution:** User must reconnect to MCP server to re-authenticate.

**See also:** [Microsoft Token Refresh Failed](./technical/token-auth-flows.md#microsoft-token-refresh-failed)

### What happens if a token family is revoked?

**Answer:** All refresh operations fail for that user. The user must re-authenticate completely. This happens automatically when refresh token reuse is detected (possible token theft).

**See also:** [Token Family Revoked](./technical/token-auth-flows.md#token-family-revoked)

### What happens if the encryption key changes?

**Answer:** All stored Microsoft tokens become unreadable. All users must reconnect to obtain fresh tokens. There is no zero-downtime rotation for the encryption key.

**See also:** [Encryption Key Changed](./technical/token-auth-flows.md#encryption-key-changed)

### Why are access tokens so short-lived (60 seconds)?

**Answer:** Short-lived access tokens reduce the impact of token theft. If an access token is compromised, it expires quickly. Refresh tokens are used to obtain new access tokens without user re-authentication.

**See also:** [MCP OAuth (Internal)](./technical/token-auth-flows.md#mcp-oauth-internal)

## Subscriptions & Processing

### Why do subscriptions expire?

**Answer:** Microsoft Graph subscriptions expire after a maximum of 3 days. Teams MCP automatically renews subscriptions before they expire (default: 3 AM UTC daily). This ensures token validity is checked consistently.

**See also:** [Subscription Lifecycle](./technical/flows.md#subscription-lifecycle)

### What happens if a subscription renewal fails?

**Answer:** The subscription is deleted and the user must reconnect to the MCP server to re-authenticate. This can happen if:
- Microsoft refresh token expired (~90 days of inactivity)
- User revoked app consent
- Network issues reaching Microsoft

**See also:** [Subscription Lifecycle](./technical/flows.md#subscription-lifecycle)

### Why aren't transcripts appearing in Unique?

**Answer:** Check the following:

1. **User has active subscription** - Verify the user successfully connected and subscription was created
2. **Webhook notifications received** - Check if Microsoft is sending notifications
3. **RabbitMQ queue processing** - Verify messages are being processed
4. **No processing errors** - Check logs for any failures during transcript processing

**See also:** [Transcript Processing Flow](./technical/flows.md#transcript-processing-flow)

## Webhooks & Processing

### Why use RabbitMQ for webhook processing?

**Answer:** Microsoft requires webhook responses in < 10 seconds. Transcript processing can take minutes (fetching meeting data, transcript content, recordings, uploading to Unique). RabbitMQ decouples webhook reception (fast 202 response) from processing (asynchronous), ensuring we meet Microsoft's strict timeout requirements.

**See also:** [Why RabbitMQ](./technical/why-rabbitmq.md)

### Can I deploy without RabbitMQ?

**Answer:** No. RabbitMQ is required to meet Microsoft's webhook response time requirements. Without it, webhook processing would timeout and Microsoft would stop sending notifications.

### How does webhook validation work?

**Answer:** When creating a subscription, the server sends `MICROSOFT_WEBHOOK_SECRET` as `clientState` to Microsoft. Microsoft returns this value in every webhook payload. The server validates that the received `clientState` matches the configured secret, rejecting invalid requests.

**See also:** [Webhook Validation](./technical/security.md#webhook-validation)

### What happens if webhook validation fails?

**Answer:** The request is rejected with 401 Unauthorized. Microsoft will retry the notification. If validation consistently fails, Microsoft may stop sending notifications for that subscription.

**See also:** [Webhook Validation](./technical/security.md#webhook-validation)

## Deployment

### Why do I need RabbitMQ?

**Answer:** Microsoft requires webhook responses in < 10 seconds. RabbitMQ decouples webhook reception (fast response) from transcript processing (slower, can take minutes). This ensures we meet Microsoft's strict timeout requirements.

**See also:** [Why RabbitMQ](./technical/why-rabbitmq.md)

### What happens if the database is full?

**Answer:** Write operations will fail. Solutions:
- Run token cleanup job manually
- Increase database storage
- Archive old data

## Data Model

### Why track token families?

**Answer:** Token family tracking enables theft detection. Each OAuth session has a `token_family` identifier. If a refresh token is reused (indicating possible theft), the entire family is revoked. This prevents attackers from using stolen tokens while the legitimate client continues working.

**See also:** [Token Family Tracking](./technical/architecture.md#key-design-decisions)

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

**See also:** [Token Isolation](./technical/token-auth-flows.md#token-isolation)

### What's the threat model?

**Answer:** The security architecture protects against:
- Token theft (refresh token rotation, family-based revocation)
- Authorization code interception (PKCE)
- Webhook spoofing (clientState validation)
- Token tampering (AES-GCM authenticated encryption)

**See also:** [Security](./technical/security.md)

## Microsoft Graph Integration

### Why can't I use certificate authentication?

**Answer:** Certificate authentication only works with Client Credentials flow, which requires application permissions. Teams MCP uses delegated permissions (user-specific access), which require the Authorization Code flow with a client secret.

**See also:** [Unsupported Authentication Methods](./technical/token-auth-flows.md#unsupported-authentication-methods)

### Why single app registration architecture?

**Answer:** Each MCP deployment uses one Microsoft Entra ID app registration that can serve users from multiple Microsoft tenants. When tenant admins grant consent, Microsoft creates Enterprise Applications in their tenants. This is simpler than managing multiple app registrations.

**See also:** [Single App Registration Architecture](./technical/token-auth-flows.md#single-app-registration-architecture)

### How does multi-tenant authentication work?

**Answer:**
1. App registration configured as multi-tenant ("Accounts in any organizational directory")
2. Tenant admin grants consent → Microsoft creates Enterprise Application in their tenant
3. Users authenticate via Enterprise Application in their tenant
4. One MCP deployment serves all tenants

**See also:** [Single App Registration Architecture](./technical/token-auth-flows.md#single-app-registration-architecture)

## Multi-Tenant

### Can one deployment serve multiple Microsoft tenants?

**Answer:** Yes. Configure the app registration with "Accounts in any organizational directory" (multi-tenant). When each organization's admin grants consent, Microsoft creates an Enterprise Application in their tenant. One MCP deployment serves all tenants.

**Considerations:**
- Data isolation: All tenant data stored in same database (with tenant-scoped access controls)
- Enterprise Application management: Each tenant admin controls user assignment
- Compliance: Some organizations may require dedicated infrastructure

**See also:** [Multi-Tenant App Registration](./operator/authentication.md#multi-tenant-app-registration)

## Related Documentation

- [Architecture](./technical/architecture.md) - System components and infrastructure
- [Security](./technical/security.md) - Encryption, authentication, and threat model
- [Token and Authentication](./technical/token-auth-flows.md) - Token types, validation, refresh flows
- [Flows](./technical/flows.md) - User connection, subscription lifecycle, transcript processing
- [Permissions](./technical/permissions.md) - Required scopes and least-privilege justification
- [Why RabbitMQ](./technical/why-rabbitmq.md) - Message queue rationale
- [Operator Guide](./operator/README.md) - Deployment and operations

## Standard References

- [Microsoft Graph API](https://learn.microsoft.com/en-us/graph/overview) - Graph API overview
- [Microsoft Entra ID Troubleshooting](https://learn.microsoft.com/en-us/entra/identity-platform/troubleshoot-authentication) - Authentication troubleshooting
- [Kubernetes Documentation](https://kubernetes.io/docs/) - Kubernetes official docs
