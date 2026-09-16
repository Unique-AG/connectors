# Agent coding guide for backstop-mcp

Read this before adding, changing, or refactoring a feature. Two references:

- Reads: [`src/backstop_mcp/features/opportunities/`](src/backstop_mcp/features/opportunities/)
- Writes: [`src/backstop_mcp/features/activity_writes/`](src/backstop_mcp/features/activity_writes/)

When this file and a read feature disagree, opportunities wins. When this file and a write
feature disagree, activity_writes wins. Do not invent a third shape.

Backstop behaviour is a different question — use the `backstop-api` skill and live `GET`s
before designing from swagger. The live instance is read-only: never `POST` / `PATCH` /
`PUT` / `DELETE` against `BACKSTOP_BASE_URL` unless the user says so for that task, and
then delete what you created and verify the `GET` 404s. Writes designed from swagger alone
have been wrong every time so far — see "Write tools and commands" and "Write payloads"
below.

---

## agent-explore (developer utility)

[`agent-explore/`](agent-explore/) is a local CLI for reading the live REST API and the
Elevio help center. It is **not** part of the shipped MCP server. `src/backstop_mcp/`
and `tests/` must not import it, load its caches, or mention its paths. Its own
helpers are tested beside the scripts, not from the product suite. Feature tests pin
wire behaviour with respx fixtures, not by reading those caches.

Credentials live in `agent-explore/.env` (copy `.env.example`). Do not print them.
Run the scripts from `services/backstop-mcp` so `uv run` picks up the service venv.

| Script | What it does | Cache (gitignored) |
|---|---|---|
| `explore.py` | `GET` only against `BACKSTOP_BASE_URL` (API token). 2-minute timeout. | `.probe-cache/` |
| `docs.py` | Elevio help via help-prod SSO (web username/password). Never POST to the CRM. | `.docs-cache/` |
| `test_set.py` | Optional local question harness. Not CI. | `.test-set-runs/` |

Reuse a cached probe instead of hitting the API again. Do not rewrite these scripts.
The `backstop-api` skill is the workflow; this folder is the tooling.

---

## Deprecated layout (do not copy)

The catalog trio, `tasks`, `org_people`, `accounts`, `activity_history`,
`party_resolver`, and `activity_writes` already follow the opportunities layout. Do not copy leftover `fetch_*` files into new work
(`accounts/utils/fetch_series.py`). That name stays only because it still has callers; it
is not the template. Do not add a `fetch_*` filename ban while it exists.

What that older layout did, and what to do instead:

| Deprecated | Current (opportunities) |
|---|---|
| `fetch_<thing>.py` at the feature root, named after a function | `queries/<thing>_query.py` named after a `*Query` class with `run(...)` |
| Tool file owns the large `*ResolvedResponse` | Published models live in `responses.py`; the tool stays small |
| Type aliases (`Literal[...]`) dumped in `internal_dto.py` | Keep small types on the query that owns them |
| Outsiders import `features.<pkg>.fetch_person` or a sibling file | Outsiders import `from backstop_mcp.features.<pkg> import …` |
| Mapper / service grows a wrapper just so a query can call it | Inject the real collaborator (`CustomFieldsService`, not `load_custom_fields_catalog` on the mapper) |
| One `fetch` does HTTP, mapping, and filtering | Query/command does one logical operation; `utils` are reused helpers |

The layering tests still *allow* the old shapes so existing features keep compiling. Allowance
is not the standard.

---

## Feature shape

```
features/<name>/
  __init__.py              public door: __all__ is the whole of what the feature promises
  dependencies.py          factories; @lru_cache only for process-wide services
  api_responses.py         *Attributes / wire resources — or api_responses/ if this grows
  responses.py             *Response published models — or responses/ if this grows
  internal_dto.py          only if you have real *Dto classes
  queries/
    __init__.py
    get_<name>_query.py    Get<Name>Query — one logical read
  commands/
    __init__.py
    <name>_command.py      <Name>Command — one logical write (edits on data)
  utils/
    __init__.py
    map_<x>_to_response_util.py
    …                      functions reused in more than one place inside the feature
  tools/
    get_<name>.py          the MCP endpoint; name matches the file
  <name>_service.py        only if there is a long-lived catalog / vocabulary
```

