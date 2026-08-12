# Design: outlook-semantic-mcp forward proxy support

**Ticket:** UN-23554

## Problem

`outlook-semantic-mcp` has no forward-proxy support. Every outbound call uses the default undici
dispatcher (or Node's core `https` agent), so the service cannot be deployed into customer
environments where egress to Microsoft Graph, `login.microsoftonline.com` and the Unique API is only
permitted through a corporate HTTP(S) proxy.

`sharepoint-connector` and `confluence-connector` already solve this, with near-identical copies of a
`ProxyService` + `proxy.config.ts` pair. Porting a third copy is the obvious move and the wrong one.

### Outbound call inventory

Established by reading every call site, not from the ticket:

| # | Site | Destination | Current transport |
|---|---|---|---|
| 1 | `src/msgraph/graph-client.factory.ts` | Graph | Graph SDK → global `fetch` |
| 2 | `src/msgraph/token.provider.ts:78` | `login.microsoftonline.com` | global `fetch` |
| 3 | `src/unique/unique-api.module.ts` | Unique API | undici (accepts `dispatcher`) |
| 4 | `src/health/ms-graph-connectivity-health.indicator.ts:33` | Graph | undici `fetch` |
| 5 | `src/unique/upload-file-for-ingestion.command.ts:19` | Azure blob *or* ingestion svc | global `fetch` |
| 6 | `.../upload-in-memory-attachment.command.ts:73` | Graph upload session | global `fetch` |
| 7 | `.../stream-unique-attachment.command.ts:68` | Unique ingestion svc | global `fetch` |
| 8 | `.../stream-unique-attachment.command.ts:238` | Graph upload session | global `fetch` |
| 9 | `src/auth/microsoft.provider.ts` → `passport-microsoft` | `login.microsoftonline.com` + Graph | **Node core `https`** |

### Three findings that shape the design

**1. Site 9 is not reachable by an undici dispatcher, and the ticket misses it.**
The interactive MCP login flow runs `passport-microsoft` → `passport-oauth2` → `oauth@0.10.2`, which
issues requests through Node's core `https.request` (`oauth/lib/oauth2.js:142` — `options.agent =
this._agent`). An undici `ProxyAgent` cannot intercept it. Shipping undici-only proxy support would
produce a service whose Graph calls are proxied but whose *login* — the call that produces the tokens
every other call depends on — hangs. The feature would be non-functional for its target deployment.

Mitigation is cheap and needs **no change to `@unique-ag/mcp-oauth`**:
- `passport-oauth2/lib/strategy.js:96` assigns `this._oauth2` inside the constructor, so a subclass
  can call `setAgent()` immediately after `super()`.
- `passport-microsoft/lib/strategy.js:97` fetches the profile through that same `_oauth2` instance,
  so one `setAgent()` covers both the token exchange and the profile fetch.
- `provider.strategy` is typed `z.any()` (`mcp-oauth.module-definition.ts:9`) and the whole `provider`
  object is supplied per-service inside `McpOAuthModule.forRootAsync`'s `useFactory`
  (`app.module.ts:134`), so the service can pass a subclass with no shared-package hook.

**2. Passing a dispatcher to `UniqueApiModule` silently removes retry and redirect.**
`unique-api-client.factory.ts:33-35` reads
`config.dispatcher ?? new Agent().compose([interceptors.retry(), interceptors.redirect()])`.
Today outlook passes no dispatcher, so it receives that composed agent implicitly. The moment we pass
`dispatcher`, the `??` stops firing and all Unique API traffic loses both interceptors — *including
when `PROXY_AUTH_MODE=none`*, breaking the ticket's own "behaviour unchanged when no proxy is
configured" criterion. This is why `sharepoint-connector/src/shared/services/http-client.service.ts`
composes them back on. We must do the same.

Dispatcher ownership is already correct: `isOwnedDispatcher` (factory line 33, close at line 126)
means `unique-api` will not close a dispatcher we supply, leaving `ProxyService.onModuleDestroy` as
sole owner. No double-close.

**3. Retry lives at a different layer for everything else, so proxying the raw `fetch` sites is safe.**
The only *active* dispatcher-level retry in the service is the Unique API path above.
`src/http-client/http-client.service.ts:11` composes `interceptors.retry()` but `HttpClientModule` is
imported nowhere — dead code. The Graph SDK retries via its own `RetryHandler` middleware
(`graph-client.factory.ts:92`), independent of the dispatcher. Six command files retry at the
orchestration level via `withRetryAttempts`. Sites 2 and 5–8 have no retry at all.

This matters for site 5, whose comment (`upload-file-for-ingestion.command.ts:17`) warns that undici
retrying on 500s corrupted Azure blobs by re-sending only the first chunk. That warning is about
`interceptors.retry()`, not undici itself. A bare `Agent`/`ProxyAgent` from `getDispatcher()` has no
retry composed, so attaching it there cannot reintroduce the corruption — provided we pass the
dispatcher directly and never compose retry onto it at that site.

## Solution

### Overview

Extract a `@unique-ag/proxy` package containing the config schema, `ProxyModule` and `ProxyService`,
and wire `outlook-semantic-mcp` onto it. `sharepoint-connector` and `confluence-connector` keep their
existing copies for now; migrating them is a tracked follow-up. This avoids a third copy without
putting two shipping connectors at regression risk inside this PR.

`ProxyService` exposes two agent flavours built from one config:
- an **undici `Dispatcher`** for the eight undici/fetch call sites, and
- a **core-http `https-proxy-agent`** for `passport-microsoft` (site 9).

Both honour the same `PROXY_*` env vars with the same semantics as the SharePoint connector.
`https-proxy-agent@7.0.6`'s options type is `tls.ConnectionOptions & http.AgentOptions & { headers }`,
so `cert`/`key`/`ca` and the CONNECT `headers` map onto the identical config — `ssl_tls` and
`PROXY_SSL_CA_BUNDLE_PATH` behave the same across both flavours.

### Architecture

**`packages/proxy`** (new workspace package, `@unique-ag/proxy`)

```
packages/proxy/
  package.json          # deps: undici, https-proxy-agent; peer: @nestjs/common, @nestjs/config, zod
  src/
    proxy.config.ts     # ProxyConfigSchema + registerConfig('proxy', ...)
    proxy.service.ts    # ProxyService
    proxy.module.ts     # ProxyModule.forRootAsync
    index.ts
    __tests__/proxy.service.spec.ts
```

The config schema is ported from `confluence-connector/src/config/proxy.config.ts` — it is the
cleaner of the two copies, already using `@unique-ag/utils/zod`'s `json` helper rather than a
service-local `parseJsonEnvironmentVariable`. It keeps the discriminated union over `authMode`
(`none` | `no_auth` | `username_password` | `ssl_tls`) and the `z.preprocess` empty-object guard,
whose comment explains why `prefault` cannot be used with nestjs-zod. Env var names are unchanged:
`PROXY_AUTH_MODE`, `PROXY_HOST`, `PROXY_PORT`, `PROXY_PROTOCOL`, `PROXY_USERNAME`, `PROXY_PASSWORD`,
`PROXY_SSL_CERT_PATH`, `PROXY_SSL_KEY_PATH`, `PROXY_SSL_CA_BUNDLE_PATH`, `PROXY_HEADERS`.

`ProxyService` exposes three modes:

```ts
export type ProxyMode = 'always' | 'never' | 'for-external-only';

getDispatcher({ mode }: { mode: ProxyMode }): Dispatcher
getHttpAgent({ mode }: { mode: ProxyMode }): http.Agent | undefined
```

`for-external-only` is resolved against an `isExternal` boolean supplied at module registration
rather than by reading a consumer's config namespace:

```ts
ProxyModule.forRootAsync({
  inject: [ConfigService],
  useFactory: (config: ConfigService<UniqueConfigNamespaced, true>) => ({
    isExternal: config.get('unique', { infer: true }).serviceAuthMode === 'external',
  }),
})
```

This keeps all three modes available while leaving the package ignorant of each service's config
shape — sharepoint migrates later with zero call-site changes, and confluence can still pass `'never'`
per-tenant from its `TenantRegistry`.

`getHttpAgent` returns `undefined` when the resolved mode is no-proxy, so callers can skip
`setAgent()` entirely rather than installing a pass-through agent. Timeouts reuse the existing
`sharedTimeoutOptions` (`bodyTimeout: 60_000`, `headersTimeout: 30_000`, `connectTimeout: 15_000`)
unchanged. `onModuleDestroy` closes both undici dispatchers as today; the core-http agent is
destroyed alongside them.

**`outlook-semantic-mcp` wiring**

`ProxyModule.forRootAsync` is registered in `app.module.ts` and `proxyConfig` added to the
`ConfigModule.forRoot` `load` array and to `ConfigNamespaced` in `src/config/index.ts`.

Mode per call site:

| Site | Mode | Rationale |
|---|---|---|
| 1 Graph SDK | `always` | External Microsoft endpoint |
| 2 token refresh | `always` | External Microsoft endpoint |
| 4 Graph health check | `always` | External Microsoft endpoint |
| 6, 8 Graph upload sessions | `always` | `uploadUrl` is an external Microsoft URL from `createUploadSession` |
| 9 passport strategy | `always` | External Microsoft endpoints |
| 7 content download | `never` | `stream-unique-attachment.command.ts:43` hard-gates on `serviceAuthMode === 'cluster_local'` and returns `failed` otherwise, so this call is unconditionally in-cluster |
| 3 Unique API | `for-external-only` | In-cluster under `cluster_local` |
| 5 blob/ingestion upload | `for-external-only` | `correctWriteUrl` already rewrites to the in-cluster hairpin path when not `external`; the mode must track the same condition |

Site 7 uses `never` rather than `for-external-only` deliberately: under `for-external-only` it would
be correct only by coincidence, and would read as though a proxied path existed. `never` states the
invariant the file already enforces.

Sites 1 and 4 follow the reference implementation — `fetchOptions.dispatcher` on `ClientOptions` for
the Graph SDK, and a `dispatcher` option on the undici `fetch` for the health indicator. Sites 2 and
5–8 switch from global `fetch` to `fetch` imported from `undici` with an explicit `dispatcher`.

Site 3 must compose the interceptors back on, per finding 2:

```ts
dispatcher: proxyService
  .getDispatcher({ mode: 'for-external-only' })
  .compose([interceptors.retry(), interceptors.redirect()])
```

Site 9 becomes a subclass in `src/auth/microsoft.provider.ts`, with `MicrosoftOAuthProvider` changed
from a static const to a factory taking the agent, called from the existing `McpOAuthModule
.forRootAsync` `useFactory` in `app.module.ts` with `ProxyService` added to its `inject` array.

`src/http-client/` is deleted. It composes retry+redirect on a non-proxied `Agent`, is imported
nowhere, and would be a live trap once a proxy exists — the next person to wire it up would silently
bypass the proxy.

**Deployment**

- `deploy/helm-charts/outlook-semantic-mcp/templates/proxy-configmap.yaml`, ported from the
  SharePoint chart, gated on `.Values.proxyConfig.enabled`.
- `proxyConfig` block in `values.yaml` and `values.schema.json`, matching SharePoint's keys and
  comments. `PROXY_PASSWORD` stays out of the ConfigMap and is supplied via `envVars` from a secret,
  as in SharePoint.
- `.env.example` gains the `PROXY_*` block; `docs/operator/configuration.md` gains a proxy section
  covering all four auth modes and the cert-mounting requirement for `ssl_tls`.

Adding `packages/proxy` requires a `proxy = packages/proxy/**` entry in `.gitcommitizen`'s `[scopes]`
section — `defined-scope = true` and `enforce-patterns = true` mean commits touching it are otherwise
rejected. `pnpm-workspace.yaml` already globs `packages/*` and needs no change.

### Error Handling

Config validation is the primary guard: the discriminated union makes `PROXY_HOST`/`PORT`/`PROTOCOL`
required for every non-`none` mode, and the cert paths required for `ssl_tls`, so a misconfigured
proxy fails at boot with a zod error naming the missing variable rather than at first request.

Cert and CA bundle files are read synchronously in the `ProxyService` constructor. A missing or
unreadable path throws during module init — deliberate, and matching the reference implementation: a
service that cannot build its proxy agent must not start and report healthy.

Beyond that, proxy failures surface as ordinary transport errors. Connection failures through the
proxy raise the same undici error types the call sites already handle, so `get-retry-after-ms.ts` and
`is-rate-limit-error.ts` (both of which already branch on `undici.errors`) keep working unchanged.
The Graph connectivity health indicator reports the proxy path as `down` on failure via its existing
`extractErrorCode` branch, which gives operators a direct signal that egress is misconfigured.

No retry or fallback is added. A proxy that cannot be reached is a deployment fault, not a transient
condition to paper over, and silently falling back to a direct connection would defeat the point of
the feature in exactly the environments that require it.

### Testing Strategy

Behavioural, using the existing vitest setup.

- `packages/proxy/src/__tests__/proxy.service.spec.ts`, ported from
  `confluence-connector/src/proxy/__tests__/proxy.service.spec.ts`: all four auth modes produce the
  expected agent type; `none` yields a plain `Agent`; `never` returns the direct dispatcher;
  `for-external-only` follows the injected `isExternal` flag; `username_password` sets the Basic
  token; `ssl_tls` and `sslCaBundlePath` populate `proxyTls`. Plus coverage for `getHttpAgent`
  returning `undefined` in no-proxy modes and an `HttpsProxyAgent` otherwise.
- Graph client factory: asserts `fetchOptions.dispatcher` is the dispatcher from
  `getDispatcher({ mode: 'always' })`.
- Health indicator: asserts the ping is issued with that dispatcher.
- Unique API module: asserts the dispatcher handed to `UniqueApiModule` is a *composed* dispatcher,
  guarding finding 2 — the regression this test exists to catch is silent and would otherwise only
  show up as lost retries in production.
- `microsoft.provider`: asserts `setAgent` is called when a proxy is configured and not called when
  `PROXY_AUTH_MODE=none`.
- Helm: extend the chart tests with `proxyConfig` cases (disabled, `no_auth`, `username_password`,
  `ssl_tls`), mirroring `sharepoint-connector/.../tests/regressions._test.yaml`.

The raw `fetch` call sites (5–8) are covered by the mode table above rather than by new unit tests;
their existing tests keep passing, and asserting "this call used dispatcher X" at four more sites has
poor cost/benefit versus the config-level tests.

## Out of Scope

- **Migrating `sharepoint-connector` and `confluence-connector` onto `@unique-ag/proxy`.** Tracked as
  a follow-up. Both keep their current copies; this PR does not touch them.
- Proxying AMQP or Postgres connections. Neither is HTTP; the ticket is scoped to HTTP egress.
- `NO_PROXY` / per-host bypass lists. Neither reference implementation has them and no requirement
  exists.
- Proxy connection pooling, metrics or dedicated dashboards.
- Runtime proxy reconfiguration. Config is read once at boot, as in both reference implementations.
- Changing the shared `sharedTimeoutOptions` values. Attachment chunks (sites 6 and 8) now traverse
  the proxy and are the largest payloads the service moves, but undici's `bodyTimeout` is an
  inactivity timeout between chunks rather than a total-transfer deadline, so a steadily-streaming
  upload will not trip the existing 60s value. Revisit only if it proves a problem in practice.

## Tasks

1. **Add the `proxy` commit scope** - Add `proxy = packages/proxy/**` to the `[scopes]` section of
   `.gitcommitizen`. Without it, `defined-scope = true` rejects every commit touching the new package.

2. **Scaffold `packages/proxy`** - Create the workspace package using `packages/probe` as the
   structural template: `package.json` (`@unique-ag/proxy`, private, `undici` + `https-proxy-agent`
   deps, nest/zod peers), `tsconfig.json`, `src/index.ts`.

3. **Port the proxy config schema** - Move `confluence-connector/src/config/proxy.config.ts` into the
   package, keeping the discriminated union, the `z.preprocess` empty-object guard and its explanatory
   comment, and sourcing `json`/`redacted` from `@unique-ag/utils/zod`.

4. **Implement `ProxyService` and `ProxyModule`** - Port the confluence `ProxyService`, extend it to
   the three-mode enum resolved against an injected `isExternal` flag, and add `getHttpAgent` building
   an `HttpsProxyAgent` from the same config. Expose `ProxyModule.forRootAsync`. Close both
   dispatchers and destroy the agent in `onModuleDestroy`.

5. **Write `proxy.service.spec.ts`** - Port the confluence spec and extend it to cover the third mode,
   the `isExternal` resolution and `getHttpAgent` across all four auth modes.

6. **Register proxy config and module in outlook** - Add `proxyConfig` to `ConfigModule.forRoot`'s
   `load` array and `ProxyConfigNamespaced` to `ConfigNamespaced`, and register
   `ProxyModule.forRootAsync` in `app.module.ts` deriving `isExternal` from `unique.serviceAuthMode`.

7. **Proxy the Graph SDK client** - Inject `ProxyService` into `GraphClientFactory` and pass
   `fetchOptions: { dispatcher: getDispatcher({ mode: 'always' }) }` in `ClientOptions`. Assert the
   wiring in the factory's existing test.

8. **Proxy the token refresh** - Replace the global `fetch` in `token.provider.ts:78` with undici
   `fetch` plus the `always` dispatcher. `TokenProvider` is constructed manually by
   `GraphClientFactory`, so the dispatcher is threaded through its existing options object.

9. **Proxy the passport-microsoft login flow** - Convert `MicrosoftOAuthProvider` into a factory
   taking an optional agent, returning a provider whose `strategy` is a subclass calling
   `this._oauth2.setAgent(agent)` after `super()`. Inject `ProxyService` into the existing
   `McpOAuthModule.forRootAsync` factory in `app.module.ts`.

10. **Proxy the Unique API clients** - Pass a `for-external-only` dispatcher to `UniqueApiModule`
    with `interceptors.retry()` and `interceptors.redirect()` composed back on, and add the test that
    guards against losing them.

11. **Proxy the Graph health indicator** - Pass the `always` dispatcher to the undici `fetch` in
    `ms-graph-connectivity-health.indicator.ts` and assert it in the indicator's test.

12. **Proxy the remaining raw fetch call sites** - Switch sites 5–8 to undici `fetch` with the mode
    from the design table, adding a brief comment at site 7 recording why it is `never`.

13. **Delete the dead `HttpClientModule`** - Remove `src/http-client/` entirely.

14. **Add the Helm proxy configuration** - Port `proxy-configmap.yaml` and the `proxyConfig` block
    into the outlook chart's `values.yaml` and `values.schema.json`, then extend the chart tests to
    cover disabled, `no_auth`, `username_password` and `ssl_tls`.

15. **Document the proxy** - Add the `PROXY_*` block to `.env.example` and a proxy section to
    `docs/operator/configuration.md` covering all four modes and cert mounting for `ssl_tls`.

16. **File the migration follow-up** - Open a ticket to move `sharepoint-connector` and
    `confluence-connector` onto `@unique-ag/proxy` and delete their local copies.
