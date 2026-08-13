# Design: on-demand `list_custom_fields` (no glossary prefetch)

## Problem

`tools/list` currently pays for custom-field schema it does not need. Middleware loads a
per-caller Postgres snapshot, refreshes from Backstop if stale, and appends a truncated glossary
onto tool descriptions. That needs a service-account env pair to probe at boot, a TTL snapshot
table, env display-name/alias overlays, and a second full walk of `/lov-entries`. The listing is
large, often truncated, and still tells the model to call `list_custom_fields` for the real
catalog.

The live `entityType` values are Java Beans (`OrganizationBean`, `PersonBean`, `AccountBean`,
`OpportunityBean`, `ProductBean`, `PartyBean`), not the singulars we assumed (`organization`).
Today's normalizer drops those Beans, so the glossary can be empty even after a successful fetch.
`ContactBean` and `EmployeeBean` are not valid Backstop enum constants; `contacts` and `employees`
are party-search types, not schema buckets. Dropdown options already sit on
`attributes.selectOptions`, so the LOV join is wasted work.

`list_custom_fields` exists but takes one entity type, uses the snapshot cache, and returns our
overlay shape (`aliases`, env `display_name`) instead of the definition attributes the model
actually needs (`tabName`, `groupName`, `layoutName`, `resourceType`, `required`,
`selectOptions`, …).

## Solution

### Overview

Replace glossary prefetch with one on-demand tool. `list_custom_fields` takes
`entity_types: list[…]` — at least one of `organizations`, `people`, `accounts`,
`opportunities`, `products`, `party` — plus optional `refresh` (default false). The description
tells the agent not to pass `refresh=true` unless the user says a field is missing.

The tool maps those names to Beans, reads the process-wide catalog, and returns the matching
definitions grouped by requested name. Each definition is the Backstop attributes we care about
(`id`, `name`, `entityType`, `fieldType`, `fieldTypeDisplay`, `isTimeSeries`, `selectOptions`,
`tabName`, `groupName`, `layoutName`, `resourceType`, `required`, `clientRequired`,
`systemDefined`, `description`, …) — no env aliases, no `/lov-entries`.

`CustomFieldsService` keeps owning the catalog, but as a single in-memory list with a 1-hour TTL
and a lock so concurrent cold calls share one fetch. The first authenticated caller paginates
`GET /custom-field-definitions` at `page[limit]=1000` (no `include=lovSet`) and fills the cache
for everyone. Later calls in that hour filter memory. `refresh=true` bypasses TTL and re-fetches.

Remove glossary middleware, `glossary_meta` on other tools, the Postgres snapshot table, the
service-account env vars, boot warmup, the LOV walk, and custom-field env overlays
(`BACKSTOP_CUSTOM_FIELD_OVERRIDES`, `CustomFieldOverrideConfig`, `overrides.py`). `/ready` no
longer reports custom-field schema. Party-search `EntityType` (`contacts`, `employees`, …) stays
unchanged; this tool gets its own type enum so we do not pretend contacts have a Bean.

### Architecture

**Tool** (`list_custom_fields`) — `entity_types: list[CustomFieldEntityType]` (min 1) and
`refresh: bool = false`. `CustomFieldEntityType` is a closed enum: `organizations`, `people`,
`accounts`, `opportunities`, `products`, `party`. It is not the party-search `EntityType`.
Unknown names fail validation before any fetch.

**Bean map** (single table next to the enum):

| Tool name | `entityType` |
|---|---|
| `organizations` | `OrganizationBean` |
| `people` | `PersonBean` |
| `accounts` | `AccountBean` |
| `opportunities` | `OpportunityBean` |
| `products` | `ProductBean` |
| `party` | `PartyBean` |

**Fetch** — `GET /custom-field-definitions` via `BackstopClient.paginate()`, `page[limit]=1000`,
no `include`. Map each resource to a definition (id + the attributes listed above). Skip a row
only when `name` or `entityType` is missing, or `entityType` is not one of the six Beans.

**Service** — one process-wide catalog + `TimedGate` (1 hour, hardcoded) + `asyncio.Lock`.
`get(client, refresh=False)`: if fresh and not refresh, return the list; else fetch, replace,
stamp. Concurrent waiters share the in-flight fetch. No Postgres, no per-subject map, no
overrides.