`api_responses` and `responses` start as a file. When either grows past one coherent
module, make it a package (`api_responses/`, `responses/`) whose `__init__` re-exports
the same names. Layering still matches the `api_responses*` / `responses*` prefix.

`utils/` is the name for reusable helpers. Opportunities still calls this
`resource_utils/` — same role, do not add a second package beside it, and do not rename
that folder unless the task is the rename. New features use `utils/`.

Vocabulary modules keep those names: `api_responses*`, `internal_dto*`, `responses*`,
`dependencies.py`, `entity_types.py`, `settings.py`. Every other logic file is named after
the symbol it defines (`get_opportunities_query.py` → `GetOpportunitiesQuery`).
`tests/test_layering.py` rule 6 enforces that.

A feature that is only a couple of functions does not need empty `queries/` / `commands/` /
`utils/` packages. Add a package when a second query, a command, or a shared helper
appears — do not invent structure for one file.

`commands/` is the write side. Do not exercise a command against the live tenant in
`agent-explore/.env` unless the user asks for that task; when they do, delete every record
you created and verify the follow-up `GET` 404s. See "Write payloads" for the wire shapes
Backstop actually accepts.

---

## Names and suffixes

File names follow the folder they live in. The suffix is the type; the stem is the symbol
`tests/test_layering.py` rule 6 checks. Do not invent `fetch.py`, `service.py`, `helpers.py`,
or a file named after a mechanism.

| Folder | File | Symbol |
|---|---|---|
| `queries/` | `get_opportunities_query.py` | `GetOpportunitiesQuery` |
| `commands/` | `close_opportunity_command.py` | `CloseOpportunityCommand` |
| `utils/` | `map_opportunity_to_response_util.py` | `MapOpportunityToResponseUtil` |
| `queries/` or `commands/` | `_json_api_utils.py` | several small private functions |
| `tools/` | `get_opportunities.py` | `get_opportunities` |
| feature root | `opportunity_stages_service.py` | `OpportunityStagesService` |
| `responses` | `*Response` classes | published MCP models |
| `api_responses` | `*Attributes` / resource types | wire shapes |
| `internal_dto` | `*Dto` classes only | internal projections |

**`_util` is one symbol; `_utils` is a private module of several.** A public helper in
`utils/` is singular and named after the one thing it defines
(`map_opportunity_to_response_util.py` → `MapOpportunityToResponseUtil`). A `_`-prefixed
sibling inside `queries/` or `commands/` is plural — `_<subject>_utils.py` — because it
holds a handful of small functions and no single symbol to name it after; rule 6 exempts it
for exactly that reason. When the subject turns out to be a single symbol, drop the `_utils`
and take its name (`extract_collection.py` → `extract_collection`).

The subject still has to be in the name. `_file_data_utils.py` and `_json_api_utils.py` say
what they hold; `_utils.py` and `_attachment_utils.py`, which those two replaced, did not.
Reach for one of these modules only when a second caller inside the folder appears; until
then the helper is a private method on the query or command.

A name that has to cover two subjects is worth a second look, not an automatic split. A few
small functions that the same callers use together stay together — the extra module and its
import line cost more than the broad name does. Split when the **callers** diverge:
`extract_collection.py` came out of `_json_api_utils.py` because only
`update_activity` and `delete_activity` resolve a path, while every log and attach command
was importing routing code it never called. That is the signal — two groups of functions
with two different sets of callers — not the word count in the filename.

The class, the factory, the injected parameter, and the instance attribute should read as
the same thing: `GetOpportunitiesQuery`, `get_opportunities_query_factory`,
`get_opportunities_query: GetOpportunitiesQuery`, `self._get_opportunities_query` (or the
public `self.map_opportunity_to_response_util` when the query holds a util it calls). A
reader following a request should not have to translate `mapper` → `MapOpportunityToResponseUtil`
→ `self._proj`.

Inside a class, names describe the data, not the step. `opportunities_mapped`, `pages`,
`catalog`, `selected` is a flow you can read top to bottom. `tmp`, `data`, `result2`,
`items_list` is not. Prefer the name the next line will use: if you filter by status, the
input is `opportunities_mapped` and the output is `selected`, not `filtered_data`.

Name the check that runs, not a leftover flag or a longer phrase the arguments already
say. `_has_completed_status` not `_is_actual`. `raise_if_invalid_series` not
`raise_if_invalid_series_for_entity`. `_series_or_figure_error` not `_accepted_series`.
The file stem is that short name.

