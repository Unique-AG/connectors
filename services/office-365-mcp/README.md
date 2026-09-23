# office-365-mcp

For what this service offers, and how permissions and deployment work, read `docs/README.md`.

## Layout

```
src/office_365_mcp/
  app.py                 Compose the app.
  config.py              Configuration classes.
  auth.py                Entra auth setup.
  logging.py metrics.py  Cross-cutting utilities.
  graph_client/          Microsoft Graph transport (official SDK).
  shared/                Code that two or more tools must share.
  tools/                 One file per tool, plus the registry that selects and unions them.
  server/                /ready and /manifest endpoints (not tools).
```

This service owns no database schema and no migrations. The OAuth store creates the service's
only table, `oauth_kv`.

**A tool is one file.** For example, `tools/get_me.py` owns:

- the tool name
- the description
- the Graph permissions
- the arguments
- the output shape
- the Graph request
- the error messages

A new tool needs one file and one line in the registry. A tool needs no base class and no
decorator. A tool module publishes three names: `TOOL_NAME`, `GRAPH_PERMISSIONS`, and `register`.

The file `tools/__init__.py` is the central registry. Its function `resolve()` reads an operator's
selection and returns two things:

- the tool modules to register
- the union of their `GRAPH_PERMISSIONS`, as the scope list that sign-in asks for

The tool modules derive both lists. No person writes them by hand.

Entra must receive every Graph permission at startup. A forgotten permission cannot be obtained
later. For this reason, `create_app` resolves the selection once, then hands the same `Selection`
object to `build_auth` and to `register_tools`.

The test file `tests/test_app.py` reads the tool files from disk. It does this to make sure that
every registered tool's permissions reach the consent screen.

**The `shared/` package is what a file-per-tool design costs.** Two tool files can otherwise
disagree about a shared fact. The `shared/` package lists every fact they must not disagree about:

- `handles.py` owns the `teams:///` grammar:
  - every shape this connector mints
  - the parser for each shape
  - the writer for each shape
  - the permission that each Teams surface reads under
- `messages.py` owns what a Teams message is:
  - the shape a message is answered in
  - the sender, normalized out of every identity shape Graph answers with
  - the Teams HTML that a message body is unwound from
  - the test for "did a person write this"

  One function normalizes this type. So the same message, found by one tool and read by another
  tool, is one type, not two types that must separately agree.
- `meetings.py` owns how a meeting is reached:
  - a join URL, resolved to the meeting it identifies
  - which occurrence of a series a time window means
  - how far "newest first" holds
- `identity.py` owns who the signed-in user is. The tool `get_me` reports this identity, and every
  other answer is correlated against it. This file stops two tools from giving two different
  answers to "who am I".
- `seam.py` owns the Graph client a tool receives, with its per-tool On-Behalf-Of token inside it,
  and the mapping from a Graph failure to advice. A model reads every refusal on this server as one
  voice, so this mapping must live in one place.

A fact belongs in `shared/` under one condition. Two tools each need their own copy of the fact,
and a difference between the two copies is a bug a caller can see. Examples are:

- a handle that one tool mints, which another tool answers with a 404 error
- two different answers to "who am I"
- a refusal that sounds like it comes from a different server

When only one tool owns a fact, that fact does not belong in `shared/`. Examples are:

- a description
- an argument
- an answer shape
- a request
- a refusal

**`handles.py` writes one URL segment for each handle family. Four families use two segments
instead of one.**

Every `teams:///` family, and every `outlook:///` mail family, names a single id. A calendar handle
also names a single id. Microsoft states that a container type has no immutable id, because its
regular ids "were already constant".

An event handle is `outlook:///events/{calendar}/{event}`, two segments. An event id is meaningful
only next to the calendar it was read from. Graph answers a different id for the same meeting in a
delegated copy. The read request needs both halves: `/me/calendars/{calendar}/events/{event}`.
`teams:///transcripts/{a}/{b}` uses the same two-segment shape, for the same reason.

This layout follows seven layering rules:

