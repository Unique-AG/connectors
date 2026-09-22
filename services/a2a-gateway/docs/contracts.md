# Contracts

Three gateway surfaces, one set of core operations the gateway consumes, and one capability contract core adds.

## 1. Public A2A surface (`/a2a`)

All rows except the public card are behind Kong (JWT → `x-user-id`, `x-company-id`, `x-user-roles`). Clients still send `Authorization: Bearer <Zitadel token>`; the gateway only sees the headers.

| Path | Auth | Purpose |
| --- | --- | --- |
| `GET /a2a/agents` | Kong JWT | Unique-specific catalog: published spaces the caller may **use** (checked live against core). Returns `{ agents: [{ publicationId, name, description, cardUrl }] }`. |
| `GET /a2a/agents/{publicationId}/.well-known/agent-card.json` | none | Public Agent Card. Contains only Space-Admin-approved fields (name, description, skills, modes, security schemes, `supportedInterfaces`). Fields hidden by the admin are omitted. |
| `POST /a2a/agents/{publicationId}` | Kong JWT | JSON-RPC 2.0 endpoint, `A2A-Version: 1.0`. |
| `GET /a2a/agents/{publicationId}/files/{artifactFileId}` | Kong JWT | Download of a file artifact produced by the space. Authorised like `GetTask` on the owning task. |

Supported JSON-RPC methods (v1.0 names only, see [compatibility-profile](./compatibility-profile.md)):
`SendMessage`, `SendStreamingMessage` (SSE), `GetTask`, `ListTasks`, `CancelTask`, `SubscribeToTask` (SSE), `CreateTaskPushNotificationConfig`, `GetTaskPushNotificationConfig`, `ListTaskPushNotificationConfigs`, `DeleteTaskPushNotificationConfig`, `GetExtendedAgentCard`.

Mapping:

| A2A | Unique |
| --- | --- |
| `contextId` | one Unique `chatId` in the published space, owned by the caller's user (created on first message) |
| `taskId` | one user message + its assistant turn (`userMessageId`) |
| `Message` (ROLE_USER) with new `contextId`/no `taskId` | `messageCreate` in that chat |
| `Message` with `taskId` of a task in `INPUT_REQUIRED`/`AUTH_REQUIRED` | `elicitationRespond` (never a new run) |
| `Message` with `taskId` of a task in a terminal state | error `-32602` — "task is terminal, send a new message in the same context" |
| `TASK_STATE_WORKING` | assistant message streaming |
| `TASK_STATE_INPUT_REQUIRED` | pending `Elicitation` mode `FORM` (schema in status message `data` part) |
| `TASK_STATE_AUTH_REQUIRED` | pending `Elicitation` mode `URL` (url in status message) |
| `TASK_STATE_COMPLETED` | assistant turn `completedAt`/`stoppedStreamingAt` set |
| `TASK_STATE_CANCELED` | `messageStopStreaming` succeeded |
| `TASK_STATE_FAILED` | run error, elicitation declined/expired |
| final `Artifact` | assistant text (`text`), references (`data`, `metadata.kind = "unique.references"`), generated chat files (`file` with gateway download URI) |

Concurrency: one active task per `contextId`. A `SendMessage` while a task is active returns `-32602` with `ErrorInfo.reason = CONTEXT_BUSY`.

Never exposed: internal tool traces, prompts, `debugInfo`, model names, assistant ids, other users' tasks.

## 2. Management surface (`/management`)

Caller: Unique frontend directly (not via core) through Kong (JWT → identity headers). The gateway authorises object-level access **against core** (assistant manage access) before every write.

| Method | Path | Rule |
| --- | --- | --- |
| `GET` | `/management/publications?assistantId=` | caller has read access to the space |
| `PUT` | `/management/publications/{assistantId}` | caller manages the space; space is native (`executionProvider != A2A`); body: `enabled`, `card` (allowed fields), `skills` |
| `DELETE` | `/management/publications/{assistantId}` | same; running tasks finish, new sends rejected |
| `GET/POST/PUT/DELETE` | `/management/connections[/{id}]` | roles `ADMIN_SPACE_WRITE` or `SPACE_MANAGER`; credentials write-only (never returned) |
| `POST` | `/management/connections/{id}/test` | fetch + validate remote Agent Card, store negotiated capabilities, return supported interaction matrix |