---

## Local helpers (do this on the first draft)

These are the review nits that kept coming back while moving `accounts` onto queries.
Later slices should not need the same pass.

**Private methods on the query, not module-level `_` functions.** `_params`, `_fields`,
`_project_row` belong on `GetXQuery`. A `_time_series_params` sitting next to the class is
the old `fetch_*.py` with a class stapled on.

**Inline a value used once.** Do not extract `_SORT = "sort"` or
`_ACCOUNT_FIELDS = "date,value,valueStatus"` for a single call site. Write the string
where it is sent. A named constant is for a second use, or a value tests and docs must
share.

**Keep `schema=` as a real assignment.** `SeriesPointResource = BackstopApiResource[SeriesPointAttributes]`
stays — `schema=` needs a class object; a PEP 695 alias is not `type[T]`. That is not a
one-use constant to inline.

**Do not wrap a single call.** If `_series_figure` only calls `fetch_series(self._client, path)`,
delete it and call `fetch_series` at the site.

**One pass.** Filter and project in the same loop. Do not build "kept rows" and then map
them. A projector that always succeeds returns the row (`assert account is not None` to
narrow); the loop drops the unusable input *before* calling it, instead of
`from_attributes` returning `None`.

**A util needs two callers inside the feature**, unless the review asked for the util
anyway (`raise_if_invalid_series` lives in `utils/` by request). Do not invent a second
helpers package.

**`Included` is the shared include API.** `backstop_client.Included` / `included_resource` /
`IncludedResource` is what every feature uses to read `?include=` chips. Do not grow a
second follow/index helper in a feature. Call-site updates in leave-alone packages are
part of keeping that one API, not a drive-by rewrite. Warn when a chip is dropped
(`includes.side_load.unreadable` from `include_plan`; `org_people.side_load.unreadable`
when `Included.by_type` drops an employment chip).

---

## Data flow

Prefer the obvious path. A query that paginates, maps each row, filters, sorts, and returns
is correct even when a clever pipeline, a cache of intermediate shapes, or an extra
fan-out would be faster on paper.

A complicated flow is allowed only when it is justified **with real measurements** — a
probe, a histogram already on `/metrics`, a timed walk against this instance — and the
comment says what was measured and what the complexity buys. The search walk indexes
`included` once because 1,206 rows would otherwise rebuild that map thousands of times;
the catalog load overlaps the walk because a cold `join_values` waits until the last page.
Those are measured. "It might be slow" is not.

Do not add `asyncio.gather`, parallel page fetches, or a second in-memory index "just in
case". Do not split a straight loop into a pipeline of helpers so the query looks smaller.
Simplicity is the default; performance is an exception you can point at.

---

## Imports

A package is entered through its `__init__`. `__all__` is the contract; reaching past it is
how collaborators get assembled twice and `create_app`'s config is ignored
(`tests/test_layering.py` rule 4).

**From outside the feature** (tools in other features, `teardown.py`, tests that are not
tool-module tests):

```python
from backstop_mcp.features.opportunities import (
    GetOpportunitiesQuery,
    OpportunitiesResolvedResponse,
    OpportunityStatus,
)
```

**Inside the feature**, import sibling *packages*, not sibling *files*:

```python
from backstop_mcp.features.opportunities.queries import GetOpportunitiesQuery
from backstop_mcp.features.opportunities.resource_utils import MapOpportunityToResponseUtil
```

New features import `…utils` the same way. Opportunities still uses `resource_utils`.

Never `from backstop_mcp.features.opportunities.queries.get_opportunities_query import …`
from outside `queries/`. Same for `commands/` and `utils/`.

**Exceptions that stay:**

- A file inside `queries/`, `commands/`, or `utils/` may import its own sibling file when a
  package import would cycle (`map_opportunity_to_response_util` → `get_stage_history_query`).
- `api_responses` / `responses` import each other downward only
  (`responses` → `internal_dto` → `api_responses`). Never upward. A small shared
  `Literal[...]` that the query, published response, and tool all need lives in a
  feature-root file named after the alias (`time_series_name.py` → `TimeSeriesName`)
  so the query file does not cycle with `responses`. Do not park it on `internal_dto`.
- Tool tests may import `features.<pkg>.tools.get_*` (the tool is reached by being
  registered, not as a public surface). They still enter the rest of the feature through
  `__init__`.
