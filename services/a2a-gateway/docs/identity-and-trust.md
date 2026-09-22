# Identity and trust

Rule: **the gateway never validates JWTs**. Every JWT-authenticated surface is reached through Kong, which validates the Zitadel token and stamps `x-user-id`, `x-company-id`, `x-user-roles`. `AUTH_MODE=development` allows unauthenticated local requests; in any other mode a request without identity headers is rejected.

## Inbound: external client → published space

```mermaid
%%{init: {'theme': 'neutral'}}%%
sequenceDiagram
    autonumber
    actor Human
    participant Agent as External A2A client
    participant Zitadel
    participant Kong
    participant GW as a2a-gateway
    participant Chat as node-chat

    Human->>Agent: use agent
    Agent->>Zitadel: authorization code + PKCE (Unique project)
    Zitadel-->>Agent: access token (human user)
    Agent->>Kong: POST /a2a/agents/{pub} · Bearer token · A2A-Version 1.0
    Kong->>Kong: validate JWT, strip inbound x-user-*, stamp identity headers
    Kong->>GW: request · x-user-id, x-company-id, x-user-roles
    GW->>GW: KongIdentityGuard: headers present; principal classification (Q16)
    GW->>Chat: space use access(assistantId) · x-user-id, x-company-id
    Chat-->>GW: allowed / denied
    GW->>Chat: messageCreate … x-user-id, x-company-id
```

- Principal = the human Kong identified. Never taken from the request body, A2A metadata or query parameters.
- Machine/service principals must be rejected (KRA-22 / Q16: Kong-forwarded user type, or a one-time user lookup via scope-management).
- A valid token is required per **request** (`SendMessage`, `GetTask`, SSE open). A running task continues when the token expires because core calls use the header identity. Reconnect requires a fresh token for the **same user**.
- Roles are forwarded as stamped by Kong; for calls where the gateway omits them, `node-chat`'s guard resolves roles from scope-management (same path `unique-api` uses).
- Push-notification webhooks: outbound only, credentials from `TaskPushNotificationConfig.authentication`, URL passes egress policy, payload = task id + state (no content).

## Outbound: Unique user → remote agent

```mermaid
%%{init: {'theme': 'neutral'}}%%
sequenceDiagram
    autonumber
    actor User
    participant Chat as node-chat
    participant GW as a2a-gateway
    participant Remote as Remote A2A agent

    User->>Chat: message in A2A External Agent space
    Chat->>Chat: core authz (space use access, entitlement, feature flag)
    Chat->>GW: POST /internal/executions · x-user-id, x-company-id, x-user-roles
    GW->>GW: ClusterIdentityGuard; verify executionProvider = A2A via core; load connection (companyId scoped)
    GW->>Remote: SendStreamingMessage · shared connection credential
    Remote-->>GW: task events
    GW->>Chat: message update / stream chunks · x-user-id, x-company-id
```

- Shared connection credentials (per connection, per company): `none | bearer | api_key | oauth2_client_credentials`. Encrypted at rest with `@unique-ag/aes-gcm-encryption`; never returned by any API; never logged.
- The remote agent sees **no** Unique user identity (no per-user OAuth in this delivery). Attribution stays in the gateway (`executions.user_id`).
- Sub-agent calls arrive as ordinary messages with `correlation` — same path, same authz, correlation stored on the execution.

## Trust boundaries

| Boundary | Trust | Control |
| --- | --- | --- |
| Internet → Kong → `/a2a` | Kong-stamped identity | headers required; rate limits + body size limit (Kong and gateway); JSON-RPC schema validation (SDK); per-tenant quotas |
| Internet → Kong → `/a2a/.../agent-card.json` | unauthenticated | only admin-approved fields; no ids beyond `publicationId`; cache headers |
| Internet → Kong → `/management` | Kong-stamped identity | object-level check against core for every write; role check for connections |
| `node-chat` → `/internal` | trusted network (NetworkPolicy) | headers accepted only from cluster; no fallback identity; deny if `x-user-id`/`x-company-id` missing |
| RabbitMQ → gateway | trusted platform bus | read-only binding on `EVENT_BUS`; events used to update state, never as an identity source; every event re-checked against `company_id` of the mapped task |
| gateway → core | trusted internal caller like `unique-api` | forwards effective identity only; never `x-service-id` for user-bound calls; NetworkPolicy allow-list |
| gateway → remote agent | untrusted peer | HTTPS only, cert validation, host allow-list or private-range/metadata block, no blind redirects, timeouts, size caps, parts validated against declared modes |
| remote agent → Unique | untrusted content | text/data/files treated as data; files size/type validated before upload; no HTML rendering |
| gateway DB | tenant data | every row carries `company_id`; every query filters on it; task visibility `(company_id, user_id)` |

Threats explicitly covered:

- **Identity confusion**: identity comes only from Kong/cluster headers; `x-user-*` from the internet is stripped by Kong; the gateway rejects requests on `/a2a`/`/management` that did not pass Kong (dedicated Kong→gateway network path, optional shared header secret).
- **Cross-tenant task access**: `GetTask`/`ListTasks`/`SubscribeToTask` scoped by `(company_id, user_id)`; unknown = `TASK_NOT_FOUND`, never `FORBIDDEN`.
- **Stale catalog**: catalog cached, every invocation re-checks space access and publication state.
- **Republication**: DB constraint + core check prevent publishing a space with `executionProvider = A2A`.
- **Credential exfiltration**: credentials write-only, encrypted, redacted in logs and errors; connection test never echoes secrets.
- **SSRF via connection URL / push URL / file URI**: shared egress guard (SECURITY-RULES §3).
- **Silent approval**: elicitations are never auto-approved; `autoApproveElicitation` is never set.
- **Content in logs**: ids and states only (SECURITY-RULES §6).
