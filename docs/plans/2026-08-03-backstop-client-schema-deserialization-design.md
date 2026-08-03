# Design: Schema-validated deserialization in BackstopClient

**Ticket:** UN-22647

## Problem

`BackstopClient.get/post/patch/delete` (`backstop_client/client.py:168-184`) all return
`dict[str, object]`, validated only via `TypeAdapter(dict[str, object])` — i.e. "is this
valid JSON and a top-level object," nothing about shape. Every caller that needs actual
fields (`party_resolver/search.py`, `tools/get_organization.py`) hand-parses the JSON:API
envelope itself with `isinstance` checks and manual `.get("data")` → `.get("attributes")`
walks — duplicated logic, no compile-time guarantee the walk matches what Backstop
actually returns, and a malformed/unexpected shape fails silently (returns `None`, item
just disappears) instead of surfacing as an error.

`paginate()` has the same problem one level deeper: it already validates the JSON:API
*envelope* (`links`, `meta`) via a private pydantic model in `pagination.py`, but each
accumulated item in `PageResult.items` stays an untyped `dict[str, object]` — the envelope
is trusted, the payload isn't.

There's no way today to ask the client "give me back a `PartyAttributes` (or
`OrganizationAttributes`), not a bag of `object`s" — callers either get a raw dict or write
their own parser.

## Solution

### Overview

Every `BackstopClient` method (`get`, `post`, `patch`, `delete`, `paginate`) takes a single
frozen, generic request object instead of loose keyword args — `GetRequest[T]`,
`PostRequest[T]`, `PatchRequest[T]`, `DeleteRequest[T]`, `PaginateRequest[T]` — each
carrying its existing fields (`path`, `params`/`json`, `max_records` for pagination) plus a
new optional `schema: type[T] | None = None`. When `schema` is omitted, behavior is
unchanged: you get back `dict[str, object]` (or `PageResult[dict[str, object]]` for
pagination), validated exactly as loosely as today. When `schema` is provided, the client
validates the response body against it with a `pydantic.TypeAdapter` and returns the
parsed `T` directly — no raw dict, no manual walking.

`PageResult` becomes generic (`PageResult[T]`, `items: list[T]`) so `paginate()` can return
typed items the same way — each accumulated JSON:API resource gets validated against the
given schema after the envelope (`links`/`meta`) is parsed as it is today.

A new `BackstopResponseSchemaError` (alongside `BackstopApiError`/`BackstopAuthError`) wraps
any `pydantic.ValidationError` raised during this schema-checked deserialization, carrying
the request path and schema name for logging — closing a gap where today's bare
`dict[str, object]` validation failure isn't logged at all (it happens after `_request()`'s
try/except).

The three existing callers (`search.py` ×2, `get_organization.py`) get new pydantic models
for the attribute shapes they actually read (`PartyAttributes`, `OrganizationAttributes`)
and a shared generic `JsonApiResource[T]`/`JsonApiDocument[T]` pair for the envelope,
replacing their hand-rolled `isinstance`/`_as_object_dict` parsing.

### Architecture

**Client (`backstop_client/client.py`, `pagination.py`):**
- Five frozen dataclasses, `Generic[T]`: `GetRequest`, `PostRequest`, `PatchRequest`,
  `DeleteRequest`, `PaginateRequest` — same fields each method takes today, plus
  `schema: type[T] | None = None`.