- `server/tools/registry.py` imports each tool module the same way.

A `TYPE_CHECKING` import of package A from package B, while B is already imported by A's
`__init__`, is still a cycle for basedpyright. Do not type a util with a query-owned alias
if that forces `utils` → `queries`. Repeat the small `Literal[...]` inline, or
split the type into its own file once it is no longer small.

`features/` must not import `server/`. `backstop_client/` must not import `features/` or
`config`. `teardown.py` imports feature factories; features must not import `teardown`.

---

## Models

Three layers, one direction:

1. **`api_responses`** — `*Attributes` / `BackstopApiResource[...]`. Every field optional,
   every scalar lenient (`LenientStr`, `LenientDate`, … in `lenient.py`). `extra="ignore"`.
   `client.paginate` deserializes a whole page; a required field or a strict type fails every
   row on one bad record. `schema=` is this layer — never a published `*Response` or
   `dict[str, object]`.
2. **`internal_dto`** — `*Dto` only. Skip the file when there are none. Do not park
   `Literal` aliases here. Do not hop wire → `*Dto` → `*Response` when the query can map
   Attributes onto the published model in one pass.
3. **`responses`** — `*Response`. This is the published MCP output schema. Every model has
   a docstring; every field has a `Field(description=...)`. A number with no unit or a stage
   name with no direction is where a reader guesses wrong.

Shared project types (`OmitNoneModel`, `StrippedStr`, `NonEmptyStr`, `CoercedId`,
`published_output_schema`) live in `models.py`. Lenient scalars live in `lenient.py`.
Do not re-declare them per feature.

Backstop camelCase arrives as `validation_alias`, not `alias`, so the schema and
`model_dump` stay snake_case. `populate_by_name` is what still accepts either spelling.

**Tool return types:**

- Large published models go in `responses.py` so the tool file stays small. See
  `OpportunitiesResolvedResponse`, `GetOpportunitiesByIdsResponse`,
  `SearchOpportunitiesResolvedResponse`.
- A small union may stay in the tool file:

  ```python
  type GetOpportunitiesResponse = (
      PartyAmbiguousResponse | NotFoundResponse | OpportunitiesResolvedResponse
  )
  ```

- The query's own payload can be a separate model (`PartyOpportunitiesResponse`) when the
  tool still has to wrap it with `resolved` / status. Do not collide those two names.

No model declares `extra="forbid"`. `extra="allow"` only where passthrough is the point
(`PersonRecordResponse`).

---

## Queries, commands, utils, tools

A **query** or **command** does one logical operation. It may call other queries or
commands to get there, but the unit is still one thing the caller asked for — "this
party's pipeline", "these ids", "close this deal" — not a grab-bag of HTTP. Queries read;
commands write. Neither resolves a party and neither publishes MCP annotations.

```python
class GetOpportunitiesQuery:
    async def run(...) -> PartyOpportunitiesResponse: ...

class CloseOpportunityCommand:
    async def run(...) -> ...: ...
```

**Utils** are functions (or small classes) reused in more than one place *inside this
feature* — project a record, aggregate a list, resolve a side-load. If only one query
calls it, keep it on that query until a second caller appears. A util does not grow a
method that is only a pass-through to another feature. The opportunities mapper joins
custom-field *values*; the query injects `CustomFieldsService` and loads the catalog
itself.

**Tool** is the MCP endpoint: the place the request comes together. It structures the
conversation — elicitation, party resolve, id coercion — and then calls queries and
commands. Ideally it calls **one** query or command to fulfil the request. Calling
several is fine when the user-facing operation is genuinely several logical steps
(resolve, then fetch, then maybe a follow-up write); do not push that orchestration down
into a query so the tool stays "thin" on paper.

One `@tool` per file, name equals filename, registered on `TOOLS`. Collaborators are
`Depends(...)` parameters and stay out of the published schema.

```python
from backstop_mcp.features.opportunities import GetOpportunitiesQuery, OpportunitiesResolvedResponse
from backstop_mcp.features.opportunities.dependencies import get_opportunities_query_factory
```

`dependencies.py` is a vocabulary module at the feature root — tools may import that file.
They still import types and query classes from the feature package.

Small owned types stay on the query:

