# Frequently Asked Questions (Technical)

This guide addresses common technical questions and design decisions for developers and architects working with the Teams MCP Connector.

## Architecture & Design

### Why are Microsoft tokens never sent to clients?

**Answer:** This is a critical security design. Microsoft OAuth tokens (access and refresh) are exchanged entirely on the server and stored encrypted. The server then issues separate opaque JWT tokens to clients for MCP API authentication. This ensures:
- Microsoft tokens never leave the server
- Clients cannot access Microsoft Graph API directly
- All Microsoft API calls are made by the server on behalf of authenticated users

**See also:** [Token Isolation](./token-auth-flows.md#token-isolation)

### Why are MCP tokens hashed but Microsoft tokens encrypted?

**Answer:**
- **MCP tokens:** Opaque JWTs that the server doesn't need to read - hash comparison is sufficient for validation
- **Microsoft tokens:** Must be decrypted to use for Graph API calls - encryption allows retrieval

Hashing reduces attack surface (no decryption key needed for MCP tokens), while encryption enables token retrieval for Microsoft API calls.

**See also:** [Token Security](./security.md#token-security)

### Why use AES-GCM for token encryption?

**Answer:** AES-GCM provides authenticated encryption - both confidentiality and integrity. It prevents tampering with ciphertext and is an industry standard for token encryption.

**See also:** [Microsoft Tokens (Encrypted at Rest)](./security.md#microsoft-tokens-encrypted-at-rest)

### Why refresh tokens rotate?

**Answer:** Refresh token rotation with family-based revocation detects token theft. If a refresh token is reused (indicating possible theft), the entire token family is revoked. This prevents attackers from using stolen tokens while the legitimate client continues working.

**See also:** [Refresh Token Rotation](./security.md#refresh-token-rotation)

### Why use delegated permissions instead of application permissions?

**Answer:** The MCP model requires self-service user connections where each user:
1. Connects their own account
2. Controls what data they share
3. Can disconnect at any time

Application permissions would require tenant administrators to pre-configure access for each user via PowerShell, defeating the self-service model.

**See also:** [Why Delegated (Not Application) Permissions](./permissions.md#why-delegated-not-application-permissions)

### Why can't I use Client Credentials flow?

**Answer:** Client Credentials flow only supports application permissions, which would require tenant admins to create Application Access Policies per user via PowerShell. This is impractical for self-service MCP connections. Delegated permissions require the Authorization Code flow.

**See also:** [Unsupported Authentication Methods](./token-auth-flows.md#unsupported-authentication-methods)

### Why are subscriptions renewed instead of recreated?

**Answer:** Renewal (PATCH) is more efficient than recreation (DELETE + POST). It preserves the subscription ID and reduces API calls. Renewal happens automatically before expiration (default: 3 AM UTC daily) to ensure token validity is checked consistently.

**See also:** [Subscription Lifecycle](./flows.md#subscription-lifecycle)

## Token Management

### What happens if token refresh fails?

**Possible causes:**
- Microsoft refresh token expired (~90 days of inactivity)
- User revoked consent in Microsoft account settings
- Network issues reaching Microsoft token endpoint

**Resolution:** User must reconnect to MCP server to re-authenticate.

**See also:** [Microsoft Token Refresh Failed](./token-auth-flows.md#microsoft-token-refresh-failed)

### What happens if a token family is revoked?

**Answer:** All refresh operations fail for that user. The user must re-authenticate completely. This happens automatically when refresh token reuse is detected (possible token theft).

**See also:** [Token Family Revoked](./token-auth-flows.md#token-family-revoked)

### What happens if the encryption key changes?

**Answer:** All stored Microsoft tokens become unreadable. All users must reconnect to obtain fresh tokens. There is no zero-downtime rotation for the encryption key.

**See also:** [Encryption Key Changed](./token-auth-flows.md#encryption-key-changed)

### Why are access tokens so short-lived (60 seconds)?

**Answer:** Short-lived access tokens reduce the impact of token theft. If an access token is compromised, it expires quickly. Refresh tokens are used to obtain new access tokens without user re-authentication.

**See also:** [MCP OAuth (Internal)](./token-auth-flows.md#mcp-oauth-internal)

## Webhooks & Processing

### Why use RabbitMQ for webhook processing?

**Answer:** Microsoft requires webhook responses in < 10 seconds. Transcript processing can take minutes (fetching meeting data, transcript content, recordings, uploading to Unique). RabbitMQ decouples webhook reception (fast 202 response) from processing (asynchronous), ensuring we meet Microsoft's strict timeout requirements.

**See also:** [Why RabbitMQ](./why-rabbitmq.md)

### How does webhook validation work?

**Answer:** When creating a subscription, the server sends `MICROSOFT_WEBHOOK_SECRET` as `clientState` to Microsoft. Microsoft returns this value in every webhook payload. The server validates that the received `clientState` matches the configured secret, rejecting invalid requests.

**See also:** [Webhook Validation](./security.md#webhook-validation)

### What happens if webhook validation fails?

**Answer:** The request is rejected with 401 Unauthorized. Microsoft will retry the notification. If validation consistently fails, Microsoft may stop sending notifications for that subscription.

**See also:** [Webhook Validation](./security.md#webhook-validation)

## Data Model

### Why track token families?

**Answer:** Token family tracking enables theft detection. Each OAuth session has a `token_family` identifier. If a refresh token is reused (indicating possible theft), the entire family is revoked. This prevents attackers from using stolen tokens while the legitimate client continues working.

**See also:** [Token Family Tracking](./architecture.md#key-design-decisions)

### Why store MCP tokens as hashes?

**Answer:** MCP tokens are opaque JWTs - the server doesn't need to read them, only validate them. Hash comparison is sufficient for validation and reduces attack surface (no decryption key needed).

**See also:** [MCP Tokens (Hashed for Validation)](./security.md#mcp-tokens-hashed-for-validation)

### Why encrypt Microsoft tokens instead of hashing?

**Answer:** Microsoft tokens must be decrypted to use for Graph API calls. Encryption allows retrieval, while hashing is one-way and would prevent token usage.

**See also:** [Microsoft Tokens (Encrypted at Rest)](./security.md#microsoft-tokens-encrypted-at-rest)

## Security

### Why use PKCE?

**Answer:** PKCE (Proof Key for Code Exchange) prevents authorization code interception attacks. It's required for all OAuth flows in OAuth 2.1 and uses `S256` challenge method (SHA-256).

**See also:** [OAuth 2.1 with PKCE](./security.md#oauth-21-with-pkce)

### Why separate MCP tokens from Microsoft tokens?

**Answer:** This design ensures:
- Microsoft tokens never leave the server
- Clients cannot access Microsoft Graph API directly
- All Microsoft API calls are made by the server on behalf of authenticated users
- Client tokens are opaque JWTs that only authenticate with the MCP server

**See also:** [Token Isolation](./token-auth-flows.md#token-isolation)

### What's the threat model?

**Answer:** The security architecture protects against:
- Token theft (refresh token rotation, family-based revocation)
- Authorization code interception (PKCE)
- Webhook spoofing (clientState validation)
- Token tampering (AES-GCM authenticated encryption)

**See also:** [Security](./security.md)

## Microsoft Graph Integration

### Why can't I use certificate authentication?

**Answer:** Certificate authentication only works with Client Credentials flow, which requires application permissions. Teams MCP uses delegated permissions (user-specific access), which require the Authorization Code flow with a client secret.

**See also:** [Unsupported Authentication Methods](./token-auth-flows.md#unsupported-authentication-methods)

### Why single app registration architecture?

**Answer:** Each MCP deployment uses one Microsoft Entra ID app registration that can serve users from multiple Microsoft tenants. When tenant admins grant consent, Microsoft creates Enterprise Applications in their tenants. This is simpler than managing multiple app registrations.

**See also:** [Single App Registration Architecture](./token-auth-flows.md#single-app-registration-architecture)

### How does multi-tenant authentication work?

**Answer:**
1. App registration configured as multi-tenant ("Accounts in any organizational directory")
2. Tenant admin grants consent → Microsoft creates Enterprise Application in their tenant
3. Users authenticate via Enterprise Application in their tenant
4. One MCP deployment serves all tenants

**See also:** [Single App Registration Architecture](./token-auth-flows.md#single-app-registration-architecture)

## Related Documentation

- [Architecture](./architecture.md) - System components and infrastructure
- [Security](./security.md) - Encryption, authentication, and threat model
- [Token and Authentication](./token-auth-flows.md) - Token types, validation, refresh flows
- [Flows](./flows.md) - User connection, subscription lifecycle, transcript processing
- [Permissions](./permissions.md) - Required scopes and least-privilege justification
- [Why RabbitMQ](./why-rabbitmq.md) - Message queue rationale
- [Operator FAQ](../operator/faq.md) - Common operator questions