- `BackstopClient.get/post/patch/delete` each take their `*Request[T]` and return `T` (or
  `T | None` for `delete`, matching today's "no content" case).
- `BackstopClient.paginate` takes `PaginateRequest[T]`, returns `PageResult[T]`.
  Internally, `paginate_all` keeps validating the envelope (`_Page`/`links`/`meta`) exactly
  as now, producing raw `dict[str, object]` items; the client then re-validates each item
  against `schema` via `TypeAdapter.validate_python(...)` only if one was given.
- A shared `_deserialize(content, schema, *, path)` helper centralizes the "use
  `TypeAdapter(schema)` if given, else the existing generic dict adapter, wrap
  `ValidationError` as `BackstopResponseSchemaError`" logic, used by all four non-paginate
  methods.

**Shared JSON:API models (new, likely `backstop_client/json_api.py`):**
- `JsonApiResource[AttrT]`: `id: str`, `type: str`, `attributes: AttrT`.
- `JsonApiDocument[AttrT]`: `data: JsonApiResource[AttrT] | list[JsonApiResource[AttrT]] | None`.
- Callers pass `schema=JsonApiDocument[PartyAttributes]` etc. — one generic pair covers both
  single-resource and collection responses.

**Caller-specific attribute models:**
- `PartyAttributes` (party_resolver): `name`, `first_name`/`last_name` (via `AliasChoices`
  for the `firstName`/`first_name` variants the current code already checks),
  `extra="ignore"` since only `id`/`name`/`label` ever leave `search.py`.
- `OrganizationAttributes` (tools): `name: str | None`,
  `model_config = ConfigDict(extra="allow")` — unknown Backstop fields (e.g. `status`)
  survive. `get_organization` calls `.model_dump(exclude_none=True)` on the parsed
  `JsonApiDocument` to rebuild the same dict shape it returns today.

### Error Handling

- **Unchanged paths:** HTTP-level failures (4xx/5xx, 401, network errors) still raise
  `BackstopApiError`/`BackstopAuthError`/`BackstopUnreachableError` exactly as today — this
  refactor only touches what happens *after* a successful HTTP response, at the
  body-parsing step.
- **No schema passed:** identical to current behavior —
  `TypeAdapter(dict[str, object]).validate_json(...)` either succeeds or raises a bare
  `pydantic.ValidationError` if the body isn't even valid JSON/an object. Not touched by
  this change.
- **Schema passed, validation fails:** `TypeAdapter(schema).validate_json(...)` (or
  `.validate_python(...)` for paginated items) raises `pydantic.ValidationError`, caught and
  re-raised as `BackstopResponseSchemaError(path, schema, cause)` — a new exception alongside
  `BackstopApiError` in `errors.py`, also extending `ToolError` so it surfaces the same way
  to MCP callers. It logs via the same `logger` used elsewhere in `client.py`, including
  `path` and the schema's name, which today's failures don't get (they happen outside
  `_request()`'s try/except).
- **Schema passed, validation succeeds:** caller gets back `T` directly — no dict, no
  `None`-on-mismatch silent drops like the current `_candidate_from_resource`/
  `_name_from_organization_body` do. A malformed individual item in a *collection* response
  (e.g. one bad resource among many `quick-search` hits) still fails the whole call rather
  than skipping just that item — a deliberate change from today's per-item leniency in
  `_candidates_from_response`, consistent with "throw on deserialization failure" rather
  than "drop and continue."

### Testing Strategy

Existing test setup: `pytest` + `pytest-asyncio` + `respx` for mocking Backstop HTTP
responses (see `tests/tools/test_get_organization.py`, `tests/party_resolver/`). No new
test infrastructure needed.

**Client-level (new tests, e.g. `tests/backstop_client/`):**
- `get`/`post`/`patch`/`delete` with `schema=None` still return `dict[str, object]`
  unchanged (regression coverage for existing behavior).
- Same four methods with a schema: valid body → returns the parsed model instance; invalid
  body → raises `BackstopResponseSchemaError` wrapping the underlying `ValidationError`,
  with `path` and schema name set correctly.
- `paginate` with `schema=None` still returns `PageResult[dict[str, object]]` unchanged;
  with a schema, a multi-page walk returns `PageResult[T]` with every item parsed, and one
  bad item on any page raises `BackstopResponseSchemaError` for the whole call.

**Caller-level (existing test files updated in place):**
- `tests/party_resolver/test_email.py` / `test_resolve.py` / `test_disambiguate.py`:
  mocked responses already use JSON:API-shaped fixtures (`resource()`/`collection()`
  helpers) — validate against `PartyAttributes` as-is; add one case per file for a
  malformed candidate now raising instead of silently vanishing.
- `tests/tools/test_get_organization.py`:
  `test_unique_search_fetches_organization_and_echoes_resolved`'s
  `result["organization"] == org_body` assertion must keep passing byte-for-byte via the
  `model_dump(exclude_none=True)` round-trip — this is the one behavioral guarantee that
  must not regress.

## Out of Scope

- **`.post`/`.patch`/`.delete` real usage** — they get the same `Request[T]` shape for API
  consistency, but no caller exercises them yet; no new business logic or schemas for those
  verbs beyond the generic mechanism itself.
- **`system_info.py`** — stays on `schema=None` (raw dict passthrough); nothing in the
  codebase reads specific fields from it, so no model is needed.
- **Retrofitting `pagination.py`'s private envelope models (`_Page`, `_PageLinks`,
  `_PageMeta`) into the new shared `json_api.py` models** — they serve a different purpose
  (pagination envelope vs. resource/attributes) and already work; not touched.