All writes are idempotent (`If-Match` on `version`).

## 3. Internal surface (`/internal`) — core → gateway

Cluster-local only. Caller: `node-chat` with effective-user headers (`x-user-id`, `x-company-id`, `x-user-roles`). No service identity fallback.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/internal/capabilities` | `{ version, protocolVersions: ["1.0"], features: {...} }` — used by core to decide whether A2A UI/API is available |
| `POST` | `/internal/executions` | Start outbound run: `{ connectionId, chatId, userMessageId, assistantMessageId, assistantId, parts }`. Returns `{ executionId }` immediately; gateway streams results back into the chat. |
| `POST` | `/internal/executions/{executionId}/cancel` | User stopped the message in Unique → `CancelTask` on the remote |
| `POST` | `/internal/executions/{executionId}/elicitation-response` | Core-side elicitation answered/declined/expired → `{ elicitationId, action, content? }`; gateway emits the workflow event, the suspended run continues with a follow-up message carrying the remote `taskId` (D-08) |
| `GET` | `/internal/connections/{connectionId}` | Redacted connection summary + negotiated capabilities for the space settings UI |
| `POST` | `/internal/publications/reconcile` | Core notifies space deletion/type change; gateway disables the publication |

## 4. Core operations the gateway consumes (identity-preserving client, KRA-21)

All calls carry `x-user-id` + `x-company-id` (roles resolved by the target's `AccessControlGuard`). No `x-service-id` on user-bound calls.

| Need | Existing operation (node-chat unless noted) | Status |
| --- | --- | --- |
| Space lookup, use/manage access | GraphQL `assistants`/`assistantByUser`, `spaceManagerVerify` (scope-management) | exists |
| Create chat / message | GraphQL `messageCreate` (as in `SpaceMessageCreate`) with `correlation` for sub-agent calls | exists |
| Run events | RabbitMQ `EVENT_BUS` (topic): `unique.chat.assistant-message.{created,update,stream.chunk,finished}`, `unique.chat.user-message.created` | exists (D-07); gateway declares its own queue |
| Elicitation events | — (node-chat emits them in-process only) | **gap**: publish `unique.chat.elicitation.{created,responded,expired}` on `EVENT_BUS` (P-03) |
| Poll run state (cache miss / recovery) | GraphQL `messages`/`message` (`stoppedStreamingAt`, `completedAt`, segments) | exists |
| Cancel | GraphQL `messageStopStreaming` | exists |
| Elicitation read/respond | GraphQL `elicitationGetPending`, `elicitationGetById`, `elicitationRespond` | exists |
| Elicitation create (outbound `input-required`) | GraphQL `elicitationCreate` | exists |
| Write assistant message (outbound results) | GraphQL `messagePublicUpdate` / message stream chunk path used by external modules | exists (verify streaming path) |
| Chat file upload / download | `contentUpsertByChat` + ingestion upload (node-ingestion), content download URL | exists |
| Outbound execution hook | — | **gap**: core must dispatch `executionProvider = A2A` spaces to `/internal/executions`, forward stop → `/cancel`, and elicitation outcome → `/elicitation-response` (KRA-30) |

## 5. Core capability contract (KRA-25, KRA-30)

Core adds:

- `A2A_GATEWAY_URL` (node-chat env) + `FEATURE_FLAG_ENABLE_A2A_<ticket>` + company entitlement.
- `Assistant.executionProvider: NATIVE | A2A` and `Assistant.a2aConnectionId` (reference only).
- GraphQL `a2aCapabilities(companyId)` → `{ available, reason?: NOT_DEPLOYED | UNREACHABLE | DISABLED | NOT_ENTITLED }` for the frontend; evaluates flag/entitlement and probes `/internal/capabilities` (short TTL cache, outage ≠ deletion).
- Server-side gate on publish/configure/invoke for both direct chat and sub-agent execution.
