<!-- confluence-page-id: 2814541902 -->
<!-- confluence-space-key: PUBDOC -->

## Overview

All configuration is through environment variables. Every variable this service defines is listed
on this page, grouped the way [`config.py`](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/config.py)
groups them. `FASTMCP_*` variables, and `OTEL_*` variables other than the three in
[Tracing](#Tracing), are read by libraries and are not covered here.

- **App default** is what the server uses when the variable is unset.
- **Chart default** is what the Helm chart's [`values.yaml`](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/deploy/helm-charts/backstop-mcp/values.yaml)
  sets under `env`. A blank cell means the chart leaves it to the app.
- Most values are validated at startup, and a value outside its allowed range stops the server.
  The error names the settings class and field, for example `BackstopConfig` / `max_retry_attempts`
  for `BACKSTOP_MAX_RETRY_ATTEMPTS`. `BACKSTOP_CUSTOM_FIELD_SCHEMA_TTL_MINUTES` is clamped instead.
- `SEARCH_*`, `RESOLUTION_*`, `PRODUCT_INVESTORS_*`, and `ACTIVITY_HISTORY_*` are read on the first
  tool call that uses them. A bad value there does not stop startup; it fails those tool calls.
- Variable names are case-insensitive, except `DATABASE_URL` and `LOGS_DIAGNOSTICS_DATA_POLICY`,
  which must be upper case. Booleans accept `true` / `false`.

Only two variables have no usable default in production: `PUBLIC_BASE_URL` and
`BACKSTOP_MCP_ENCRYPTION_KEY`. A database connection is also required.

### Setting values with Helm

| Kind | Where | Example |
|---|---|---|
| Per-firm settings | `mcpConfig`, checked by the chart schema | `mcpConfig: { backstop: { baseUrl: https://<firm>.backstopsolutions.com } }`. See [Chart values](#Chart-values) |
| Tuning (caches, timeouts, page sizes, logging) | `env` map (rendered into a ConfigMap) | `env: { SEARCH_RESULT_SIZE: "200" }` |
| Secrets | `envVars` list, native Kubernetes syntax | `- name: BACKSTOP_MCP_ENCRYPTION_KEY` with `valueFrom.secretKeyRef` |
| Database | `postgresql.connection`, which injects `DATABASE_URL` | `url: { fromSecret: { name: ..., key: ... } }` |

### Chart values

The settings that differ per firm have typed values under `mcpConfig`:

| Chart value | Variable | Type |
|---|---|---|
| `mcpConfig.app.publicBaseUrl` | `PUBLIC_BASE_URL` | URL |
| `mcpConfig.backstop.baseUrl` | `BACKSTOP_BASE_URL` | URL |
| `mcpConfig.backstop.uiBaseUrl` | `BACKSTOP_UI_BASE_URL` | URL |
| `mcpConfig.employment.relationshipTypeIds` | `BACKSTOP_EMPLOYMENT_RELATIONSHIP_TYPE_IDS` | List |
| `mcpConfig.employment.relationshipTypeMarkers` | `BACKSTOP_EMPLOYMENT_RELATIONSHIP_TYPE_MARKERS` | List |
| `mcpConfig.employment.formerRelationshipTypeIds` | `BACKSTOP_FORMER_EMPLOYMENT_RELATIONSHIP_TYPE_IDS` | List |
| `mcpConfig.employment.formerRelationshipTypeMarkers` | `BACKSTOP_FORMER_EMPLOYMENT_RELATIONSHIP_TYPE_MARKERS` | List |
| `mcpConfig.tenantGuidance` | `BACKSTOP_MCP_TENANT_GUIDANCE` | Object, rendered as JSON. See [Tenant guidance](#Tenant-Guidance) |

```yaml
mcpConfig:
  app:
    publicBaseUrl: https://backstop-mcp.example.com
  backstop:
    baseUrl: https://<firm>.backstopsolutions.com
    uiBaseUrl: https://<firm>.backstopsolutions.com
  employment:
    formerRelationshipTypeIds: ["1042", "1043"]
```

- A misspelt key fails `helm install` against the chart schema. A URL must start with `http://` or
  `https://`, and a list item cannot contain a comma. Ids are strings: quote them (`["1042"]`), or
  the schema rejects them.
- A URL is rendered only when it is not empty, so an empty value keeps the app default. URLs pass
  through `tpl`, so an overlay can build them from other values. The schema checks the raw value
  before `tpl` runs, so the scheme must be literal: `https://{{ .Values.routes.hostname }}` passes,
  while `{{ printf "https://%s" .Values.routes.hostname }}` is rejected.
- A list is rendered comma-separated whenever it is set, including `[]`, which reaches the app as an
  empty value. The chart default `null` leaves the variable unset. This matters for the markers
  lists: `[]` replaces their defaults, `null` keeps them. See
  [Departed-contact detection](#Departed-Contact-Detection).
- `mcpConfig.tenantGuidance` is rendered only when it is not empty.
- `mcpConfig.enabled: false` renders none of these variables, tenant guidance included.
- A variable set both under `mcpConfig` and under `env` takes the `mcpConfig` value. `env` reaches
  the container through a ConfigMap (`envFrom`), and Kubernetes gives a container's own `env`
  entries precedence over it. A deployment that still sets these variables under `env` keeps
  working, and can move them to `mcpConfig` at any time.

## Required

| Variable | Format | Description |
|---|---|---|
| `PUBLIC_BASE_URL` | `https://host` | The URL clients and browsers reach this server on. It is the OAuth issuer; the login form and every OAuth endpoint hang off it. With `APP_ENV=production`, a loopback or `0.0.0.0` host is refused at startup. In Helm, set `mcpConfig.app.publicBaseUrl` |
| `BACKSTOP_MCP_ENCRYPTION_KEY` | Fernet key | Encrypts stored Backstop credentials. Startup fails if it is missing or invalid. See [Authentication: Encryption key](./authentication.md#Encryption-Key) |
| `DATABASE_URL` or `DB_URL` or `DB_HOST`+`DB_NAME`+`DB_USER`+`DB_PASSWORD` | See [Database](#Database) | PostgreSQL connection |

## Application

| Variable | App default | Chart default | Description |
|---|---|---|---|
| `APP_ENV` | `production` | `production` | `development`, `production`, or `test`. Only `production` enforces a public `PUBLIC_BASE_URL` |
| `PORT` | `9010` | `8000` | HTTP port. The container image also sets `PORT=8000`. The chart writes it from `ports.application` and overwrites any `env.PORT` |
| `LOG_LEVEL` | `info` | `info` | `debug`, `info`, `warning`, `error`, `critical` |
| `LOGS_DIAGNOSTICS_DATA_POLICY` | `conceal` | `conceal` | `conceal` pseudonymizes identifying values (logins, emails, search terms). At `LOG_LEVEL` info or above the pseudonym is `hmac-sha256:<hex>`, keyed from `BACKSTOP_MCP_ENCRYPTION_KEY`, so guessing a likely email does not find the line. At `LOG_LEVEL=debug` it is plain `sha256:<hex>`, which a developer can recompute locally. `disclose` writes the original, and only the exact lower-case value `disclose` turns it on. The Backstop HTTP client's request and re-check events (`backstop.request.*`, `backstop.auth_recheck.*`) carry the plain username under either setting, so treat logs as containing Backstop logins. API tokens are never logged |
| `PUBLIC_BASE_URL` | `http://localhost:9010` | Set per deployment in `mcpConfig.app.publicBaseUrl` | See [Required](#Required) |
| `VERSION` | Package version | `image.tag`, falling back to the chart `appVersion` (set by the base chart) | Reported as the MCP server version and on metrics. Not meant to be set by hand |

## Tracing

Off unless one of these is set. The chart does not set an endpoint; an overlay does.

| Variable | App default | Chart default | Description |
|---|---|---|---|
| `OTEL_TRACES_EXPORTER` | unset | | `console` prints spans on stderr. `otlp` sends them to a collector. Unset, or `none`, installs no exporter |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | | Collector base URL, for example `http://otel-collector:4318`. Setting it turns tracing on |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | unset | | Traces-only collector URL. Wins over `OTEL_EXPORTER_OTLP_ENDPOINT` for traces when both are set |

## Backstop API

Where to reach Backstop and how the shared HTTP client behaves. Prefix `BACKSTOP_`.

| Variable | App default | Chart default | Description |
|---|---|---|---|
| `BACKSTOP_BASE_URL` | `https://api.backstopsolutions.com` | Set per deployment in `mcpConfig.backstop.baseUrl` | Backstop REST API origin: the tenant's own host or the shared API host. Both work |
| `BACKSTOP_UI_BASE_URL` | unset | Set per deployment in `mcpConfig.backstop.uiBaseUrl` | CRM UI origin used to build links to records (`{origin}/backstop/...`). See [CRM links](#CRM-links) |
| `BACKSTOP_DEFAULT_TIMEOUT_SECONDS` | `120` | | Timeout for one ordinary Backstop request |
| `BACKSTOP_REPORTS_TIMEOUT_SECONDS` | `600` | | Timeout for requests to `/reports` and `/analytics` paths, which Backstop documents as slow |
| `BACKSTOP_MAX_CONCURRENT_REQUESTS_PER_USER` | `5` | | Concurrent Backstop requests allowed per user, per pod. Backstop itself limits each user token to 5 |
| `BACKSTOP_MAX_RETRY_ATTEMPTS` | `5` | | Attempts for a request that gets a `429` Backstop marks as a concurrency limit. Only those are retried: minute, hour, and day quota `429`s, and `429`s Backstop does not classify, fail at once |
| `BACKSTOP_MAX_RETRY_WAIT_MS` | `30000` | | Longest single backoff the server will wait before retrying a `429`. A longer `Retry-After` fails the call instead |
| `BACKSTOP_DEFAULT_PAGE_SIZE` | `100` | | Page size for ordinary collection walks |
| `BACKSTOP_REPORT_PAGE_SIZE` | `500` | | Page size for `/reports` and `/analytics`. Maximum `500`, Backstop's recommendation |
| `BACKSTOP_PAGE_LIMIT_PARAM` | `page[limit]` | | Name of the page-size query parameter. Backstop silently ignores an unknown parameter, so only change it if Backstop changes |
| `BACKSTOP_PAGE_OFFSET_PARAM` | `page[offset]` | | Name of the page-offset query parameter. Same caution |

### CRM links

Tools that return a record also return its Backstop UI `url`, and `build_backstop_links` builds tab
and layout links. The origin is chosen like this:

1. `BACKSTOP_UI_BASE_URL` when set.
2. Otherwise `BACKSTOP_BASE_URL`, but only when its host is not `api.backstopsolutions.com`. A tenant
   host is assumed to also serve the UI.
3. Otherwise no links: record `url` fields are empty and `build_backstop_links` answers
   `not_configured`.

Set `BACKSTOP_UI_BASE_URL` explicitly whenever `BACKSTOP_BASE_URL` is not the tenant's own host. A
regional or staging API host would otherwise be used as a UI origin and produce links that do not
load.

## Catalog Caches

Several tools read small instance-wide catalogs (custom-field definitions, activity tags, system
users, and so on). Each catalog has an on/off flag and a TTL. With the flag off, every read fetches
the catalog from Backstop again. Concurrent requests for the same catalog share one fetch either way.

| Catalog | Enable flag | App / chart flag | TTL variable | Default TTL |
|---|---|---|---|---|
| Custom-field definitions and groups | `BACKSTOP_CUSTOM_FIELD_SCHEMA_CACHE_ENABLED` | `true` / `true` | `BACKSTOP_CUSTOM_FIELD_SCHEMA_TTL_MINUTES` | 120 |
| Contact sources | `BACKSTOP_CONTACT_SOURCE_CACHE_ENABLED` | `false` / `false` | `BACKSTOP_CONTACT_SOURCE_TTL_MINUTES` | 1440 |
| Contact categories | `BACKSTOP_CONTACT_CATEGORY_CACHE_ENABLED` | `false` / `false` | `BACKSTOP_CONTACT_CATEGORY_TTL_MINUTES` | 1440 |
| Activity tags | `BACKSTOP_ACTIVITY_TAG_CACHE_ENABLED` | `false` / `false` | `BACKSTOP_ACTIVITY_TAG_TTL_MINUTES` | 1440 |
| System users | `BACKSTOP_SYSTEM_USER_CACHE_ENABLED` | `false` / `false` | `BACKSTOP_SYSTEM_USER_TTL_MINUTES` | 1440 |
| Time zones | `BACKSTOP_TIME_ZONE_CACHE_ENABLED` | `false` / `false` | `BACKSTOP_TIME_ZONE_TTL_MINUTES` | 1440 |
| Opportunity stages | Always on | | `BACKSTOP_OPPORTUNITY_STAGE_TTL_MINUTES` | 60 |
| Entity-relationship types | Always on | | `BACKSTOP_ENTITY_RELATIONSHIP_TYPE_TTL_MINUTES` | 60 |

- Every TTL is in minutes, between 1 and 1440 (24 hours). A custom-field TTL above 1440 is lowered to
  1440 instead of failing startup.
- A TTL is ignored while its flag is off.
- The custom-field cache is on because large tenants have thousands of definitions and one walk takes
  several seconds; every party and product read joins against it.
- `list_custom_fields`, `list_custom_field_groups`, `list_activity_tags`, `list_contact_sources`,
  `list_contact_categories`, and `list_system_users` accept `refresh=true` to fetch again regardless
  of the TTL.
- When a cached catalog's refresh fails, the previous copy keeps being served and the TTL restarts.
  Opportunity stages and relationship types are the exception: a failed refresh fails the call.
- To decide whether to turn a cache on, compare `catalog_get_duration_seconds_count` (demand) with
  `catalog_fetch_duration_seconds_count` (actual walks). See [Architecture: Observability](../technical/architecture.md#Observability).

## Departed-Contact Detection

`get_person`, `get_people_for_party`, and `search_people` report whether a person's link to an
organization is `current` or `former`. A firm may record a departure as a separate relationship type
("is a former employee of") rather than an end date, so the server needs to know which relationship
types mean employment and which mean it has ended.

| Variable | Chart value (`mcpConfig.employment.`) | App default | Description |
|---|---|---|---|
| `BACKSTOP_EMPLOYMENT_RELATIONSHIP_TYPE_IDS` | `relationshipTypeIds` | empty | Relationship type ids that mean employment. Exact match |
| `BACKSTOP_EMPLOYMENT_RELATIONSHIP_TYPE_MARKERS` | `relationshipTypeMarkers` | `employ` | Case-insensitive substrings of a type's name that mean employment |
| `BACKSTOP_FORMER_EMPLOYMENT_RELATIONSHIP_TYPE_IDS` | `formerRelationshipTypeIds` | empty | Relationship type ids that mean employment has ended |
| `BACKSTOP_FORMER_EMPLOYMENT_RELATIONSHIP_TYPE_MARKERS` | `formerRelationshipTypeMarkers` | `former,previous,ex-,no longer` | Case-insensitive substrings that mean employment has ended |

- All four are comma-separated; in Helm they are lists. Setting a markers variable **replaces** its
  defaults; setting it empty (`[]` in Helm) leaves only the ids for that bucket. Leave the chart
  value `null` to keep the defaults.
- The two marker lists must not overlap. A shared substring such as `employee` cannot tell a current
  type from a former one, which is why the departure word is the marker. This is not checked at
  startup: an overlap silently misclassifies links.
- Ids differ per Backstop instance and have no default. `GET /entity-relationship-types` lists them.
- An organization's own record returns the mirror type ("… (mirror)") with a different id. Markers
  match both directions; if you configure former ids, include the mirror type's id too.

## Tool Behaviour

| Variable | App default | Chart default | Description |
|---|---|---|---|
| `SEARCH_RESULT_SIZE` | `100` | `100` | Rows one call of `search_organizations`, `search_people`, `search_opportunities`, or `search_activities` returns before handing back a cursor. 1 to 1000 |
| `RESOLUTION_ELICIT_TIMEOUT_SECONDS` | `120` | `120` | How long a tool waits for the user to pick between several matching records before returning the candidate list instead. The Unique chat client can cancel a tool call at 60 seconds |
| `PRODUCT_INVESTORS_MAX_VALUED_ACCOUNTS` | `100` | `150` | Most accounts `get_product_investors` fetches a latest value for (`include_latest_value`). Each is one Backstop request; measured at about 0.14 s per account warm |
| `ACTIVITY_HISTORY_PAGE_SIZE` | `10` | | Page size per stream in `get_activity_history`. Up to five streams are fetched at this size, so one page can return up to five times this many rows |
| `ACTIVITY_HISTORY_GIST_CHARS` | `300` | | Characters each activity body is cut to in `get_activity_history`. A gist is the start of the body, not a summary |

## Tenant Guidance

`BACKSTOP_MCP_TENANT_GUIDANCE` adds firm-specific text to what the AI reads, without changing the
shipped tool descriptions. In Helm, set the `mcpConfig.tenantGuidance` object; the chart renders it
as JSON into the variable, and omits the variable when the object is empty.

```yaml
mcpConfig:
  tenantGuidance:
    server_instructions: >-
      "Strategy" on a product is the custom field named Investment Strategy.
    tools:
      search_products:
        description: Fund short names start with NW, for example NWGM.
        parameters:
          name: Short names are upper case.
```

| Field | Limit | Appended to |
|---|---|---|
| `server_instructions` | 1 to 2,500 characters | The server instructions, under the heading *"This firm's Backstop setup:"* |
| `tools.<tool>.description` | 1 to 800 characters | That tool's description, under the same heading |
| `tools.<tool>.parameters.<parameter>` | 1 to 300 characters | That top-level parameter's description |

- An unknown tool or parameter name stops startup, and the error lists the valid names.
- Unknown keys are rejected.
- Empty or unset means the shipped descriptions only.

## Database

| Variable | App default | Description |
|---|---|---|
| `DB_URL` | unset | PostgreSQL URL. `postgresql://` is accepted and rewritten for the async driver |
| `DATABASE_URL` | unset | Used when `DB_URL` is unset. The base chart injects it when `postgresql.enabled` is true and `postgresql.connection` has either `url` or all of `host`, `database`, `username`, and `password` |
| `DB_HOST` | unset | Used only when neither URL is set |
| `DB_PORT` | `5432` | |
| `DB_NAME` | unset | |
| `DB_USER` | unset | |
| `DB_PASSWORD` | unset | |
| `PG_DATABASE_SSL_MODE` | unset | `sslmode` used when the URL has none. The base chart sets it from `postgresql.connection.sslMode`, default `verify` |
| `DB_SSL_ROOT_CERT` | chart: `/etc/postgresql-ca/ca.crt` | CA file `verify-ca` and `verify-full` check the certificate against. When unset or absent, the container's system CA bundle |

Without a URL, `DB_HOST`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD` are all required and startup names
the missing ones.

**TLS** is set by the URL's `sslmode` parameter, or by `PG_DATABASE_SSL_MODE` when the URL has none:

| `sslmode` | Behaviour |
|---|---|
| `disable` | No TLS |
| `allow` | No TLS, unless the server requires it. Then TLS without verification |
| absent from both | The driver's default, `prefer`: TLS when the server offers it, without verification |
| `require`, `prefer` | TLS without certificate verification |
| `verify-ca` | TLS, verifies the certificate chain but not the hostname |
| `verify-full`, `verify` | TLS, verifies the chain and the hostname |

- A failed verification fails the connection. It never falls back to an unverified one.
- `sslrootcert` and the other libpq certificate parameters in the URL are not supported (the driver
  rejects them). Use `DB_SSL_ROOT_CERT` instead.
- The chart mounts the CloudNativePG cluster CA from the Secret `backstop-mcp-pg-cluster-ca` (only
  its `ca.crt`) at `/etc/postgresql-ca` in the server and the migration job, and points
  `DB_SSL_ROOT_CERT` at it. The mount is optional: on a database without that Secret the file is
  absent and the system CA bundle is used, which suits a managed Postgres with a publicly signed
  certificate. For another privately signed database, mount its CA and set `DB_SSL_ROOT_CERT`.
- An overlay that sets `volumes` or `volumeMounts` replaces the chart's lists, so it must repeat the
  `tmp` and `pg-cluster-ca` entries.
- With `postgresql.connection.url` (CloudNativePG's `fqdn-uri` carries no `sslmode`),
  `postgresql.connection.sslMode` applies through `PG_DATABASE_SSL_MODE`. An `sslmode` in the URL wins.
- With `postgresql.connection.host`, `database`, `username`, and `password`, the chart builds
  `DATABASE_URL` itself with `sslmode=<postgresql.connection.sslMode>`, default `verify`.

Migrations (`alembic upgrade head`) read the same variables as the server.

## Authentication and Encryption

| Variable | App default | Description |
|---|---|---|
| `BACKSTOP_MCP_ENCRYPTION_KEY` | none (required) | Fernet key. See [Authentication: Encryption key](./authentication.md#Encryption-Key) |
| `AUTH_LOGIN_MAX_ATTEMPTS` | `10` | Failed logins allowed per Backstop username within the window |
| `AUTH_LOGIN_ATTEMPT_WINDOW_MINUTES` | `15` | Throttle window |
| `AUTH_TOKEN_RETENTION_DAYS` | `30` | How long fully expired OAuth token families are kept as an audit trail before the sweep deletes them |
| `AUTH_UNUSED_CLIENT_RETENTION_HOURS` | `24` | How long a registered OAuth client that nothing references is kept |
| `AUTH_CLEANUP_INTERVAL_HOURS` | `6` | How often the cleanup sweep runs |

Token lifetimes (15-minute access, 30-day refresh) are fixed in code. See
[Authentication: Token lifetimes](./authentication.md#Token-Lifetimes).

## Related

- [Operator Guide](./README.md)
- [Overview](../README.md)
- [Authentication](./authentication.md)
- [Local Development](./local-development.md): the minimum `.env` for a local run, based on the
  commented [`.env.example`](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/.env.example)
- [Architecture: Observability](../technical/architecture.md#Observability)