- **Changing `_JsonApiError`/`_JsonApiErrorBody` in `errors.py`** — that's the *error*-body
  schema, unrelated to this success-body deserialization work.
- **PEP 696 TypeVar-default mechanics** (making `Request[T]()` default `T` to
  `dict[str, object]` when no explicit type arg is given) — the intended behavior, but the
  exact typing approach (native default via `typing_extensions.TypeVar`, vs. `@overload`
  pairs) is an implementation detail to verify against `basedpyright` during `/implement`,
  not a design decision.
- **Any change to how `resolve_party`/`disambiguate.py` consume `PartyCandidate`** — those
  stay as-is; only how `PartyCandidate` gets built from the raw response changes.

## Delivery sequencing

This work spans two branches:

1. Implement the client-level refactor (tasks 1-5) on
   `backstop-mcp/feat/UN-22647--scafolding` — scoped entirely to `backstop_client/`, since
   `party_resolver/` and `tools/get_organization.py` don't exist on this branch.
2. Rebase `backstop-mcp/feat/UN-23676--party-id-resolver` onto the updated scaffolding
   branch, then fix up the call sites (tasks 6-8) as part of that rebase.

## Tasks

**On `backstop-mcp/feat/UN-22647--scafolding`:**

1. **Add `BackstopResponseSchemaError`** - new exception in `errors.py`, wrapping
   `pydantic.ValidationError` with request path + schema name, extending `ToolError`
   alongside the existing `BackstopApiError`.
2. **Add shared JSON:API resource models** - new `json_api.py` (or similar) with generic
   `JsonApiResource[T]` (`id`/`type`/`attributes`) and `JsonApiDocument[T]`
   (single-or-collection `data`), reusable by any future caller.
3. **Introduce `Request[T]` dataclasses and generic `PageResult[T]`** -
   `GetRequest`/`PostRequest`/`PatchRequest`/`DeleteRequest`/`PaginateRequest` in
   `client.py`, each `Generic[T]` with an optional `schema` field; make `PageResult`
   generic in `pagination.py`.
4. **Wire schema-aware deserialization into `BackstopClient`** - shared `_deserialize`
   helper; update `get`/`post`/`patch`/`delete`/`paginate` to take their new `Request[T]`
   and return `T` (or `PageResult[T]`), raising `BackstopResponseSchemaError` on mismatch.
5. **Add client-level tests** - schema-on vs. schema-off for all four methods, plus a
   multi-page `paginate` case with typed items and a mid-page bad-item failure.

**During the `UN-23676` rebase onto the updated scaffolding branch:**

6. **Define `PartyAttributes` and migrate `party_resolver/search.py`** - replace
   `_candidate_from_resource`/`_display_name`/`_as_object_dict` with
   `GetRequest(schema=JsonApiDocument[PartyAttributes])`.
7. **Define `OrganizationAttributes` and migrate `tools/get_organization.py`** - replace
   `_name_from_organization_body` with typed attribute access; rebuild the `organization`
   dict via `model_dump(exclude_none=True)`.
8. **Update existing party_resolver / get_organization tests** - cover the new
   raise-on-malformed-item behavior; confirm the org round-trip assertion
   (`result["organization"] == org_body`) still passes byte-for-byte.