```python
# queries/get_opportunities_query.py
type OpportunityStatus = Literal["open", "closed", "all"]

# queries/search_opportunities_query.py
type SearchMode = Literal["rows", "aggregate"]
type OpportunityGroupBy = Literal["stage", "product", "period", "party"]
```

Export them from `queries/__init__.py` and the feature `__init__`. Split to a types file
only when the set is no longer small.

---

## Write tools and commands

Reads copy `features/opportunities/`. Writes copy `features/activity_writes/`. The first
draft of UN-23684 designed payloads from swagger, then every live create returned `400`.
The patterns below are what that review settled on — do not re-litigate them into one
write service or a `mode=` flag.

**Split tools when the annotations cannot tell the truth.** One `ToolAnnotations` set
cannot honestly cover an additive create, a replacing PATCH, and a permanent hard delete.
`log_activity` is `destructive_hint=False`; `update_activity` and `delete_activity` are
separate tools with `destructive_hint=True` so the host approval prompt is the
confirmation. A `mode=` flag on one tool is how that honesty is lost.

**Put a multi-megabyte field on its own tool.** `attach_file` is separate so the everyday
note-taking schema never carries a base64 blob. FastMCP's `RequestBodyLimitMiddleware` is
4 MiB (`DEFAULT_MAX_REQUEST_BODY_SIZE`) and does not accept an override — derive the
published cap from that constant (`attach_file_max_bytes.py`) rather than inventing 20 MB.
Our over-cap rejection is reported distinctly from Backstop's own `413`.

**Discriminated unions for variants.** `LogActivityInput` is a union on `kind`. Each
variant's required fields (`time_zone` / `start` / `stop` on a meeting, `due_date` on a
task) live on that variant so pydantic rejects the call instead of Backstop. Shared
fields that several variants need (`activity_tag_ids`, party targeting) live once on a
base class; tasks still omit tags because they do not accept them. There is no `email`
kind on `log_activity`: `POST /emails` needs the message blob
(`400 "Field data is required"`), so email creates live only on `attach_file`.

**Facade command, child commands, public door.** `LogActivityCommand` switches on `kind`
and calls `LogNoteCommand` / `LogMeetingOrCallCommand` / `LogTaskCommand`. Each child
does one POST. Meeting and call share one command — they are the same Backstop
collection. The outside interface does not look inside. `__all__` exports the four public
commands (`LogActivityCommand`, `AttachFileCommand`, `UpdateActivityCommand`,
`DeleteActivityCommand`) and the published inputs/responses — child commands and union
members stay inside the feature. Factories stay on the door for teardown. FastMCP's
Depends system needs a factory per injectable command; do not collapse fourteen commands
into one "write service" to shorten `dependencies.py`.

**Author is derived, never a parameter.** `get_current_caller_system_user` resolves the
login-cached `external_user_id` (`filter[userName][eq]` is rejected). The tool passes
`AuthorDto.from_system_user(caller)` into create `run`. `AuthorDto` is the three fields
the write needs, not a pass-through of `SystemUserDto`. Tasks have no author — do not
walk `/system-users` for a field the payload will not send. `assigned_user` is a
caller-supplied login and still goes through `SystemUsersService`.

**Share the thing that would drift; leave the rest at the call site.**
`activity_base_attributes` / `activity_tag_relationship` are shared because create and
PATCH map `title` → `name` (tasks) the same way. Party links stay at the caller — they
need the resolved `party_id`, which is not on the activity. A util that takes five
arguments to hide those links obfuscates more than it saves. `json_api_update` is
`json_api_create` plus `id`. `relationship_data` is one function: `None` omits the key,
`()` is an empty replace. Creates pass `omit_empty=True` on tags so `()` is not sent;
updates leave `()` as a clear.

**Reuse, do not redeclare.** Parent links are `ResourceRef` from `json_api.py`.
`NonEmptyStr` lives in `models.py`. `blank_to_none` / `require_exactly_one_party_selector`
live on the party-resolver door. `parse_activity_handle` is one parser; writes pass
`kind` into `extract_collection` so a bare create-echo id still lands on the right
collection. `api_responses` model the real attribute subset the API returns — do not
invent an empty model "just to take `.id`", and do not put `author` / `attendees` /
`createdBy` on `*Attributes` (those are relationships; `extra="ignore"` still accepts
them if they ever show up).

**DELETE has no body.** `client.delete(path)` — no dummy `*Attributes`, no `schema=` on a
204. Pass `schema=` only when Backstop returns a body.

