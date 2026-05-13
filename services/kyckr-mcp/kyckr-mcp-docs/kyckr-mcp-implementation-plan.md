# Kyckr MCP Implementation Plan

## Current state

The `kyckr-mcp` directory is a verbatim copy of `outlook-semantic-mcp`. It contains AMQP, Drizzle DB, Microsoft Graph, OAuth flows, ingestion workers, subscriptions, and Outlook-specific features. The implementation scope asks to strip all of that down to a thin NestJS/MCP wrapper around Kyckr's REST API.

## Task 1 — Fix directory name

Rename `services/kyckr-mcp ` (trailing space in name) to `services/kyckr-mcp`.

## Task 2 — Strip package.json

- Rename package to `@unique-ag/kyckr-mcp`
- Remove dead scripts: `db:generate`, `db:migrate`, `db:check`
- Remove dead dependencies: `@golevelup/nestjs-rabbitmq`, `@microsoft/microsoft-graph-client`, `@nestjs/cache-manager`, `@nestjs/event-emitter`, `@nestjs/schedule`, `@opentelemetry/instrumentation-pg`, `@unique-ag/aes-gcm-encryption`, `@unique-ag/mcp-oauth`, `@unique-ag/unique-api`, `amqplib`, `bottleneck`, `cache-manager`, `cron`, `drizzle-orm`, `drizzle-zod`, `fastest-levenshtein`, `jsonwebtoken`, `passport`, `passport-microsoft`, `pg`, `safe-regex2`
- Remove dead devDependencies: `@microsoft/microsoft-graph-types`, `@types/amqplib`, `@types/jsonwebtoken`, `@types/passport`, `@types/passport-microsoft`, `@types/pg`, `drizzle-kit`

## Task 3 — Register kyckr-mcp in workspace config

- Add `kyckr-mcp = services/kyckr-mcp/**` to `.gitcommitizen`
- Add `services/kyckr-mcp` to `release-please-config.json`

## Task 4 — Delete dead source directories

Remove entirely: `src/amqp/`, `src/db/`, `src/msgraph/`, `src/auth/`, `src/features/`, `src/unique/`

## Task 5 — Strip src/utils to a minimal set

Keep only: `zod.ts`, `sleep.ts`, `redacted.ts`, `record-in-histogram.ts`, `tracing.ts`, `nullish.ts`, `non-nullish-props.ts`, `validation-call.interceptor.ts`

Delete: all graph/KQL/Outlook-specific utilities, `graph-error.filter.ts`, SQL helpers, email/sync helpers

## Task 6 — Rewrite config

- Delete: `amqp.config.ts`, `auth.config.ts`, `database.config.ts`, `delegated-access.config.ts`, `encryption.config.ts`, `ingestion.config.ts`, `microsoft.config.ts`, `mcp-backend-type.config.ts`
- Simplify `app.config.ts`: remove `directorySyncCronSchedule`, `mcpBackend`, `selfUrl` (no OAuth callback needed)
- Keep `logs.config.ts`
- Add `kyckr.config.ts` with: `KYCKR_API_BASE_URL` (default `https://test-api.kyckr.com/v2`), `KYCKR_API_KEY` (required), `KYCKR_DEFAULT_CUSTOMER_REFERENCE` (optional), `KYCKR_DEFAULT_CONTACT_EMAIL` (optional)
- Add `MCP_ACCESS_TOKEN` to `appConfig` (optional) — protects the `/mcp` transport, independent of the Kyckr API key

## Task 7 — Rewrite app.module.ts and main.ts

- `app.module.ts`: remove all Outlook/DB/AMQP/OAuth/cache modules; keep `ConfigModule`, `LoggerModule`, `ProbeModule`, `OpenTelemetryModule`, `McpModule`; add simple access-token guard if `MCP_ACCESS_TOKEN` is set
- `main.ts`: rename service to `kyckr-mcp`, remove `includePgInstrumentation`, remove static assets, remove the 50 MB body limit override

After this task the app skeleton should compile and start with an empty MCP server.

## Task 8 — Adapt http-client and add Kyckr HTTP client module

