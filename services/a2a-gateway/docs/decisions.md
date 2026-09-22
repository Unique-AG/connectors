# Decisions

Status: **proposed** unless marked *agreed* (agreed = from the Linear project brief).

| # | Decision | Rationale | Status |
| --- | --- | --- | --- |
| D-01 | Service lives in `connectors/services/a2a-gateway`, TypeScript + NestJS, drizzle + PostgreSQL, Helm chart, same shared packages as `teams-mcp` (`logger`, `probe`, `instrumentation`, `aes-gcm-encryption`, `utils`). | Official JS SDK is v1.0-stable on Express; richest shared tooling in this repo is TS; connectors conventions apply. | proposed |
| D-02 | `@a2a-js/sdk` 1.2.x, JSON-RPC binding only, protocol 1.0 only, no 0.3 compat. | Project brief; LangSmith speaks 1.0 JSON-RPC. | *agreed* (version pin proposed) |
| D-03 | Gateway calls core internal services (`node-chat`, `node-scope-management`, `node-ingestion`) with `x-user-id`/`x-company-id`, never the public Unique API and never `x-service-id` on user-bound calls. | Identical to how `unique-api` preserves identity; core resolves roles and enforces object-level authz. | *agreed* |
| D-04 | Inbound auth: gateway verifies Zitadel JWTs itself (JWKS via `jose`, `iss`, project audience, `exp`), classifies principal as human, rejects machine users. | Optional service must be self-contained; Kong route optional later. | proposed — **Q3** |
| D-05 | `contextId` = one chat, `taskId` = one user message/turn, follow-ups to `INPUT_REQUIRED`/`AUTH_REQUIRED` map to `elicitationRespond`, follow-ups to terminal tasks are new tasks. | Matches Unique's chat/turn/elicitation model 1:1; no synthetic state. | proposed |
| D-06 | One non-terminal task per context; concurrent send → `-32602` `CONTEXT_BUSY`. | A Unique chat processes one turn at a time; queueing hides latency and complicates cancel. | proposed — **Q5** |
| D-07 | Inbound run events: MVP uses `POST /space-message-events/stream` (SSE) for live `SendStreamingMessage`, and message polling for `GetTask`/`SubscribeToTask`/recovery. KRA-21 records the gap and asks core for a stable, re-attachable run-event contract (or direct event-bus subscription). | The existing endpoint is experimental (feature flag, in-process tap, 1 h cap, no re-attach) but is the only streaming contract today. | proposed — **Q1** |
| D-08 | Outbound `INPUT_REQUIRED`/`AUTH_REQUIRED` become Unique elicitations created by the gateway; the answer reaches the gateway by polling `elicitationGetById` (MVP), later via a core → gateway callback. | No core change for MVP; callback is a narrow later addition. | proposed — **Q4** |
| D-09 | Remote responses parsed leniently (tolerate missing `ErrorInfo`, `+00:00` timestamps); if a peer's SSE is not v1.0-shaped, connection test marks `streaming=false` and we poll. No 0.3 shape translation layer. | Keeps "no 0.3" while still working with LangSmith. | proposed — **Q9** |
| D-10 | Management API is called by the Unique frontend directly through Kong; gateway checks space-manage access against core per write. Core proxies nothing except capability/routing. | Keeps core integration narrow (project brief). | proposed — **Q2** |
| D-11 | Publication disable/delete: running tasks finish, new sends rejected, card returns 404; space deletion in core → reconcile disables publication and keeps tasks until retention. Connection delete blocked while spaces reference it. | Predictable for clients, no data loss, no dangling execution. | proposed — **Q6** |
| D-12 | Worker = pg-boss inside the same image, enabled via `WORKER_ENABLED`; API and worker can be split into two Deployments in Helm without code changes. | One dependency (Postgres), minimal ops surface, durable retries. | proposed — **Q7** |
| D-13 | Files: inbound bytes only (≤ 10 MB default) uploaded to the chat; outbound artifacts exposed via authenticated gateway download URL; remote files fetched through the egress guard. | Avoids exposing Unique storage URLs; bounded resource use. | proposed — **Q10** |
| D-14 | `data` parts: inbound forwarded to the space as fenced JSON in the user text (except elicitation answers); outbound remote `data` rendered as fenced JSON in the assistant message; references emitted as a `data` artifact with `metadata.kind = "unique.references"`. | Native spaces have no structured-input channel; honest, lossless. | proposed — **Q8** |
| D-15 | Public agent card is unauthenticated but minimal; catalog and extended card require Bearer; `publicationId` is a random opaque id. | Discovery must work for OAuth bootstrap; nothing sensitive before authz (KRA-22). | proposed — **Q11** |
| D-16 | Multi-tenant capable (all rows `company_id`), but a deployment is expected to serve one Unique installation; Zitadel issuer/project configured per deployment. | Matches other connectors; cheap to keep tenant column. | proposed — **Q13** |

## Open questions (need your answer before KRA-19/20/21)

- **Q1 (D-07)** Run events: OK to build the MVP on the experimental `/space-message-events/stream` (needs the flag on for the tenant) + polling, and file the stable contract request in KRA-21? Or should the gateway subscribe to the platform RabbitMQ event bus (`unique.chat.assistant-message.*`) directly — is broker access acceptable for a connectors service?
- **Q2 (D-10)** Management surface: frontend → gateway via Kong directly (needs a Kong route + CORS), or core proxies publication/connection settings?
- **Q3 (D-04)** Inbound OAuth: gateway validates Zitadel JWTs itself, or `/a2a` goes behind Kong? How are external A2A clients onboarded as Zitadel OAuth apps (one app per client, manual)? Which claim reliably marks a human vs machine user in your Zitadel setup?
- **Q4 (D-08)** Outbound elicitation answers: polling for MVP acceptable, or should KRA-30 include a core → gateway callback from the start?
- **Q5 (D-06)** Reject concurrent sends per context, or queue them?
- **Q6 (D-11)** On publication disable: let running tasks finish (proposed) or cancel them?
- **Q7 (D-12)** pg-boss in-process worker OK? (Alternative: Temporal — is there a shared Temporal in the target environments?)
- **Q8 (D-14)** Forwarding inbound `data` parts as fenced JSON acceptable, or reject non-text input for native spaces?
- **Q9 (D-09)** If the client's LangSmith SSE is 0.3-shaped, is "no streaming, poll instead" acceptable, or do you want a narrow SSE normaliser (would soften "no 0.3")?
- **Q10 (D-13)** File artifact delivery via gateway download URL fine? Inline bytes limit 10 MB?
- **Q11 (D-15)** Unauthenticated minimal public card OK?
- **Q12 (D-01)** TypeScript/NestJS confirmed (vs Python `a2a-sdk`)?
- **Q13 (D-16)** Single installation per deployment assumption correct?
- **Q14** Publication URL: opaque random id (proposed) or an admin-editable slug?
- **Q15** Should inbound calls be attributed/quoted per *external OAuth client* (Zitadel `azp`/`client_id`) in addition to per user? Affects `tasks` columns.