**A bulk POST is read through `features/bulk_writes`.** Every `POST /bulk-*` answers `201`
whether or not anything landed, so `BulkLoadSummaryAttributes`, `RecordOutcomeResponse` and
the `bulk_record_outcomes` fold (error index → row, `successCount: 0` → whole batch failed,
landed key → `applied`, leftover message → warning) live there once. A new bulk writer
supplies the two things that are actually its own: the `match_key` its rows are identified by
in Backstop's echo (a definition id; an `(opportunity_id, stage_id)` pair) and the document
shape wrapping `attributes.records`. Do not copy the fold into the feature.

**Never let `omit_none_values` eat a value the caller meant to clear.** It is for keys that
are absent, not for keys that are null. Custom-field writes send `"value": null` explicitly —
dropping the key posts a record with nothing to write, and Backstop still echoes the
definition id back, so the fold above would have reported `applied` for a no-op.

**Elicitation is a capability, then a fetch.** `elicit_entity_deletion` takes a callback
and runs it only after the client is known to support elicitation. Do not GET a preview
for a prompt that will never be shown. Id spaces differ (`/entity-activity-details` is
not `/emails` or `/tasks`) — use one parser that knows `kind`, and do not treat a 200
from the wrong collection as the target record.

**Do not premature-optimize a small catalog.** A linear scan of ~200 time zones is fine.
Cache TTL stays off until a metric says otherwise. Index a roster by casefolded login
when every write would otherwise walk it; drop users without a login, keep the first
duplicate, warn.

---

## Write payloads

Four rules, each learned from a 400 on the live instance. Local copies of those probes
live only under `agent-explore/.probe-cache` (developer utility, not shipped). The swagger
is wrong or silent about all four, so a create designed from it does not work.

**1. A parent link's `resourceType` is the plural resource name.** `attachedTo`,
`regarding`, `resources`, `linkedResources` and `secondaryRegarding` carry
`{resourceId, resourceType, resourceLink}` where `resourceType` is `organizations` /
`people` / `contacts` / `employees`. Bean casing is rejected —
`400 "Can not find OrganizationBean with id ..."`, and `linkedResources` is blunter:
`400 "Invalid LinkResourceType EmployeeBean"`. A `SearchType` is already the right string.
`map_search_type_to_resource_type_bean` is for `filter[entityType][eq]` on the **read**
side only; it has no business in a write payload.

**2. Identity pointers are relationships, never attributes.** `author`, `createdBy` and
`assignedUser` go in `relationships` as `{"data": {"type": "system-users", "id": ...}}`.
In `attributes` Backstop answers
`400 "author should not be in the 'attributes' but 'relationship."`. `attendees` and
`activityTags` are relationships too, and both persist on the `POST` — no follow-up PATCH.

**3. Required fields are not the swagger's required list.** Notes need `effectiveDate`;
`meeting-or-calls` need `title`, `type`, `timeZone`, `startTimestamp`, `stopTimestamp`,
`regarding` and `author`; tasks need `name`, `dueDate` and `attachedTo`; `emails` need
`data` **and** `emailFormat`. Put each one on the pydantic input (or default it in the
command) so the model rejects the call instead of the agent reading a 400.

**4. Silent defaults bite.** `sendNotification` defaults to **true** when omitted, which
mails the assignee — always write the flag explicitly. `isDraft` defaults to false. A
`linkedResources` entry that repeats the parent is silently dropped, so filter it out
rather than reporting a link that is not there.

Also worth knowing before you route a write: nested collection routes are not uniformly
writable (`POST /contacts/{id}/notes` is `403 "contacts/notes is read only."` while
top-level `POST /notes` accepts every party type), nested `POST /{segment}/{id}/meeting-or-calls`
returns `201` but silently orphans the record from the parent's activity feed (route
meetings and calls through top-level `POST /meeting-or-calls` with an explicit `regarding`),
and `Accept: application/json` gets an HTML 404 page instead of a JSON error, which is why
`backstop_client/factory.py` pins `application/vnd.api+json`.

A metadata-only email cannot be created. `POST /emails` answers
`400 "Field data is required in POST request."` — the blob goes on `attach_file(kind="email")`.
The UI can log an email without a file; the REST API cannot.

---

## Overlapping other GETs (custom-field catalog)

