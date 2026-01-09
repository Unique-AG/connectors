# Frequently Asked Questions (Operator)

## Authentication & Permissions

### Why do I need admin consent?

**Answer:** `OnlineMeetingTranscript.Read.All` and `OnlineMeetingRecording.Read.All` require admin consent because they access sensitive meeting content. This is a Microsoft requirement, not a Teams MCP requirement.

**What to do:**
1. Go to Azure Portal → App Registration → API permissions
2. Click "Grant admin consent for [Your Organization]"
3. Users can then connect and grant their own consent

**See also:** [Understanding Admin Consent](./authentication.md#understanding-microsoft-consent-flows)

### Why do users still need to consent after admin consent?

**Answer:** This is standard Microsoft behavior for delegated permissions. Even after admin consent, each user must individually consent because delegated permissions act on behalf of the signed-in user. This ensures users are aware of what data the app can access.

**This is not a bug** - it's how Microsoft OAuth works for all Microsoft 365 apps.

**See also:** [Understanding Consent Requirements](../technical/permissions.md#understanding-consent-requirements)

### What is the "login flicker" when users reconnect?

**Answer:** After a user has connected once, Microsoft Entra ID uses silent authentication on subsequent connections. The browser quickly redirects through the OAuth flow to validate the existing session, creating a brief "flicker" effect. This is **normal Microsoft OAuth behavior**, not a bug.

**See also:** [User Reconnection Experience](./authentication.md#user-reconnection-experience-the-login-flicker)

### Why can't I use certificate authentication?

**Answer:** Certificate authentication only works with the Client Credentials flow, which requires application permissions. Teams MCP uses delegated permissions (user-specific access), which require the Authorization Code flow with a client secret.

**See also:** [Unsupported Authentication Methods](../technical/token-auth-flows.md#unsupported-authentication-methods)

### Why do I need a client secret?

**Answer:** The client secret proves to Microsoft that your server is the legitimate application (not an imposter). It's used during the OAuth token exchange to securely obtain Microsoft access and refresh tokens.

**Security note:** The client secret is never sent to clients - it's only used server-side during the OAuth flow.

**See also:** [Why Client ID is Required](../technical/token-auth-flows.md#why-client-id-is-required)

### Why can't I use application permissions instead of delegated?

**Answer:** Application permissions would require tenant administrators to create Application Access Policies via PowerShell for each user. This defeats the self-service MCP model where users connect their own accounts without IT involvement.

**See also:** [Why Delegated (Not Application) Permissions](../technical/permissions.md#why-delegated-not-application-permissions)

### What's the difference between delegated and application permissions?

**Answer:**
- **Delegated:** Acts on behalf of the signed-in user, only accesses data that user can access
- **Application:** Acts as the application itself, requires admin-configured policies per user

Teams MCP uses delegated permissions for self-service user connections.

**See also:** [Why Delegated (Not Application) Permissions](../technical/permissions.md#why-delegated-not-application-permissions)

### Why can't I use multiple app registrations?

**Answer:** Each Teams MCP deployment uses one Microsoft Entra ID app registration. The app can be configured as multi-tenant to serve users from multiple organizations, but you don't need separate app registrations per tenant.

**See also:** [Single App Registration Architecture](../technical/token-auth-flows.md#single-app-registration-architecture)

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

**See also:** [Redirect URI Configuration](./authentication.md#redirect-uri-configuration)

### Why do I need a webhook secret?

**Answer:** The `MICROSOFT_WEBHOOK_SECRET` validates that incoming webhook notifications are actually from Microsoft Graph, not from an attacker. It's sent to Microsoft when creating subscriptions and returned in every webhook payload for validation.

**Generate:** `openssl rand -hex 64` (128 characters)

**See also:** [Webhook Secret](./authentication.md#webhook-secret)

### What happens if I change the encryption key?

**Answer:** All stored Microsoft tokens become unreadable. All users must reconnect to the MCP server to re-authenticate. There is no zero-downtime rotation for the encryption key.

**Best practice:** Plan for a maintenance window and notify users before rotating the encryption key.

**See also:** [ENCRYPTION_KEY Rotation](../technical/security.md#rotation-procedures)

### What happens if I change the client secret?

**Answer:** Update the Kubernetes secret and restart the pods. Users don't need to reconnect - the server will use the new secret for token refresh operations.

**Rotation process:**
1. Create new secret in Entra ID
2. Update Kubernetes secret
3. Restart pods
4. Verify authentication works
5. Delete old secret from Entra ID

**See also:** [Client Secret Management](./authentication.md#client-secret-management)

## Subscriptions & Processing

### Why do subscriptions expire?

**Answer:** Microsoft Graph subscriptions expire after a maximum of 3 days. Teams MCP automatically renews subscriptions before they expire (default: 3 AM UTC daily). This ensures token validity is checked consistently.

**See also:** [Subscription Lifecycle](../technical/flows.md#subscription-lifecycle)

### What happens if a subscription renewal fails?

**Answer:** The subscription is deleted and the user must reconnect to the MCP server to re-authenticate. This can happen if:
- Microsoft refresh token expired (~90 days of inactivity)
- User revoked app consent
- Network issues reaching Microsoft

**See also:** [Subscription Lifecycle](../technical/flows.md#subscription-lifecycle)

### Why aren't transcripts appearing in Unique?

**Answer:** Check the following:

1. **User has active subscription** - Verify the user successfully connected and subscription was created
2. **Webhook notifications received** - Check if Microsoft is sending notifications
3. **RabbitMQ queue processing** - Verify messages are being processed
4. **No processing errors** - Check logs for any failures during transcript processing

**See also:** [Transcript Processing Flow](../technical/flows.md#transcript-processing-flow)

### What happens if token refresh fails?

**Answer:** Graph API calls will fail with 401 errors. This typically happens when:
- Microsoft refresh token expired (~90 days of inactivity)
- User revoked app consent
- Client secret was rotated without updating the configuration

**Solution:** User must reconnect to the MCP server to re-authenticate.

## Deployment

### Why do I need RabbitMQ?

**Answer:** Microsoft requires webhook responses in < 10 seconds. RabbitMQ decouples webhook reception (fast response) from transcript processing (slower, can take minutes). This ensures we meet Microsoft's strict timeout requirements.

**See also:** [Why RabbitMQ](../technical/why-rabbitmq.md)

### Can I deploy without RabbitMQ?

**Answer:** No. RabbitMQ is required to meet Microsoft's webhook response time requirements. Without it, webhook processing would timeout and Microsoft would stop sending notifications.

### What happens if the database is full?

**Answer:** Write operations will fail. Solutions:
- Run token cleanup job manually
- Increase database storage
- Archive old data

## Security

### How are Microsoft tokens stored?

**Answer:** Microsoft access and refresh tokens are encrypted at rest using AES-256-GCM and stored in the `user_profiles` table. They are **never sent to clients** - only opaque JWT tokens are issued to clients for MCP authentication.

**See also:** [Token Security](../technical/security.md#token-security)

### What happens if a refresh token is stolen?

**Answer:** If a refresh token is reused (indicating possible theft), the entire token family is revoked. The user must re-authenticate completely. This is detected automatically by the refresh token rotation mechanism.

**See also:** [Refresh Token Rotation](../technical/security.md#refresh-token-rotation)

## Multi-Tenant

### Can one deployment serve multiple Microsoft tenants?

**Answer:** Yes. Configure the app registration with "Accounts in any organizational directory" (multi-tenant). When each organization's admin grants consent, Microsoft creates an Enterprise Application in their tenant. One MCP deployment serves all tenants.

**Considerations:**
- Data isolation: All tenant data stored in same database (with tenant-scoped access controls)
- Enterprise Application management: Each tenant admin controls user assignment
- Compliance: Some organizations may require dedicated infrastructure

**See also:** [Multi-Tenant App Registration](./authentication.md#multi-tenant-app-registration)

## Getting Help

For detailed troubleshooting steps and diagnostic information, see:
- [Architecture](../technical/architecture.md) - System components and infrastructure
- [Token Flows](../technical/token-auth-flows.md) - OAuth token lifecycle
- [Permissions](../technical/permissions.md) - Microsoft Graph permissions
- [Security](../technical/security.md) - Encryption and authentication

## Standard References

- [Microsoft Graph API](https://learn.microsoft.com/en-us/graph/overview) - Graph API overview
- [Microsoft Entra ID Troubleshooting](https://learn.microsoft.com/en-us/entra/identity-platform/troubleshoot-authentication) - Authentication troubleshooting
- [Kubernetes Documentation](https://kubernetes.io/docs/) - Kubernetes official docs