**Response** — `{ status: "ok", cache: "ok" | "stale", definitions_by_entity: { people: [...],
party: [...] } }` only for requested types, in request order. `entityType` in each item stays the
Bean; the group key is the tool name. `resourceType` is a field on the item, not a filter.
`cache: "stale"` is set when a refresh/TTL fetch failed and the previous catalog was served.

**Wiring** — drop `CustomFieldGlossaryMiddleware` and `warmup_lifespan` from `create_app`. Drop
`BACKSTOP_SERVICE_*`, `BACKSTOP_CUSTOM_FIELD_SCHEMA_TTL_MINUTES`, and
`BACKSTOP_CUSTOM_FIELD_OVERRIDES` from config. `/ready` checks Postgres only. `get_person` /
`get_organization` lose `glossary_meta` and the “call list_custom_fields when truncated” blurb;
they point at `list_custom_fields` with the matching type when the model needs field names.

**Teardown of unused catalog helpers** — `resolve_field`, `read_custom_field_value`, glossary
formatting, LOV join, snapshot/store, and override indexing have no remaining tool caller once
the service is a plain list. Delete them with the service slim-down rather than leave a broken
subject-keyed API.

### Error Handling

**Validation** — an empty `entity_types` list or a name outside the six-value enum is a tool
input error. FastMCP/Pydantic rejects it; we do not call Backstop.

**Cold cache, fetch fails** — the error propagates. There is no schema to serve, and inventing an
empty catalog would look like “this type has no custom fields.” The tool uses the same
Backstop/HTTP error path as other tools.

**Warm cache, `refresh=true` or TTL expiry, fetch fails** — keep serving the existing catalog,
log a warning, set `cache: "stale"`. A 1-hour-old schema is still useful; failing the whole call
would hide fields they could have used.

**Partial pages** — `paginate()` already raises if a page fails. We do not commit a half-walk
into the cache; the previous catalog stays until a full walk succeeds.

**Unknown Bean on a row** — skip that definition (do not fail the catalog). Only the six Beans
are indexed; a new Backstop type is ignored until we add it to the enum.

**Concurrent cold fills** — waiters share one in-flight fetch via the service lock. Two users do
not start two ~10s walks.

**Auth** — fetch uses the calling user's Backstop token. The shared catalog is instance schema;
if a later user's token cannot read `/custom-field-definitions` on refresh, we keep stale (when
present) or error (when cold).

### Testing Strategy

Use the existing pytest setup under `services/backstop-mcp/tests`. No new harness.

**Tool behavior** — `entity_types=["organizations","people"]` returns only those groups; keys are
tool names; items keep Bean `entityType`. `selectOptions` and layout fields (`tabName`,
`resourceType`, …) appear on the mapped object. `contacts` / `employees` are rejected by the
schema. Empty list is rejected. Tool description mentions `refresh` only for a user-reported
missing field.

**Catalog service** — first `get()` paginates at 1000 and caches; second `get()` within the hour
does not call Backstop. After TTL, next `get()` fetches again. `refresh=true` fetches even when
fresh. Concurrent cold `get()`s produce one walk. A failed fetch with no cache raises; a failed
fetch with a cache keeps the old list and reports `stale`.

**Fetch mapping** — `OrganizationBean` → kept under `organizations`; a row with no `name` or an
unknown Bean is dropped; `selectOptions` is copied from attributes; no `/lov-entries` or
`include=lovSet`. Overrides are not applied because they no longer exist.

**Removals** — middleware tests go away with the middleware. App/config tests no longer expect
`BACKSTOP_SERVICE_*`, schema TTL, override JSON, or `/ready`'s `custom_field_schema` check.
`get_person` / `get_organization` no longer declare `glossary_meta`. Snapshot/store/override/
glossary/LOV tests go with those modules.

**Skip** — no live Backstop test in CI. No glossary truncation tests.

## Out of Scope

- **Server-side filter by Bean** — we always walk the full `/custom-field-definitions`
  collection and filter in memory. No `filter[entityType][eq]=…` per requested type.