`CustomFieldsService` is a process-wide TTL cache with single-flight. `join_values` loads
the catalog (or reuses it) and returns `[]` on a miss. An empty `custom_field_values` list
is therefore ambiguous unless the caller also reports the miss.

Each opportunity query `asyncio.gather`s `custom_fields_service.load_catalog()` with
the Backstop walk (or the per-id GETs), then sets `custom_fields_unavailable=catalog is None`
on the response. Do that in the query, not behind a mapper wrapper:

- overlapping the walk means `join_values` hits a warm cache (or a known miss) instead of
  waiting for a cold fetch after the last page
- the flag is a fact about the catalog, not something inferred from empty values

Document *why* the gather is there on `run`, in one short paragraph — not that `gather`
runs two coroutines.

Inject the same `CustomFieldsService` instance into the query and the mapper (production:
the cached `get_custom_fields_service`; tests: one `custom_fields_service()` shared by both).
Two instances means two catalogs and the parallel load does not warm the join.

---

## Documentation

Write the comment that stops the next person guessing wrong. Do not write the comment that
restates the next line.

Worth a docstring or an inline note:

- a Backstop quirk (`filter[isOpen]` is 400; `previous_stage` is the stage LEFT)
- why a walk is unbounded, or why it has a ceiling
- why two requests run in parallel
- why a page is dropped vs a single record
- Field descriptions on every published response field (they *are* the MCP output schema;
  `tests/server/tools/test_output_descriptions.py` reads those strings)

Not worth a comment: "paginate the collection", "return the response", "map the row".

Tool docstrings are for the model that will call them. Say what to echo, what not to invent,
and what an empty list means when a flag is set. When published argument names differ from
Backstop camelCase or a sibling tool, include a `Call like:` JSON sample of the published
arguments — teach the correct call rather than accepting aliases.

---

## Tracing, logs, and metrics

Features own their observability. The ASGI middleware already spans the HTTP request;
that is not enough to see *which query ran* or *why a walk was empty*. Put spans and
structured logs on the feature path so a trace reads tool → resolve → query/command →
Backstop.

**Spans.** Open a span around each tool entry and each query/command `run` (and around a
util only when it is a real unit of work, not a one-line map). Name them after the
operation (`opportunities.get`, `opportunities.query.get`, `opportunities.command.close`),
and set attributes the reader will filter on (`segment`, `entity_id`, `status`, counts).
Use `opentelemetry.trace`. Do not invent a wrapper.

**Logs.** Dotted event names, structured `extra`, no interpolated messages:

```python
logger.info(
    "opportunities.fetched",
    extra={"segment": segment, "entity_id": entity_id, "total": result.total},
)
logger.warning(
    "opportunities.record.unreadable",
    extra={"opportunity_id": opportunity.id},
    exc_info=exc,
)
```

Log at the start of a tool call and when a query finishes (what was asked, what came
back). Warn when a record is dropped, a catalog miss is flagged, or a per-id GET fails.
Do not log every mapped row. Do not put secrets, tokens, or raw Backstop bodies in
`extra`. A username or login is `IdentifiableValue(login)` from `utils/` — it prints
`sha256:<hex>` unless `LOGS_DIAGNOSTICS_DATA_POLICY=disclose`. Never interpolate the raw
login into the line.

**Metrics.** Add an instrument in `metrics.py` only when a number will change a decision
you can name: catalog TTL vs walk cost (`CUSTOM_FIELD_SCHEMA_LOADS`, the catalog
duration pair), rate-limit retries, concurrency wait. A counter that increments on every
tool call "for completeness" is noise. If you cannot say what you would do differently
when the series moves, do not add it.

---

## Dependencies and teardown

```python
@lru_cache(maxsize=1)
def get_opportunities_query_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    map_opportunity_to_response_util: MapOpportunityToResponseUtil = Depends(
        get_map_opportunity_to_response_util_factory
    ),
    custom_fields_service: CustomFieldsService = Depends(get_custom_fields_service),
) -> GetOpportunitiesQuery: ...
```

Export cached factories from the feature `__init__`. `teardown.py` imports them from the
feature package (`from backstop_mcp.features.opportunities import …`), never from
`dependencies.py` — that file already imports `backstop_mcp.dependencies`, and the reverse
is a cycle.