1. `shared/` imports no tool module. Only `shared/seam.py` imports FastMCP. This keeps the
   framework out of the handle grammar and the rest of the shared vocabulary.
2. `graph_client/` imports nothing from this application. It uses its own frozen `GraphSettings`
   object, instead of reading the configuration.
3. `tools/` imports only `shared/`, `graph_client/`, and FastMCP, and nothing else from this
   package, not even `server/`. A tool file that imports `server/` is a tool file in name only.
4. No tool module imports another tool module. This is what makes each tool independent, and it is
   the reason this layout exists.
5. Only `create_app` constructs a configuration object. Nothing downstream can read the environment
   again on its own and disagree with the app it runs in.
6. `shared/handles.py` is the only module that builds or parses a `teams:///`, `outlook:///`,
   `sharepoint:///`, or `onenote:///` URI. Showing the shape of a URI to a model, in a description,
   an `examples=` field, or a refusal message, is prose. It is not building or parsing a URI.
7. A package is entered through its `__init__` file. The packages `graph_client/`, `server/`, and
   `tools/` each publish an `__all__` list. The `shared/` package deliberately does not. It is a
   grouping whose modules are the real units. Each consumer states which module it depends on, at
   the import line.

The test file `tests/test_layering.py` enforces every rule above, and each rule has its own guard.
When a rule has nothing real behind it, the rule has gone vacuous, and its guard fails. Examples of
a vacuous rule are:

- an empty file tree to walk
- a missing file that the rule forbids reaching past
- a framework that nothing imports any more
- a second tool module that no longer exists, so "another tool module" names nothing
- a package that publishes no `__all__` list

One more rule stops any module from addressing a single meeting recording. Both ways to reach one
recording are defects. Its content is a video that can run thirty hours, and its
`recordingContentUrl` is a Graph URL that only this connector's own token opens. The tool
`tools/teams_list_meeting_recordings.py` returns metadata and availability only, never the recording
itself, and `tests/test_layering.py` enforces this as a failing test.

## Code generation

The Python tool registry, `office_365_mcp.tools`, is the one source of truth for this service. Two
scripts generate files from it, so no person writes those files by hand.

The script `scripts/render-terraform-registry.py` generates
`deploy/terraform/azure/office-365-mcp-entra-application/registry.generated.tf.json`. It imports
the tool modules, the always-on tool, and the presets from `office_365_mcp.tools`. It also imports
the admin-consent table from `office_365_mcp.server.manifest`, and the requestable-permission list
from `office_365_mcp.shared.seam`. Run it with `--check` to find drift between the Python source
and the generated Terraform file. CI uses this mode.

The repo-root script `scripts/render-values-schema.sh` generates this chart's
`deploy/helm-charts/office-365-mcp/values.schema.json`. It merges a shared base Helm schema with
this chart's own `values.additional.schema.json`. It also has a `--check` mode. CI runs this mode
across every chart in the repository, not only this one.

Two tables are the exception. Developers keep them by hand, and no script generates them. This is
the real, bounded risk of drift.

- `NEEDS_ADMIN_CONSENT`, in `server/manifest.py`. When the manifest renders, a runtime assertion
  makes sure that every permission has an entry. No build-time check exists for it.
- `REQUESTABLE_PERMISSIONS`, in `shared/seam.py`. Convention and tests keep it correct, not
  generation.

The function `_stale_promises()`, in `server/manifest.py`, reads every selected tool's description.
When a description names a tool that the current deployment does not expose, `_stale_promises()`
warns about it, and does not fail the build. This is a deliberate design choice, not a gap. Read the
docstring near that function for why.

## Logs

Every log line is one pino-json object, on **stderr**. An operator sets the level with the
`LOG_LEVEL` variable (default `info`). This matches what the chart's pod label,
`logging.unique.app/format: pino-json`, promises the log pipeline.

Nothing goes to stdout. By default, three other sources write outside this contract: uvicorn's
access lines, FastMCP's own lines, and Python warnings. This service routes all three through the
same handler instead, onto stderr as pino-json. The file `src/office_365_mcp/logging.py` states how
and why, for each of the three.

