# Decisions

*agreed* = confirmed by product/architecture owner; *proposed* = open for review.

| # | Decision | Rationale | Status |
| --- | --- | --- | --- |
| D-01 | `connectors/services/a2a-gateway`, **TypeScript, NestJS 12.0.4, ESM only**, drizzle + PostgreSQL, Helm chart. Shared connectors packages reused where their peer ranges allow (`logger`, `probe`, `instrumentation`, `aes-gcm-encryption`, `utils`). | Official JS SDK is v1.0-stable; repo conventions. Nest 12/ESM is a first in this repo → prerequisite P-01. | *agreed* |
| D-02 | `@a2a-js/sdk` 1.2.x, JSON-RPC binding only, protocol **1.0 only**, no 0.3 compat, no peer-specific workarounds. | Project brief. Peer limitations are recorded per connection when real peers are onboarded (KRA-44), not designed for up front. | *agreed* |
| D-03 | Gateway calls core internal services (`node-chat`, `node-scope-management`, `node-ingestion`) with `x-user-id`/`x-company-id`; never the public Unique API; never `x-service-id` on user-bound calls. | Same identity-preserving path `unique-api` uses; core resolves roles and enforces object-level authz. | *agreed* |
| D-04 | **All JWT-authenticated surfaces sit behind Kong.** Kong validates the Zitadel token and stamps `x-user-id`, `x-company-id`, `x-user-roles`; the gateway never validates JWTs itself and never accepts identity headers from outside Kong/cluster. Only the public agent card is served without auth. `AUTH_MODE=development` disables the header requirement locally. | Platform rule: JWT-authenticated endpoints are never exposed directly. | *agreed* |
| D-05 | `contextId` = one chat, `taskId` = one user message/turn; follow-ups on `INPUT_REQUIRED`/`AUTH_REQUIRED` → `elicitationRespond`; follow-ups on terminal tasks → new task. | 1:1 with Unique's chat/turn/elicitation model. | proposed |
| D-06 | One non-terminal task per context; concurrent send → `-32602` `CONTEXT_BUSY`. | A chat processes one turn at a time; queueing hides latency and complicates cancel. | proposed — **Q5** |
| D-07 | Run events: the gateway **subscribes to the platform RabbitMQ event bus** (topic exchange `EVENT_BUS`, routing keys `unique.chat.assistant-message.*`, `unique.chat.user-message.created`) and matches events to tasks/executions by `chatId`/`messageId`. `GetTask` re-derives state from core on cache miss. No use of the experimental `/space-message-events/stream`. | Re-attachable, replica-independent, no in-process tap limitation. | *agreed* |
| D-08 | Outbound `INPUT_REQUIRED`/`AUTH_REQUIRED` → gateway creates a Unique elicitation; the answer arrives via **core → gateway callback** `POST /internal/executions/{id}/elicitation-response` (KRA-30 includes the hook). For inbound tasks the gateway needs to learn about pending elicitations too → core publishes `unique.chat.elicitation.{created,responded,expired}` on the event bus (P-03). | Elicitation events are in-process in node-chat today; both directions need them. | *agreed* (callback) / proposed (bus events) |
| D-09 | Strict v1.0 parsing on both sides. Peers that are not 1.0-compliant fail at connection test with a clear reason. | Focus on 1.0. | *agreed* |
| D-10 | Management surface is called by the Unique frontend directly (via Kong); gateway checks space-manage access against core per write; core proxies nothing. | Narrow core integration. | *agreed* |
| D-11 | Publication disable/delete: running tasks finish, new sends rejected, card 404; core space deletion → reconcile disables publication, tasks kept until retention; connection delete blocked while referenced. | Predictable, no data loss. | proposed — **Q6** |
| D-12 | Durable execution with **absurd** (`absurd-sdk`, Postgres-only, same database) instead of pg-boss; see comparison below. Encapsulated in one `WorkflowModule` so a swap stays local. `WORKER_ENABLED` toggles the worker in a replica. | Outbound execution is a workflow (send → stream/poll → await elicitation answer → finalize), not a queue job; `awaitEvent` matches D-08's callback; habitat UI for operators. | proposed — **Q7** (your call) |
| D-13 | Files: inbound bytes only (≤ 10 MB default) uploaded to the chat; outbound artifacts via Kong-fronted gateway download URL; remote files fetched through the egress guard. | Bounded resources, no Unique storage URLs exposed. | proposed — **Q10** |
| D-14 | `data` parts: inbound forwarded as fenced JSON in the user text (except elicitation answers); outbound remote `data` rendered as fenced JSON; references emitted as a `data` artifact `metadata.kind = "unique.references"`. | Native spaces have no structured-input channel. | proposed — **Q8** |
| D-15 | Public agent card unauthenticated (Kong route without JWT plugin) but minimal; catalog, extended card and RPC behind Kong JWT; `publicationId` is a **typeid** (`pub_…`). | Discovery must work before auth; nothing sensitive before authz. | proposed — **Q11** |
| D-16 | All ids are **typeid** (`typeid-js`, already in the catalog): `pub_`, `conn_`, `ctx_`, `task_`, `art_`, `exec_`, `pnc_`. A2A `contextId`/`taskId` are the typeids verbatim (spec treats ids as opaque, server-generated; UUIDs are only examples). | Sortable, prefixed, self-describing. | *agreed* |
| D-17 | Multi-tenant capable (`company_id` everywhere) but one deployment per Unique installation. | Matches other connectors. | proposed — **Q13** |