Cached factories must only `Depends` on other cached factories (or
`get_backstop_client_for_current_caller`, which returns the process-wide client). Read
`BackstopConfig` inside the body. An uncached or unhashable Depends — a fresh mapper, a
settings object — is either `TypeError: unhashable type` or a new object every request,
and FastMCP surfaces `Failed to resolve dependency '…'` on every tool in that chain.

---

## Tests

We test the **public interface** only. The public surface is what `__all__` and the tool
function expose: `GetOpportunitiesQuery.run`, `get_opportunities`, the published response.
Private helpers (`_matches_status`, `_fetch_one_opportunity`, `_bucket`) are exercised
through that surface. Do not make a method public so a test can call it. If it is private,
it stays private; the test still goes through `run` or the tool.

The usual shape is: mock the **external boundary** (the Backstop HTTP API, via respx),
construct the query/command/tool the same way production does, call it, assert on the
**output**. That is what the opportunities tests do — a page of JSON in, a response model
out. They do not assert on which private method ran, which local was assigned, or the
exact helper call graph. Those assertions lock an implementation in place and break on
the next rename.

Write tests pin the **wire** to recorded live shapes, not to what the first draft sent.
The originals in `activity_writes` asserted `PersonBean` and an attribute `author` — they
passed against a mock of a contract Backstop rejects, which is how the wrong payload
survived a green suite. Assert `resourceType: "organizations"` and
`relationships.author`, and keep a fixture that replays the live `400` when those are
wrong. `recorded_json_bodies` is the helper.

Assert on internals only when there is no other way to know the feature worked (for
example `definitions.call_count == 1` when the *contract* is "one catalog load covers the
batch"). Prefer an output flag (`custom_fields_unavailable`) or a missing field over
opening the object and checking a private cache.

```
tests/features/<name>/
  conftest.py                         helpers construct queries/commands the same way production does
  test_<name>_query.py                enter the feature through __init__
  test_<name>_command.py
  tools/
    test_get_<name>.py                may import features.<name>.tools.get_<name>
```

- Mock Backstop routes. Do not mock `MapOpportunityToResponseUtil` or a query's private
  methods unless the tool under test cannot be reached any other way (it almost always can).
- Construct the query or command with the same collaborators the factory would inject. Share one
  `CustomFieldsService` between query and mapper.
- Pass tools their collaborators as kwargs; do not stand up Postgres for a feature test.
- Present tense, no "should": `test_catalog_failure_keeps_the_deals_and_flags_unavailable`.
- Assert the flag and the empty list on a catalog miss, and that a successful path still
  returns `custom_fields_unavailable is False`.

---

## New feature / tool checklist

1. Read the `backstop-api` skill. Confirm the endpoint, includes, and filters with a live
   `GET` (write the probe to `agent-explore/.probe-cache/`). Never write to the CRM unless
   the user says so for that task; when they do, delete every record you created and
   verify the follow-up `GET` 404s. Pin write tests to those recorded `400`/`201` bodies.
2. Look at `features/opportunities/` for reads, `features/activity_writes/` for writes —
   not `org_people`, not `accounts`.
3. Add model layers, query and/or command, utils, tool, `__all__` exports. A write tool
   that cannot share one honest `ToolAnnotations` set is more than one tool.
4. Register the tool on `TOOLS`.
5. Add cached providers to `teardown.PROVIDERS` if and only if they are `@lru_cache`.
6. `uv run pytest tests/features/<name> tests/test_layering.py tests/test_teardown.py tests/server/tools/test_output_descriptions.py`
7. `uv run ruff format … && uv run ruff check … && uv run basedpyright …` on what you touched.

---

## Still enforced (do not "improve" away)

These are tests, not taste:

1. `features/` does not import `server/`.
2. `backstop_client/` does not import `features/` or `config`.
3. Public packages are entered through `__init__` (rule 4).
4. Model layers flow `responses` → `internal_dto` → `api_responses` (rule 5).
5. A logic file is named after its symbol (rule 6).
6. Every tool module is on `TOOLS` (rule 7).
7. Every `@lru_cache` provider is in `teardown.PROVIDERS`.
8. `src/backstop_mcp/` and `tests/` do not import or mention `agent-explore/`
   (developer utility only).
9. The service does not name a client tenant host or the client's firm.
   Measurements say "a client-obtained tenant".

Never mutate a function argument. Use `assert` for internal invariants; `raise` at the
system boundary (user input, Backstop errors).
