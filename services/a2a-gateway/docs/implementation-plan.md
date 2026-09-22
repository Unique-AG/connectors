# Implementation plan (KRA-11 groundwork)

## Stack

- NestJS **12.0.4**, `"type": "module"`, `moduleResolution: NodeNext`, `nest build` with SWC; Node 26 (repo default).
- `@a2a-js/sdk` 1.2.x (`server/express` for JSON-RPC handler, `client` for outbound), `drizzle-orm` + `pg`, `absurd-sdk` (D-12), `@golevelup/nestjs-rabbitmq` (peer override, P-01), `typeid-js`, `zod`, `@nestjs/terminus`, `nestjs-pino`, `nestjs-otel`.
- Shared packages: `@unique-ag/{logger,probe,instrumentation,aes-gcm-encryption,utils}` after P-01 upgrades `logger`/`probe`/`aes-gcm-encryption` to Nest 12. They are CJS; importing CJS from ESM is fine, but a **single `@nestjs/common` instance** must be verified.
- Versions pinned exactly (syncpack); Nest 12 lives only in this service — add a syncpack `versionGroup` so the catalog's Nest 11 pin is not enforced here.

## Target layout

```
services/a2a-gateway/
├── deploy/                     # Dockerfile, helm-charts/a2a-gateway (copy pattern from teams-mcp)
├── drizzle/                    # generated migrations (+ absurd.sql / absurd migrations)
├── docs/                       # this design
├── src/
│   ├── main.ts · app.module.ts · instrumentation.ts
│   ├── config/                 # zod configs: app, auth-mode, database, amqp, unique (core URLs), egress, limits, worker
│   ├── drizzle/                # module + schema/{publications,connections,contexts,tasks,artifacts,push-configs,executions,remote-contexts}.table.ts
│   ├── health/                 # terminus: db, amqp, core reachability (readiness)
│   ├── auth/                   # KongIdentityGuard (x-user-id/x-company-id/x-user-roles/x-client-id from Kong), ClusterIdentityGuard (internal), AUTH_MODE=development bypass
│   ├── unique/                 # UniqueInternalClient: spaces, messages, elicitations, content; normalised errors
│   ├── event-bus/              # @golevelup/nestjs-rabbitmq: per-replica queue on EVENT_BUS, typed event parsing, dispatch to task/execution handlers
│   ├── credentials/            # CredentialVault (aes-gcm-encryption), credential types
│   ├── egress/                 # EgressGuard (allow-list, private-range/metadata block, redirects, size, timeout)
│   ├── a2a-server/             # jsonRpcHandler mount, PublicationResolver middleware, PgTaskStore, InboundExecutor, agent-card builder, catalog controller, file download controller
│   ├── outbound/               # OutboundRunner (absurd task), RemoteClientFactory (@a2a-js/sdk Client), connection test/negotiation
│   ├── bridge/                 # ElicitationBridge, ArtifactTranslator (text/data/file both directions)
│   ├── management/             # publications + connections controllers/services
│   ├── internal/               # capabilities, executions (+cancel, +elicitation-response), reconcile controllers
│   └── workflow/               # WorkflowModule: absurd app, task registrations (outbound.run, push.deliver, reconcile, retention), WORKER_ENABLED
├── test/                       # e2e: tck smoke, authz matrix, cross-tenant, event-bus replay
├── package.json · nest-cli.json · drizzle.config.ts · vitest*.config.ts · turbo.json · tsconfig*.json
```

## Ticket mapping

| Ticket | Delivers from this folder |
| --- | --- |
| KRA-19 scaffold | P-01 peer bumps; `deploy/`, `src/{main,app.module,config,health,drizzle module,event-bus skeleton,workflow skeleton}`, `package.json`, empty guarded route surfaces, `.env.example`, turbo/CI wiring, release-please entries at `0.0.0`; **absurd spike** (cancellation, `awaitEvent` deadline, concurrency, retry policy, Nest 12/ESM) — findings and chosen patterns recorded in `decisions.md` |
| KRA-20 persistence | `src/drizzle/schema/*`, migrations (+ absurd schema), repositories, `PgTaskStore`, constraint tests incl. cross-tenant |
| KRA-21 internal client | `src/unique/*`, `src/event-bus/*`, `src/auth/*`; gap list filed against core (P-03: elicitation bus events, `executionProvider = A2A` dispatch/cancel/elicitation callback, `a2aCapabilities`) |

## Configuration (env, validated with zod)

| Var | Purpose |
| --- | --- |
| `AUTH_MODE` | `kong` (default: identity headers required) · `development` (no auth, local only; refused when `NODE_ENV=production`) |
| `DATABASE_URL` | Postgres (gateway tables + absurd schema) |
| `AMQP_URL` | platform RabbitMQ; read binding on `EVENT_BUS` |
| `PUBLIC_BASE_URL` | Kong-facing base URL for agent-card `supportedInterfaces[].url` and file URIs |
| `ZITADEL_ISSUER` | only for `securitySchemes.openIdConnectUrl` in agent cards |
| `UNIQUE_CHAT_URL`, `UNIQUE_SCOPE_MANAGEMENT_URL`, `UNIQUE_INGESTION_URL` | core internal endpoints |
| `ENCRYPTION_KEY` | credential vault |
| `EGRESS_ALLOWED_HOSTS` | exact operator-approved hostnames for credential-bearing remote/token requests; empty denies all |
| `MAX_REMOTE_FILE_BYTES`, `SYNC_WAIT_MAX_MS`, `STREAM_TIMEOUT_MS` | limits (inbound file size is bounded by Kong/body limits and core ingestion) |
| `TASK_RETENTION_DAYS`, `EXECUTION_RETENTION_DAYS`, `PUSH_MAX_FAILURES`, `RECONCILE_INTERVAL` | lifecycle |
| `WORKER_ENABLED` | run absurd workers in this replica |

Missing required config → readiness fails; no surface is mounted without its guard.

## KRA-12 integration boundaries

Implemented on current surfaces: human-identity guard/bootstrap, publication/connection management authorization, encrypted shared credentials, tenant/owner/publication-scoped task storage and core deployment/rollout capability contract. See [OAuth onboarding](./oauth-onboarding.md).

Pending later epics: real cards/catalog/RPC/task/artifact handlers, connection test/delete, UI, and core external-space model/dispatch/clone/import paths. KRA-30 must add `executionProvider`/`a2aConnectionId` to the core assistant queries before credential-provider invocation can succeed (it currently fails closed). Wire the shared authorization services into those paths and test active-run completion/reconnect/cancellation there. External-space publication prevention cannot be validated end-to-end until that core model exists.

## Outside this service

- **Kong** (P-02): routes for card (no auth), `/a2a/*`, `/management/*` (JWT → identity headers + `x-client-id` from `azp`, strip inbound identity headers), CORS for the frontend; NetworkPolicy for `/internal/*`.
- **Core** (P-03): KRA-30 (`executionProvider`, `a2aConnectionId`, dispatch, cancel, elicitation-response callback), KRA-25 (`A2A_GATEWAY_URL`, rollout flag, `a2aCapabilities`), KRA-27 (space settings UI → management surface), elicitation events on `EVENT_BUS`.
- **RabbitMQ** (P-04): gateway user with rights to declare its own queues and bind to `EVENT_BUS`.