- Keep `src/http-client/http-client.service.ts` as a base utility
- Create `src/kyckr/kyckr-http.client.ts`: adds `Authorization: Bearer <apiKey>` header, logs outgoing method and path (no sensitive headers), logs errors with status/details/correlation-id, records request count and duration metrics

## Task 9 — Implement 7 MCP tools

One file per tool or grouped by domain. Each tool delegates to the Kyckr HTTP client and returns the typed Kyckr response. Descriptions explicitly warn about credit cost and polling requirements where applicable.

- `search_companies` — wraps `GET /companies`
- `get_lite_profile` — wraps `GET /companies/{kyckrId}/lite`
- `get_enhanced_profile` — wraps `GET /companies/{kyckrId}/enhanced`
- `list_company_documents` — wraps `GET /companies/{kyckrId}/documents`
- `create_document_order` — wraps `POST /orders`
- `get_order` — wraps `GET /orders/{orderId}`
- `list_orders` — wraps `GET /orders`

## Task 10 — Add minimal metrics

- MCP tool call counter (tool name, result: success/error)
- Kyckr API request counter (method, path, status code)
- Kyckr API request duration histogram
- Document order status counter

## Task 11 — Update deploy scaffolding

- Rename `deploy/helm-charts/outlook-semantic-mcp/` to `deploy/helm-charts/kyckr-mcp/`
- Remove Outlook-specific helm templates: `_config-auth.tpl`, `_config-delegated-access.tpl`, `_config-ingestion.tpl`, `_config-microsoft.tpl`
- Update `Chart.yaml`, `values.yaml`, `_helpers.tpl` with kyckr-mcp name
- Update `Dockerfile` service name references
- Update `.env.example`

## Task 12 — Update docs and server instructions

- Rewrite `README.md` and `server.instructions.ts` for Kyckr
- Replace or delete all Outlook-specific docs under `docs/`
- Update `CHANGELOG.md` header
- Keep `kyckr-mcp-docs/` as-is

## Execution order

1 → 2 → 3 → 4 → 5 → 6 → 7 (skeleton compiles and starts) → 8 → 9 → 10 → 11 → 12

## Future work (deferred)

The items below are not blockers for the initial cut. They surfaced during review after tasks 1-8 and can be picked up opportunistically or in dedicated follow-up tickets.

### Wire `LOGS_DIAGNOSTICS_DATA_POLICY` into the logger

`logsConfig.diagnosticsDataPolicy` is registered in `app.module.ts` and documented in `.env.example`, but no code actually consumes the value. The pino logger options should toggle field redaction (PII / paths / emails) based on this policy. `outlook-semantic-mcp` has the same gap, so the fix likely belongs in `@unique-ag/logger`.

### Remove or wire `app.config.ts` `bufferLogs`

`appConfig.bufferLogs` exists in the schema but `main.ts` reads `process.env.APP_BUFFER_LOGS` directly. Either pipe the config value into the `NestFactory.create({ bufferLogs })` call or delete the schema field. Cosmetic; matches outlook today.

### Populate the Grafana dashboard

`deploy/helm-charts/kyckr-mcp/files/grafana-dashboard.json` is `{}` and `grafana.dashboard.enabled` is `false`. Build a dashboard around the metrics emitted by `KyckrHttpClient` (`kyckr_api_requests_total`, `kyckr_api_request_duration_ms`) plus tool-call counters added in task 10, then flip `grafana.dashboard.enabled` back to `true`.

### Author Prometheus alerts

`alerts.enabled` is `false` and `templates/alerts/` is intentionally empty. Worth adding once production traffic is observable: high Kyckr 4xx/5xx rate, latency p95 against a SLO, MCP tool error rate.

### Migrate config style if MCP access token guard grows

The current `McpAccessTokenGuard` is intentionally minimal (single static Bearer token). If the access model evolves toward per-client tokens, JWTs, or OAuth, fold it into the `@unique-ag/mcp-oauth` flow that `outlook-semantic-mcp` uses instead of extending the guard ad-hoc.

