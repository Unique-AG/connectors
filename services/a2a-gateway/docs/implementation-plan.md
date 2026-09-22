# Implementation plan (KRA-11 groundwork)

## Target layout

```
services/a2a-gateway/
├── deploy/                     # Dockerfile, helm-charts/a2a-gateway (copy pattern from teams-mcp)
├── drizzle/                    # generated migrations
├── docs/                       # this design
├── src/
│   ├── main.ts · app.module.ts · instrumentation.ts
│   ├── config/                 # zod configs: app, database, zitadel, unique (core URLs), egress, limits, worker
│   ├── drizzle/                # module + schema/{publications,connections,contexts,tasks,artifacts,push-configs,executions,remote-contexts}.table.ts
│   ├── health/                 # terminus: db, core reachability (readiness), zitadel jwks
│   ├── auth/                   # ZitadelTokenVerifier, HumanPrincipalGuard, ClusterIdentityGuard (x-user-id/x-company-id), KongIdentityGuard
│   ├── unique/                 # UniqueInternalClient: spaces, messages, run-events (SSE), elicitations, content; normalised errors
│   ├── credentials/            # CredentialVault (aes-gcm-encryption), credential types
│   ├── egress/                 # EgressGuard (allow-list, private-range/metadata block, redirects, size, timeout)
│   ├── a2a-server/             # jsonRpcHandler mount, PublicationResolver middleware, PgTaskStore, InboundExecutor, agent-card builder, catalog controller, file download controller
│   ├── outbound/               # OutboundRunner, RemoteClientFactory (@a2a-js/sdk Client), connection test/negotiation
│   ├── bridge/                 # ElicitationBridge, ArtifactTranslator (text/data/file both directions)
│   ├── management/             # publications + connections controllers/services
│   ├── internal/               # capabilities, executions, reconcile controllers
│   └── worker/                 # pg-boss registration: outbound.poll, push.deliver, reconcile, retention
├── test/                       # e2e: tck smoke, authz matrix, cross-tenant
├── package.json · nest-cli.json · drizzle.config.ts · vitest*.config.ts · turbo.json · tsconfig*.json
```

## Ticket mapping

| Ticket | Delivers from this folder |
| --- | --- |
| KRA-19 scaffold | `deploy/`, `src/{main,app.module,config,health,drizzle module}`, `package.json` with `@a2a-js/sdk`, `pg-boss`, `drizzle-orm`, `jose`; route surfaces mounted empty; `.env.example`; CI entry via turbo; `.release-please-manifest.json` + `release-please-config.json` entries at `0.0.0` |
| KRA-20 persistence | `src/drizzle/schema/*`, migrations, repositories, `PgTaskStore`, constraint tests incl. cross-tenant |
| KRA-21 internal client | `src/unique/*`, `src/auth/ClusterIdentityGuard`, gap list filed against core (`node-chat` run-event contract, `executionProvider` dispatch) |

## Configuration (env, validated with zod)

| Var | Purpose |
| --- | --- |
| `DATABASE_URL` | Postgres |
| `PUBLIC_BASE_URL` | absolute base for agent-card `supportedInterfaces[].url` and file URIs |
| `ZITADEL_ISSUER`, `ZITADEL_PROJECT_ID`, `ZITADEL_JWKS_URL?` | inbound token verification |
| `UNIQUE_CHAT_URL`, `UNIQUE_SCOPE_MANAGEMENT_URL`, `UNIQUE_INGESTION_URL` | core internal endpoints |
| `ENCRYPTION_KEY` | credential vault |
| `EGRESS_ALLOWED_HOSTS?` | optional allow-list for remote agents/push URLs (private ranges always blocked) |
| `MAX_INLINE_FILE_BYTES`, `MAX_REMOTE_FILE_BYTES`, `SYNC_WAIT_MAX_MS`, `STREAM_TIMEOUT_MS` | limits |
| `TASK_RETENTION_DAYS`, `EXECUTION_RETENTION_DAYS`, `PUSH_MAX_FAILURES` | lifecycle |
| `WORKER_ENABLED` | run pg-boss workers in this process |

Missing required config → readiness fails; no surface is mounted without its guard.

## Core-side tickets this design depends on

- KRA-30: `Assistant.executionProvider`, `a2aConnectionId`, dispatch to `/internal/executions`, cancel hook.
- KRA-25: `A2A_GATEWAY_URL`, feature flag, entitlement, `a2aCapabilities` query.
- KRA-27: space settings UI (publication + connection selection) calling the management surface.
- KRA-21 gap list: stable run-event contract; optional elicitation callback.