Every line carries a `correlation_id` field, so a reader can always group a line with its related
lines. The value comes from the first of these that exists:

1. the trace id of the active span
2. else, the MCP request id of the message this line is about
3. else, the id of the HTTP request
4. else, the id of this process's own boot

When the service knows `trace_id`, `request_id`, `session_id`, or `http_request_id`, these fields
appear beside `correlation_id`. This service uses an `x-request-id` header from a gateway as-is.

No secret reaches a log line. Two independent nets remove secrets, because a credential with an
innocent-sounding field name, and an innocent-looking credential value, are two different failures:

- **By field name.** A field can have a name similar to a credential name. Examples are
  `Authorization`, `x-api-key`, and `client_secret`, in any spelling. This service replaces that
  field's value with `[Redacted]`. This also applies inside an `extra=` mapping.
- **By value shape.** A value can have the shape of a credential. Examples are a bearer token, a
  JWT, a password in a URL, and a credential in a query string. This service replaces that value
  with `[Redacted]` wherever it appears, including inside an exception's stack trace.

## Run locally

```bash
cd services/office-365-mcp
cp .env.example .env   # fill DB_* and ENTRA_*
uv sync
uv run office-365-mcp
```

This service needs no migration. The database needs an empty schema, and the app user must have
CREATE rights in it. The OAuth store creates its table the first time the service uses it.

Once the service runs, it exposes these endpoints:

- **MCP endpoint**, `http://localhost:9544/mcp`. HTTP, authenticated.
- **Health**, `GET /health`. Reports liveness, through `unique_mcp.monitoring.setup_ops`.
- **Probe**, `GET /probe`. Reports that the process is up, through `setup_ops`.
- **Ready**, `GET /ready`. When Postgres is unreachable, this returns 503. It asks only the OAuth
  store, because that is the only connection a sign-in depends on. Even when sign-in still fails, a
  different connection can report ready.
- **Manifest**, `GET /manifest`. Returns the resolved tool surface and the exact permissions that
  sign-in asks for. It needs no authentication, and it leaks nothing: the authorize URL already
  carries the same scopes.
- **Metrics**, `GET /metrics`. Prometheus, through `setup_ops`. Beside `unique_toolkit`'s own HTTP
  series, four metrics report what this connector asked Microsoft Graph for:
  - `graph_requests_total{operation,status}`
  - `graph_request_duration_seconds{operation}`
  - `graph_throttled_total{operation,retried}`
  - `graph_pages_scanned{operation}`

  The label `operation` is always the tool's own name, never a URL. A label taken from a Graph URL
  creates one time series for each chat, so this service does not use one. The label `status` names
  the remedy a failure needs, for example `forbidden`, `not_found`, `throttled`, or `unavailable`,
  rather than the HTTP status code. The label `retried` states whether the SDK spent its retries on
  the throttling, or refused the wait that Graph asked for.
- **Traces**. Off, unless an `OTEL_*` variable states where to send them.
  - `OTEL_TRACES_EXPORTER=console` prints spans to stderr.
  - `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` sends spans to a collector, and needs no other
    configuration.
  - The file `.env.example` lists this configuration. The chart sets it from
    `internalServices.dependencies.otelTraces.enabled`.
  - Latency stays on `/metrics` only. This service switches off the ASGI instrumentation's own
    duration histogram, so only one series measures latency.
  - No span carries a Graph URL. By default, the SDK sets the full URL as `url.full` in two places:
    the request span, and the URL replacer's own span. This service switches off both, because a
    Graph URL here is almost always a chat id, a message id, or a transcript id. The request span
    keeps `url.uri_template` instead, which is the field a latency breakdown groups by.

## Tests

Integration tests start a Postgres container. Docker must run for this. The app under test creates
the one table it needs, the same way production does.

```bash
uv run pytest
```

## Lint & type-check

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run basedpyright .        # type check
```