## pg-boss vs absurd (D-12)

| | pg-boss 12.x | absurd (`absurd-sdk` 0.5.0) |
| --- | --- | --- |
| Model | job queue: retries/backoff, cron, singleton, deferral, dead-letter | durable execution: tasks → steps with checkpoints, `sleep`, `awaitEvent`, retries of the whole task, spawn/await child tasks |
| Runtime deps | Postgres, own schema via SDK migrations | Postgres, one `absurd.sql` (+ released migrations) → we apply it via drizzle migrations |
| UI | none built-in | habitat (Go binary) |
| Maturity | ~9 years, MIT, wide use | first release Nov 2025, Apache-2.0, small team, TS SDK ESM |
| Fit for `outbound.poll` | loop job that re-enqueues itself; state in our tables | one task: `step(send)` → `step(poll)`/`sleep` loop → `awaitEvent(elicitation.answered:<exec>)` → `step(finalize)`; checkpoints survive restarts |
| Fit for `push.deliver` | native retries/backoff | task retry; backoff policy to verify |
| Fit for cron (reconcile, retention) | native | documented pattern (task that sleeps and re-spawns) |
| Risks | writing our own workflow state machine on top of a queue | young project; verify in a KRA-19 spike: cancellation API, `awaitEvent` timeout/deadline, per-worker concurrency, retry policy config, Nest 12/ESM integration |

**Preference: absurd**, because the outbound run and the inbound task are workflows with suspension points (elicitation answers, remote stream completion) and absurd's `awaitEvent` is exactly the callback in D-08; the UI is a real operator benefit; you have production experience with it. Conditions: spike in KRA-19 confirms the four verification points above, version pinned, schema applied through our migrations, SDK isolated in `WorkflowModule`. If the spike fails on cancellation or deadlines, fall back to pg-boss with our own state machine.

## Prerequisites outside this service

- **P-01** Shared connectors packages must accept NestJS 12: bump `peerDependencies` to `^11 || ^12` in `logger`, `probe`, `aes-gcm-encryption` (and confirm single `@nestjs/common` instance under pnpm). `@golevelup/nestjs-rabbitmq` 9.x also peers Nest 11 → use `amqplib` + `amqp-connection-manager` directly (what core's `@unique/amqp` does) unless a Nest-12 release exists by then.
- **P-02** Kong: routes for `/a2a/agents/*/.well-known/agent-card.json` (no auth), `/a2a/*` and `/management/*` (JWT → identity headers, strip inbound `x-user-*`), CORS for the frontend origin. NetworkPolicy: `/internal/*` reachable from `node-chat` only.
- **P-03** Core (KRA-21 gap list): publish elicitation lifecycle events on the event bus; `executionProvider = A2A` dispatch + cancel + elicitation-response callback to the gateway (KRA-30); `a2aCapabilities` query (KRA-25).
- **P-04** RabbitMQ credentials for the gateway with permissions to declare its own queues bound to `EVENT_BUS` (read-only on the exchange).

## Open questions

- **Q5 (D-06)** Reject concurrent sends per context, or queue them?
- **Q6 (D-11)** On publication disable: let running tasks finish (proposed) or cancel them?
- **Q7 (D-12)** absurd (preferred, with spike) or pg-boss?
- **Q8 (D-14)** Forward inbound `data` parts as fenced JSON, or reject non-text input for native spaces?
- **Q10 (D-13)** Artifact files via gateway download URL fine? 10 MB inline limit?
- **Q11 (D-15)** Unauthenticated minimal public card OK?
- **Q13 (D-17)** One installation per deployment assumption correct?
- **Q14** Publication URL segment: typeid (proposed) or admin-editable slug?
- **Q15** Attribute/quota inbound calls per external OAuth client (`azp`) in addition to per user? Requires Kong to forward the claim (e.g. `x-client-id`).
- **Q16** Human vs machine principal (KRA-22): can Kong expose the Zitadel user type, or should the gateway verify the user via scope-management (`users` query) on first contact?
