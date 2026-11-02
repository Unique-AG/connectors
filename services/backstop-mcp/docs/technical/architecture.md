<!-- confluence-page-id: 2814083178 -->
<!-- confluence-space-key: PUBDOC -->

## Overview

Backstop MCP is a single Python process: a [FastMCP](https://gofastmcp.com/) server on Starlette and
uvicorn, serving streamable HTTP on `/mcp`. It stores no CRM data beyond in-memory caches and the
caller's own system-user record. Each tool call reads or writes Backstop live, as the calling user,
through one shared HTTP client.

```mermaid
flowchart LR
    subgraph Pod["backstop-mcp pod"]
        MW["HTTP middleware<br/>bearer auth, body limit,<br/>tracing, metrics, 401 rewrite"]
        Auth["OAuth server<br/>+ login form"]
        Tools["Tools<br/>(features/*/tools)"]
        Q["Queries / commands"]
        Cache["In-memory caches<br/>catalogs, report runs"]
        BC["Backstop client<br/>per-user gate, retry,<br/>401 re-check"]
    end
    Client["MCP client"] --> MW
    MW --> Auth
    MW --> Tools
    Tools --> Q
    Q --> Cache
    Q --> BC
    Auth --> DB[("PostgreSQL")]
    BC --> DB
    BC --> Backstop["Backstop REST API"]
```

## Code Layout

```
src/backstop_mcp/
  app.py               builds the app: logging, metrics, FastMCP, tools, routes, lifespan
  main.py              entry point (`backstop-mcp`), loads .env, runs uvicorn
  config.py            one settings class per concern
  dependencies.py      cached providers: configs, engine, Backstop client factory, OAuth provider
  logging.py           JSON logging setup
  metrics.py           OpenTelemetry instruments exported on /metrics
  teardown.py          on shutdown, closes the HTTP pool and database engine, clears cached providers
  server/              how features are exposed over MCP
    instructions.py      server instructions sent to every client
    tools/registry.py    the registered tools (listed in Tools)
    tenant_guidance.py   appends per-deployment text to descriptions
    session_revoked.py   turns a revoked session into HTTP 401
  features/            what the server does, one package per domain
  backstop_client/     HTTP transport to Backstop
  caching/             TTL cache with single-flight fetch
  db/                  SQLAlchemy engine, models, Alembic migrations
  utils/               shared helpers, including log concealment of logins
```

The tree shows the main parts only; a few small top-level modules (`dates.py`, `models.py`, …) are
left out.

Settings are described in [Configuration](../operator/configuration.md); every tool is listed in
[Tools](./tools.md).

`features/` never imports `server/`, and `backstop_client/` never imports `features/` or `config`.
`tests/test_layering.py` enforces these rules, and that every tool file is registered. Features share
one shape (`queries/`, `commands/`, `responses`, `tools/`), each part present only when needed; see
[`AGENT_README.md`](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/AGENT_README.md).

| Feature package | Domain |
|---|---|
| `auth` | Login form, credential storage, encryption, cleanup |
| `party_resolver`, `resolution.py` | Turning a name, email, or id into one Backstop party; the ambiguity policy |
| `org_people`, `org_people_writes` | Organizations, people, employment, addresses |
| `data_hygiene` | Current vs former employment; `as_of` provenance |
| `activity_history`, `activity_writes`, `activity_tags`, `tasks` | Activities and tasks |
| `opportunities`, `opportunity_writes` | Opportunities (the pipeline) |
| `accounts` | Products, holdings, investors, time series, capital flows |
| `custom_fields` | Custom-field catalog, groups, value writes |
| `contact_categories`, `contact_sources`, `system_users`, `time_zones` | Reference vocabularies |
| `reports` | Saved Report Center reports |
| `ui_links` | Building and parsing Backstop UI URLs (no HTTP) |
| `collection_scan`, `bulk_writes`, `includes`, `elicitation_utils` | Shared mechanics: paging, bulk write outcomes, side-loads, delete confirmation |

## HTTP Surface

| Path | Methods | Purpose |
|---|---|---|
| `/mcp` | GET, POST, DELETE | MCP streamable HTTP endpoint. Requires a bearer token |
| `/.well-known/oauth-authorization-server` | GET | OAuth authorization server metadata |
| `/.well-known/oauth-protected-resource/mcp` | GET | Protected resource metadata for `/mcp` |
| `/register` | POST | Dynamic client registration (RFC 7591), open to any client |
| `/authorize` | GET, POST | Starts the OAuth flow; redirects to the login form |
| `/token` | POST | Exchanges codes and refresh tokens. PKCE `S256` |
| `/revoke` | POST | Token revocation |
| `/backstop/login` | GET, POST | The hosted Backstop credential form |
| `/health`, `/probe` | GET | Process is up |
| `/ready` | GET | PostgreSQL is reachable (`503` otherwise) |
| `/metrics` | GET | Prometheus metrics |

FastMCP places its own request-context and bearer-token middlewares outermost: every request carrying
a bearer token is hashed and looked up there, before any of the app's own middleware runs. The app
then adds four, outermost first:

1. **Request body limit**, 4 MiB, the same cap as the MCP SDK's streamable HTTP transport. It also
   bounds the unauthenticated login POST.
2. **OpenTelemetry ASGI** instrumentation.
3. **HTTP request metrics** from `mcp_observability.setup_ops`.
4. **Session-revoked rewrite.** When a tool call confirms the user's Backstop credential is dead,
   this turns the in-flight `200` into `401` so the client reconnects at once. See
   [Authentication: When Backstop rejects the credential](../operator/authentication.md#When-Backstop-rejects-the-credential).

## Request Lifecycle

```mermaid
sequenceDiagram
    participant C as MCP client
    participant S as FastMCP
    participant T as Tool
    participant R as Party resolver
    participant Q as Query / command
    participant BC as Backstop client
    participant BS as Backstop

    C->>S: tools/call (Bearer token)
    S->>S: hash token, load subject
    S->>T: call with validated arguments
    T->>R: resolve "Northwind" in organizations
    R->>BC: GET /quick-search
    BC->>BC: decrypt caller's credential, wait for a slot (max 5)
    BC->>BS: request as the user
    BS-->>BC: candidates
    alt several matches
        T-->>C: ask the user to pick (elicitation)
    end
    T->>Q: run(party id, filters)
    Q->>BC: one or more requests
    BC->>BS: paginate / GET / POST
    BS-->>BC: JSON:API pages
    BC-->>Q: parsed pages
    Q-->>T: published response model
    T-->>C: structured result
```

### Party resolution

Most party-scoped tools accept either `search` (a name or email) or a trusted `party_id` with its
`search_type` (`organizations`, `people`, `contacts`, or `employees`). The four collections have
separate id spaces.

| Input | Lookup |
|---|---|
| `party_id` | Trusted as given. Not looked up, except for an optional name fetch some tools use to echo the name back |
| An email | Exact match on each email field of that collection, separately, merged by id |
| A name | `GET /quick-search` limited to the collection. Quick search is prefix-based, so when it finds nothing, organizations fall back to `filter[name][like]` and people and employees to `filter[lastName][like]` (one page of up to 200). Contacts have no fallback |

The outcome follows one policy, in [`features/resolution.py`](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/resolution.py):

1. One match: resolved. The tool echoes the resolved id, type, and name so a wrong match is visible.
2. Several matches on a single-party call: the user is asked to pick, through MCP elicitation.
3. Several matches inside a batch: everything that resolved plus every unresolved item, in one
   payload, so the model asks once.
4. The client cannot elicit, the user declines or cancels, or nobody answers within
   `RESOLUTION_ELICIT_TIMEOUT_SECONDS`: the same structured candidate list as step 3.
5. No match: `not_found`, naming the query that was used.

The server supports both elicitation styles in the MCP specification: a mid-call `elicitation/create`
request (sent on the standalone GET stream for streamable HTTP), and, for clients on protocol
version 2026-07-28, an `InputRequiredResult` the client answers by calling the tool again.

Products resolve differently, through
[`accounts/resolve_product.py`](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/accounts/resolve_product.py):
quick search misses product short names, so a product name is matched in memory over the whole
product catalog, with an exact short name winning over a longer name that contains it.

## Backstop Client

[`backstop_client/`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/backstop_client)
is the only code that talks HTTP to Backstop.

| Concern | Behaviour |
|---|---|
| **Connection pool** | One `httpx` client per process, up to 100 connections, 20 kept alive |
| **Headers** | `Accept` and `Content-Type: application/vnd.api+json`, and `token: true`. Backstop returns an HTML 404 page for `Accept: application/json` |
| **Authentication** | HTTP Basic with the caller's username and API token, resolved once per client call (`get`, `post`, `paginate`, …), so a 20-page `paginate()` walk decrypts once |
| **Per-user gate** | At most `BACKSTOP_MAX_CONCURRENT_REQUESTS_PER_USER` (5) requests in flight per username, per process. The slot is held for one HTTP request, not a whole tool call, and released while a retry backs off |
| **Timeouts** | `BACKSTOP_DEFAULT_TIMEOUT_SECONDS` (120), or `BACKSTOP_REPORTS_TIMEOUT_SECONDS` (600) for paths containing `/reports` or `/analytics` |
| **429** | Classified from the body as concurrency, minute, hour, or day. Only concurrency `429`s are retried. The wait is `Retry-After` (at least 1 s) or exponential backoff of 1 s, 2 s, 4 s… plus up to 1 s of jitter. A request gets at most `BACKSTOP_MAX_RETRY_ATTEMPTS` (5) attempts in total, and a retry happens only when the wait before jitter is at most `BACKSTOP_MAX_RETRY_WAIT_MS` (30 s) |
| **Nothing else retries** | 5xx responses, timeouts, network errors, and `429`s whose limit cannot be classified fail the call at once |
| **401** | Re-checked by probing `/system-info` with backoff (1 s, 2 s, 4 s…) within 10 seconds. The session is revoked, and the call answered with HTTP `401`, only if every probe returns `401` or `403`. Otherwise the call fails with a retryable tool error and the session is kept |
| **Pagination** | JSON:API `page[limit]` / `page[offset]`. Page size is `BACKSTOP_DEFAULT_PAGE_SIZE` (100), or `BACKSTOP_REPORT_PAGE_SIZE` (500, the maximum) for `/reports` and `/analytics`. Follows `links.next`, or fetches pages in parallel by offset where the total count is reliable. Offsets stay multiples of the page size, which Backstop requires. A walk stops at 10,000 records by default and marks the result truncated |
| **Errors** | Backstop's JSON:API `errors[]` are logged and surfaced to the model as tool errors |

## Paged Searches

`search_organizations`, `search_people`, `search_opportunities` (rows mode), and `search_activities`
(rows mode) return about `SEARCH_RESULT_SIZE` rows per call, plus a `continuation` with an opaque
`cursor` when more may match. The first three return at most that many. `search_activities` reads
whole pages until it has at least that many, so it can return up to about twice as many.

- Many filters are applied in memory after the read, because Backstop rejects them as query filters.
  A search therefore reads Backstop pages until it has a full page of matches or reaches the end.
- The cursor stores the position of the next unread record and a fingerprint of every other
  argument. Reusing it with different arguments is rejected rather than returning rows from a
  different query.
- Organizations, people, and opportunities are read in id order (`sort=id`). Backstop orders records
  that tie on a sort field differently between requests, and `/people` returns `500` for
  `sort=name`, so offset paging by name would repeat or skip rows.
- Aggregate modes (`mode="aggregate"`) read every match in one call and return counts, without a
  cursor.

## Caching

All caches are in process memory: each pod keeps its own, and they are lost on restart. Catalogs are
shared by every user of the pod; report runs are per caller.

| Cache | Contents | Lifetime |
|---|---|---|
| Custom-field definitions and groups | Tenant schema, shared by all users | 120 minutes, on by default |
| Activity tags, contact sources, contact categories, system users, time zones | Small vocabularies | 24 hours when enabled, off by default |
| Opportunity stages, entity-relationship types | Small vocabularies | 60 minutes, always on |
| Report runs | One running or finished `run_report` page, keyed by caller, report, date, limit, and offset | 1 hour, at most 1,000 runs |

Catalog caches use one shared fetch for concurrent callers. With the cache flag off, that sharing
still happens, but nothing is kept afterwards. The catalog caches hold instance-wide schema rather than
per-user data: custom-field definitions carry no permission attribute in Backstop.

If a refresh fails, a catalog whose cache is enabled keeps serving the previous value (the
response's `cache` field says `stale`). With the cache off, the default for the small vocabularies,
the failure reaches the caller. Opportunity stages and entity-relationship types never serve stale.

## Persistence

PostgreSQL holds only authentication state:

- `backstop_credentials`: one row per Backstop username, with the Fernet-encrypted credential and the
  system-user record captured at login.
- `mcp_auth_*`: OAuth clients, pending authorizations, authorization codes, hashed tokens, login
  attempts. These tables come from the shared
  [`mcp-credential-auth`](https://github.com/Unique-AG/connectors/tree/main/packages/mcp-credential-auth)
  package.

Every request with a bearer token reads the token table, which is why `/ready` depends on the
database. Schema changes are Alembic migrations in
[`db/migrations/versions/`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/db/migrations/versions).
See [Authentication: Data stored](../operator/authentication.md#Data-Stored).

## Observability

### Logs

Structured JSON on stderr, through `mcp_observability.configure_logging` (the chart labels pods so
Loki parses it). FastMCP, uvicorn and Python warnings join the same stream.

A message is a fixed sentence and values stay in `extra`, never interpolated, so every occurrence of
a line has the same `msg` and groups in Loki: `Fetched tasks for party`, `Backstop request failed`,
`Login rejected`, `Applied tenant guidance`. Outcomes are past tense, state is present tense, with
no trailing period and no ids in the text.

`LOG_LEVEL` is the level of the `backstop_mcp` loggers. `LIBRARY_LOG_LEVELS` sets libraries over
defaults that keep `httpx` and `httpcore` at WARNING, because their INFO lines are request URLs
with query strings, and `sse_starlette` at INFO, because its DEBUG lines are tool results.
FastMCP's DEBUG line that prints a tool call's arguments is dropped.

Identifying values go through `identifiable_value`: Backstop logins are `hmac-sha256:<hex>`, keyed
with a secret derived from `BACKSTOP_MCP_ENCRYPTION_KEY`, plain `sha256:<hex>` at `LOG_LEVEL=debug`,
and the value itself with `LOGS_DIAGNOSTICS_DATA_POLICY=disclose`. That covers the Backstop
client's request and re-check lines and the login lines (`Login succeeded`, `Login rejected`,
`Login throttled`), which carry the keyed username only, and every search term, `representative`,
report name and stored login a tool logs. API tokens are never logged.

What a line may carry:

- Safe raw fields are Backstop record ids, our `subject`, enums defined in our code (`kind`,
  `segment`, `mode`, `source`, `series`, `stream`, resource types), counts and lengths, presence
  flags, the HTTP status and JSON:API `code`, route templates, durations, argument and field
  names, figure names, the date windows the caller asked for, and an IANA `time_zone`. Search
  filters are logged as presence flags (`has_name`) and counts, and a stage as `stage_id`.
- No URL. The client logs the `route` template, never the path: from page 2 the path is the
  `links.next` URL with the search filters in its query string. `path`, `url` and `next_path` reach
  no log or span except as the argument of `metric_route()`.
- No Backstop error text. `Backstop request failed` and `Backstop rejected the credential` keep
  `status_code`, the JSON:API `code` and `error_count`, and drop `detail`, `title`, `errors` and the
  body, which can echo what the caller submitted.

Levels: a Backstop 4xx or 5xx or a timeout is WARNING without a stack, because it is not a bug. A
broad `except Exception` fallback logs at `failure_level(exc)`, so a bug there is still ERROR with
its scrubbed stack. A successful delete is WARNING on purpose, so a destructive write stands out.

One line per call, not per row: unreadable rows, failed fan-out items and duplicate catalog ids
become one WARNING per call with `count` and `sample_ids` (at most five), and the per-row detail is
DEBUG. Tools write no `started` or `completed` line of their own; the tool-call middleware's lines
carry the declared arguments.

Exception text is kept out of logs, because a pydantic error quotes its input and a Backstop error
can quote a record. A line logged with an exception names it in `error_type`; below ERROR it has
no stack, and at ERROR its `err` keeps the frames and exception types but no message. A pydantic
validation error, or one it was raised from (even `from None`), adds `failed_fields`: the path,
the error type and the type of the input of each error, never the input, such as
`data.3.attributes.title (string_type, got int)`. Ten are listed and `failed_field_count` gives
the total: one broken field fails once per record, and a page holds thousands. The path is
pydantic's own, so a model must never be keyed by a name or another value.
`ERROR_DETAILS_POLICY=disclose` keeps the message and full stack at ERROR. It is separate from
`LOGS_DIAGNOSTICS_DATA_POLICY`, so reading an error does not also disclose every login.

`ToolCallObservabilityMiddleware`, the outermost FastMCP middleware, logs `Tool call started`
and exactly one of `Tool call completed`, `Tool call failed` or `Tool call cancelled` per call,
with `tool`, `argument_names`, `subject` (our internal user id), `duration_ms` and the values the
tool's `@trace_arguments` declared. A failure is logged at its level: WARNING when the caller or
Backstop caused it, ERROR when a developer has to act; an exception class declares its own level
with `DeclaresFailureLevel`. An invalid argument is named in `failed_fields` without its value.
FastMCP's own per-call failure lines and `setup_ops`'s per-call line for a tool are dropped,
because they repeat these and can quote the caller's input.

### Metrics

Served on `/metrics` in Prometheus format. `setup_ops` contributes the HTTP request metrics and the
`mcp_*` tool metrics; the rest are defined in `metrics.py`.

| Metric | Type | What it tells you |
|---|---|---|
| `backstop_requests_total` | Counter (`method`, `route`, `status`) | Upstream Backstop calls and their status codes |
| `backstop_request_duration_seconds` | Histogram (`method`, `route`) | Latency of one Backstop request |
| `backstop_concurrency_wait_seconds` | Histogram (`route`) | Time waiting for a per-user slot. Rising values mean users hit the 5-request limit |
| `backstop_rate_limited_total` | Counter (`limit_kind`, `retried`) | `429`s. `retried=false` with `limit_kind=day` is a quota problem |
| `mcp_calls_total` | Counter (`kind`, `name`, `status`) | Tool calls by tool and outcome (the exception class name on failure) |
| `mcp_call_duration_seconds` | Histogram (`kind`, `name`) | Tool-call latency |
| `backstop_filter_ignored_total` | Counter (`endpoint`, `filter`) | `search_activities` found rows that contradict a filter Backstop accepted |
| `custom_field_schema_loads_total` | Counter (`source`) | Custom-field definition loads, by source (`backstop`, `stale`) |
| `catalog_get_duration_seconds` | Histogram (`catalog`, `served`) | Every catalog read and what answered it: `backstop`, `coalesced`, `cache`, `stale`, `error`, `cancelled` |
| `catalog_fetch_duration_seconds` | Histogram (`catalog`, `outcome`) | Actual catalog walks. Subtract its `_count` from the previous one for requests the cache avoided |

The chart's `BackstopFilterIgnored` alert fires when `backstop_filter_ignored_total` increases over
15 minutes. In `search_activities`, rows that contradict a filter are dropped and the filter is named
in `server_filter_ignored`.

### Traces

`mcp_observability.configure_tracing` installs a trace provider when an `OTEL_*` variable turns
tracing on (see [Configuration: Tracing](../operator/configuration.md#Tracing)), before FastMCP is
built. The ASGI middleware spans each HTTP request except `/health`, `/probe`, `/ready` and
`/metrics`, without `send`/`receive` child spans and without a second HTTP duration histogram on
`/metrics`. FastMCP opens a `tools/call <tool>` span inside the request, in the trace of the
request that carried the call, and the `run` method of every query and command opens a span inside
that, named after its class (`GetTasksForPartyQuery.run`). The Backstop client opens the only
hand-written span.

Each logical Backstop request, retries included, is one CLIENT span named
`backstop <METHOD> <route>`, with `http.request.method`, the route template as `url.template` and
`http.response.status_code` (a 401 included). It never carries the path, the URL or the query
string: from page 2 the path is the `links.next` URL with the search filters. Only a 5xx or a
transport error marks it as an error, with `error.type` and no message. Each Backstop error type
declares how loud its tool call's failure line is with `DeclaresFailureLevel`: a schema mismatch is
ERROR, a revoked session INFO, the others WARNING. A schema mismatch names the schema and its
up to ten `failed_fields`, never pydantic's text, which quotes the record; the pydantic error stays on
`.cause` and is not chained.

FastMCP records every exception a tool raises on its span, with the message, the stack and the
message again as the status description, and has no option to stop. A message can quote the
caller's input or a Backstop record. So, unless `ERROR_DETAILS_POLICY=disclose`, the span
processor `ErrorDetailsRedaction` rewrites each span as it ends, before export: an `exception`
event keeps `exception.type` and a stack of frames and exception types, as an ERROR log line
does, and loses `exception.message`; the status keeps its code and loses its description. It does
not judge whether the caller or a bug caused the failure. The SDK ignores `set_status` once a span
has ended and offers no way to edit events, so the processor replaces the span's private `_status`
and `_events`. An SDK upgrade can break it; `mcp-observability`'s tests catch that.

What a span carries is declared on the code it describes, from `mcp_observability`:

- `@trace_arguments("search_type", "party_id", "status")`, under `@tool`, puts those arguments on
  the `tools/call <tool>` span as `tool.argument.<name>` and on the tool call's log lines. It
  opens no span.
- `@traced(arguments=("search_type", "entity_id"), result=lambda r: {"total": r.total})` on a
  query or command `run` opens a child span named `<Class>.run`, with the arguments as
  `input.<name>` and the result as `result.<name>`. On an exception the span gets status ERROR
  and `error.type`, no message.
- An argument is a name, or a dotted path into a pydantic input model (`"person.owner_login"`).
  `identifying=` values (logins, names) are hashed through `identifiable_value`. Strings,
  numbers, booleans, `Literal`s, enums (as their value), dates (ISO) and sequences of those may
  be declared. Nothing is traced unless declared.
- `create_app` calls `validate_trace_declarations()`: an unknown argument or field, an annotation
  that does not resolve or a type that cannot go on a span crashes the app at startup, naming the
  function, the path and the reason. A test runs the same check in CI.
- A lambda (`arguments=lambda args: {...}`) is the escape hatch for a computed value. It is not
  checked at startup or by the type checker.
- Tracing never fails the call: a value that cannot go on the span is skipped with one WARNING
  (`Trace attribute skipped`) naming the function and the argument, never the value. A path
  through `None` is skipped silently.

No log line is written to a span and no span is read by the logging. The only thing they share is
`trace_id`, `span_id` and `trace_flags` on each log line, for correlation.

## Related Documentation

- [Technical Reference](./README.md)
- [Overview](../README.md)
- [Features](./features.md)
- [Tools](./tools.md)
- [Authentication](../operator/authentication.md)
- [Configuration](../operator/configuration.md)
