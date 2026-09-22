# Decisions

*agreed* = confirmed by product/architecture owner; *proposed* = open for review.

| # | Decision | Rationale | Status |
| --- | --- | --- | --- |
| D-01 | `connectors/services/a2a-gateway`, **TypeScript, NestJS 12.0.4, ESM only**, drizzle + PostgreSQL, Helm chart. Shared connectors packages `logger`, `probe`, `aes-gcm-encryption` are **upgraded to Nest 12** (P-01) and reused, plus `instrumentation`, `utils`. RabbitMQ via `@golevelup/nestjs-rabbitmq` (pnpm peer override until [golevelup/nestjs#1259](https://github.com/golevelup/nestjs/issues/1259) ships Nest 12 peers). | Official JS SDK is v1.0-stable; repo conventions; no hand-rolled AMQP. | *agreed* |
| D-02 | `@a2a-js/sdk` 1.2.x, JSON-RPC binding only, protocol **1.0 only**, no 0.3 compat, no peer-specific workarounds. | Project brief. Peer limitations are recorded per connection when real peers are onboarded (KRA-44). | *agreed* |
| D-03 | Gateway calls core internal services (`node-chat`, `node-scope-management`, `node-ingestion`) with `x-user-id`/`x-company-id`; never the public Unique API; never `x-service-id` on user-bound calls. | Same identity-preserving path `unique-api` uses. | *agreed* |
| D-04 | **All JWT-authenticated surfaces sit behind Kong.** Kong validates the Zitadel token and stamps `x-user-id`, `x-company-id`, `x-user-roles`, and forwards the OAuth client (`azp`) as `x-client-id`; the gateway never validates JWTs. Only the public agent card is served without auth. `AUTH_MODE=development` disables the header requirement locally. | Platform rule. | *agreed* |
| D-05 | `contextId` = one chat, `taskId` = one user message/turn; follow-ups on `INPUT_REQUIRED`/`AUTH_REQUIRED` → `elicitationRespond`; follow-ups on terminal tasks → new task. | 1:1 with Unique's chat/turn/elicitation model. | *agreed* |
| D-06 | One non-terminal task per context; concurrent send → `-32602` `CONTEXT_BUSY`. No queueing. | A chat processes one turn at a time. | *agreed* |
| D-07 | Run events: gateway **subscribes to the platform RabbitMQ event bus** (topic exchange `EVENT_BUS`, routing keys `unique.chat.assistant-message.*`, `unique.chat.user-message.created`, `unique.chat.elicitation.*`) with a per-replica queue; matches events by `chatId`/`messageId`; re-derives state from core on cache miss. | Re-attachable, replica-independent. | *agreed* |
| D-08 | Outbound `INPUT_REQUIRED`/`AUTH_REQUIRED` → gateway creates a Unique elicitation; the answer arrives via **core → gateway callback** `POST /internal/executions/{id}/elicitation-response` (KRA-30). Inbound detection via elicitation events on the bus (P-03). | Elicitation events are in-process in node-chat today. | *agreed* |
| D-09 | Strict v1.0 parsing on both sides; non-compliant peers fail at connection test with a clear reason. | Focus on 1.0. | *agreed* |
| D-10 | Management surface is called by the Unique frontend directly (via Kong); gateway checks space-manage access against core per write; core proxies nothing. | Narrow core integration. | *agreed* |
| D-11 | Publication disable/delete: **running tasks finish**, new sends rejected, card 404; core space deletion → reconcile disables publication, tasks kept until retention; connection delete blocked while referenced. | Predictable, no data loss. | *agreed* |
| D-12 | Durable execution with **absurd** (`absurd-sdk`, Postgres-only, same database). No pg-boss, not as fallback. Encapsulated in `WorkflowModule`; `WORKER_ENABLED` toggles the worker per replica. Gaps found in the KRA-19 spike (cancellation, `awaitEvent` deadlines, concurrency, retry policy) are solved with absurd primitives (`sleep` + event race, per-task deadline task) or upstream contributions. | Outbound run is a workflow with suspension points; `awaitEvent` = D-08 callback; habitat UI. | *agreed* |
| D-13 | Files: inbound bytes uploaded to the chat (no gateway-imposed size limit beyond Kong/body limits and core ingestion limits); outbound artifacts via Kong-fronted gateway download URL; remote files fetched through the egress guard. | Simple; limits live where they already exist. | *agreed* |
| D-14 | `data` parts: inbound forwarded as JSON in the user text (fenced), except elicitation answers; outbound remote `data` rendered as fenced JSON; references emitted as a `data` artifact `metadata.kind = "unique.references"`. | Native spaces have no structured-input channel. | *agreed* |
| D-15 | Public agent card unauthenticated (Kong route without JWT plugin) but minimal; catalog, extended card and RPC behind Kong JWT; `publicationId` typeid is the URL segment (no slugs). | Discovery must work before auth. | *agreed* |
| D-16 | All ids are **typeid** (`typeid-js`): `pub_`, `conn_`, `ctx_`, `task_`, `art_`, `exec_`, `pnc_`, `rctx_`. A2A `contextId`/`taskId` are the typeids verbatim (spec treats ids as opaque, server-generated). | Sortable, prefixed, self-describing. | *agreed* |
| D-17 | Multi-tenant capable (`company_id` everywhere) but one deployment per Unique installation. | Matches other connectors. | *agreed* |
| D-18 | **Existing user OAuth flow.** Clients use Unique's normal Zitadel authorization-code/PKCE login and access tokens. Reuse Kong validation and trusted identity headers; no Zitadel actions, custom principal claims or Lua changes. Machine-to-machine onboarding is out of scope; no separate human/machine token-classification policy is introduced. | KRA-12 clarification. | *agreed* |
| D-19 | **Deployment is entitlement.** No paid-access setting or billing integration. A configured, reachable gateway plus the rollout flag enables new use. Disabling the flag blocks new configuration/runs, retains connections and lets active runs finish with ongoing authorization; read/cancel/revoke remain allowed. | KRA-12 clarification. | *agreed* |

### KRA-19 absurd spike

`absurd-sdk` 0.5.0 covers the four spike questions without custom scheduling code:

- `cancelTask` persists cancellation; running work observes it at the next checkpoint or heartbeat.
- `awaitEvent` has a durable timeout and raises `TimeoutError`; no separate deadline task is needed.
- `startWorker({ concurrency })` bounds parallel work per replica.
- task registrations and spawns expose maximum attempts plus fixed, exponential or disabled retry policies.

The gateway therefore keeps absurd as the only workflow engine. It owns one `a2a-gateway` queue, starts workers only when `WORKER_ENABLED=true`, and closes the worker and shared PostgreSQL pool through Nest lifecycle hooks.

## Prerequisites outside this service

- **P-01** Upgrade `packages/logger`, `packages/probe`, `packages/aes-gcm-encryption` to NestJS 12 peers (`^12`, or `^11 || ^12` while other services stay on 11); verify a single `@nestjs/common` instance under pnpm. Add a pnpm `peerDependencyRules.allowedVersions` entry for `@golevelup/nestjs-rabbitmq`/`nestjs-discovery` → `@nestjs/*@12` until [#1259](https://github.com/golevelup/nestjs/issues/1259) is released; remove afterwards.
- **P-02** Kong: routes for `/a2a/agents/*/.well-known/agent-card.json` (no auth), `/a2a/*` and `/management/*` (JWT → identity headers, forward `azp` as `x-client-id`, strip inbound `x-user-*`/`x-client-id`), CORS for the frontend origin. NetworkPolicy: `/internal/*` reachable from `node-chat` only.
- **P-03** Core (KRA-21 gap list): publish elicitation lifecycle events on the event bus; `executionProvider = A2A` dispatch + cancel + elicitation-response callback (KRA-30); `a2aCapabilities` query (KRA-25).
- **P-04** RabbitMQ user for the gateway with rights to declare its own queues bound to `EVENT_BUS` (read-only on the exchange).

## Open questions

None blocking. Items surfaced during implementation are appended here.