- **`contacts` / `employees` on this tool** — not accepted; no alias onto `PersonBean` /
  `PartyBean`. Callers that need contact-looking fields use `party` and read `resourceType`.
- **Postgres snapshot, service account, glossary middleware, env overlays** — removed, not
  replaced. `BACKSTOP_CUSTOM_FIELD_OVERRIDES` is deleted; we do not rename CRM ids like `is1`.
- **`/lov-entries` and `?include=lovSet`** — dropdowns use `attributes.selectOptions` only.
  Fields whose options live only on the LOV relationship will have an empty `selectOptions` list.
- **Name resolution / elicitation** (`resolve_field`, `read_custom_field_value`) — unused by any
  tool; deleted rather than rebuilt. If a later tool must resolve a field by nickname, that is a
  new design.
- **Changing party-search `EntityType`** — `contacts` / `employees` stay there. We do not add
  `products` / `party` to that enum.
- **Writing or updating custom field values.**
- **Prefetch on `tools/list` or injecting glossaries into `get_person` / `get_organization`.**
- **Per-user catalogs** — one process-wide list, filled by whoever calls first.
- **Configurable TTL / page size env knobs** — 1 hour and `page[limit]=1000` are hardcoded for
  this fetch. Global `BACKSTOP_DEFAULT_PAGE_SIZE` is unchanged.

## Tasks

1. **Drop glossary prefetch** — Remove `CustomFieldGlossaryMiddleware`, `glossary_meta` /
   `tool_meta.py`, and glossary formatting. Strip `glossary_meta` and the truncated-glossary
   blurb from `get_person` / `get_organization`. Unwire middleware from `create_app`.

2. **Drop service account, warmup, and schema TTL config** — Remove `BACKSTOP_SERVICE_USERNAME` /
   `BACKSTOP_SERVICE_API_TOKEN`, boot `warmup_lifespan`, `BACKSTOP_CUSTOM_FIELD_SCHEMA_TTL_MINUTES`,
   and the `/ready` `custom_field_schema` check. Update `.env.example` and README.

3. **Drop custom-field env overrides** — Remove `BACKSTOP_CUSTOM_FIELD_OVERRIDES`,
   `CustomFieldOverrideConfig`, `overrides.py`, and every `apply_overrides` / `FieldOverride`
   call site. Fetch maps Backstop attributes only.

4. **Drop the Postgres schema snapshot** — Alembic migration to drop
   `custom_field_schema_snapshots`, delete the ORM model, `store.py`, and `snapshot.py`.

5. **Add `CustomFieldEntityType` and the Bean map** — Closed enum for the six tool names, mapped
   to `OrganizationBean` / `PersonBean` / `AccountBean` / `OpportunityBean` / `ProductBean` /
   `PartyBean`. Leave party-search `EntityType` unchanged.

6. **Slim fetch to one paginated definitions walk** — `GET /custom-field-definitions` at
   `page[limit]=1000`, no `include`, no `/lov-entries`. Map id plus layout/dropdown attributes
   (`selectOptions`, `tabName`, `groupName`, `layoutName`, `resourceType`, `required`, …). Skip
   rows with no name or an unknown Bean. Delete `lov.py`.

7. **Slim `CustomFieldsService` to a process-wide 1-hour catalog** — One in-memory list,
   `TimedGate` of 1 hour, single-flight lock, `refresh` bypasses TTL. Failed fetch with a cache
   keeps stale; cold failure raises. Delete subject-keyed snapshot logic and unused
   `resolve_field` / `read_custom_field_value` / index helpers that depended on it.

8. **Change `list_custom_fields` to take `entity_types`** — Required non-empty list of
   `CustomFieldEntityType`, optional `refresh` (default false) with a description that forbids
   using it unless the user reports a missing field. Filter the catalog by Bean, group by
   requested name, return `cache` plus mapped definitions.

9. **Rewrite tests to the new behavior** — Tool grouping/validation, cache TTL/refresh/stale/
   single-flight, Bean mapping, and removal coverage (config, `/ready`, no glossary meta).
   Delete middleware, snapshot, override, glossary, and LOV tests.
