# Design: contact details and opportunities for backstop-mcp

**Ticket:** UN-23680

## Problem

UN-23680 ("Read/Lookup A1") asks three read questions. Activity history already shipped (PR #794).
The two remaining are:

- *"Who do we contact at X?"* — emails and locations for a person or organisation.
- *"What is the pipeline status for X?"* — opportunities with their stage and stage timing.

Neither is answerable today. `get_person` / `get_organization` return only the record's own
`attributes`, so locations, the address book and the primary contact are invisible. There is no
opportunities tool at all.

A third problem surfaced during exploration and is in scope because it blocks the first two from
being *usable*: nothing this server returns is described to the model. `tool_result` serialises a
payload to a bare JSON text block, so pydantic docstrings and `Field(description=...)` never reach
the caller, and no tool publishes an `outputSchema`. A model receiving `retired: true` on an email
has no way to know what it means.

### What the live API actually does

Every number and behaviour below was measured against the live instance
(`fb-rm-lg-26.backstopsolutions.com`), not read from the swagger. These are the facts the design
turns on; several contradict the obvious reading of the API.

**`include=` is an allowlist problem, not a passthrough.**

- Every relationship accepts `include=` — all 22 organisation and 21 person relationship names
  returned 200. The API imposes no discipline whatsoever.
- Unknown include names *do* 400 (`The system does not support includes for zzzNope`), so a typo
  is loud rather than silent.
- On a **by-id resource** GET, `page[limit]` does **not** bound `included`:
  `GET /organizations/{id}?include=activities&page[limit]=5` side-loads **355** activity resources.
- On a **collection** GET the side-load does follow the page: a page of 10 opportunities carried
  34 stage-history entries versus 95 for all 33.
- Nested includes work: `include=opportunities.stage,contactLocations` returns opportunities,
  their stages and the locations in one response.

Measured cardinality (Koch org `341764767` / Kent Voss person `341665739`):

| relationship | org | person | disposition |
| --- | --- | --- | --- |
| `activities` | 355 | 358 | excluded — owned by `get_activity_history` |
| `emails` (messages, *not* addresses) | 488 | 483 | excluded — owned by `get_activity_history` |
| `meetingOrCalls` | 188 | 189 | excluded — owned by `get_activity_history` |
| `notes` | 148 | 150 | excluded — owned by `get_activity_history` |
| `documents` | 19 | 19 | excluded — owned by `get_activity_history` |
| `timeSeriesCustomFieldValues` | 0 | 111 | excluded — owned by the custom-fields feature |
| `entityRelationships` | 74 | 9 | excluded — already side-loaded unconditionally by `get_person` |
| `employees` | 33 | — | excluded — a different question from contact details |
| `opportunities` | 17 | 7 | excluded from `include` — owned by `get_opportunities` |
| `contactLocations` | 2 | 1 | **included** as `locations` |
| `contactEmails` | 0 | 3 | **included** as `email_addresses` |
| `primaryContact` | 1 | — | **included** as `primary_contact` |
| `company` | — | 1 | **included** as `company` |
| `representative` | 1 | 1 | **included** as `representative` |
| `categories` | 5 | 12 | excluded — classification, not contact detail |
| `contactSource`, `clientDefinedEntityType` | 1 | 1 | excluded — niche |
| `aums` | 0 | — | excluded — money time-series, UN-23681 |
| `tasks` | 3 | 0 | excluded — activity-shaped; note no task stream exists yet |
| `createdBy`, `modifiedBy`, `referralSource`, `permissionBucket`, `systemUser` | 0–1 | 0–1 | excluded — noise, or already in `as_of` |

**`emails` is a name collision.** Backstop's `emails` relationship is email *messages*
(subject / fromEmail / toEmails / sentTimestamp — 488 on Koch). The address book is
`contactEmails`. Exposing an include literally named `emails` would invite a model to fetch 488
messages while looking for an address, so the include names are ours, not Backstop's.

**Retired email addresses are a correctness hazard.** `contactEmails` carries
`retired: true | false`. Kent Voss has three: `vossk@kochinvests.com` (live) plus two retired, one
of which is `bbetten@macfound.org` — a different person's address at a different firm, sitting on
his record. Dropping retired entries loses "we used to reach them at X"; including them unlabelled
hands over a wrong address. Both must be returned and labelled.

**Organisation email is effectively absent.** Across 25 organisations: 31 `contactLocations` but
only **2** `contactEmails` in total, and only 2 of 25 had `attributes.email` set. For an
organisation, "contact details" is in practice locations plus the primary contact person. People
also carry `email` / `email2` / `email3` flat in `attributes`, which are already returned.

**`previousStage` is the stage a deal just *left*, and the current stage is only in a
relationship.** Verified by observing a live stage change on opportunity `5755031`:

- Before the move: `stage` → `opportunity-stages/85446` ("Client Approval"), and the
  `previousStage` attribute was **absent**.
- After the move: `stage` → `opportunity-stages/42482` ("IDD") matching the UI's Stage field, and
  `previousStage` → `"Client Approval"`, matching the earlier chevron in the UI's Stage History.

So `previousStage` only appears once a deal has moved, and it always names the vacated stage. Any
opportunity payload without `include=stage` cannot name the current stage, and the only
stage-looking attribute present would actively mislead.

**`isOpen` is not filterable and party sub-collections do not sort.**

- `filter[isOpen][eq]=true` → **400** `{"code":"InvalidParameterException","title":"Invalid filter
  field isOpen"}`, on both `/opportunities` and `/{party}/{id}/opportunities`. Unknown filter
  fields error here rather than being silently dropped. Only the five documented fields filter.
- `sort=` works on top-level `/opportunities` (ascending and descending return genuinely different
  records) but is **accepted and silently ignored** on `/{party}/{id}/opportunities` — byte-identical
  ordering for `sort=modifiedTimestamp` and `sort=-modifiedTimestamp`. A `sort` on an unknown field
  400s there, so the field name is validated but the ordering is not applied.

Therefore open/closed filtering and ordering are both ours, in memory.

**Stage history is affordable but not self-contained.**

- `include=stage,stageHistory` on the sub-collection returns everything in **one** request: Koch →
  17 opportunities + 45 history entries + 3 stage resources; the largest party → 33 + 95 + 3.
- History entries are thin: `effectiveDate` plus a stage pointer.
- The pointer is **not** a JSON:API relationship. `relationships` is `{}` and the pointer sits in
  `attributes.stage` as `{resourceType, resourceId, resourceLink}` — Backstop's second, inline
  reference format, also used by `regularCustomFieldValues` values ("Attendee 1" →
  `people/341672203`). `follow_included` does not understand this format.
- 45 history entries referenced **6** distinct stage ids while only **3** arrived in `included`.
  The missing ones resolve against `GET /opportunity-stages`, which is 7 rows total:
  Prospect(1) → Project(2) → IDD(3) → Client Approval(4) → Execution(5) → Invested(6, closed) →
  Closed(7, closed).

**Opportunity volume is small and bounded.** Across the whole instance: 1206 opportunities over 513
investors. p50 = **1**, p90 = **4**, p99 ≈ **20**, max = **33**. Twelve investors exceed 10, four
exceed 20, **none** exceed 50. `isOpen`, `dateEnteredCurrentStage`, `daysInCurrentStage` and
`modifiedTimestamp` are never null across all 1206 records; `expectedInvestmentDate` is null in 27.

**Envelope dominates payload.** The largest party's 33 opportunities with `include=stage,stageHistory`
is **298 KB** raw (~75k tokens), of which only 38 KB is custom field values — the rest is the
JSON:API envelope, 21 relationship link-blocks per opportunity. Projected to the fields that answer
the question, the same worst case is roughly 50 KB and the p50 party about 1.5 KB.

## Solution

### Overview

Three parts, plus one cross-cutting change.

**An include registry.** A per-segment table maps a semantic include name to a Backstop
relationship, the JSON:API `type` its resources arrive under, and a trimmed projection model. The
table *is* the allowlist, so `activities` is unreachable by construction rather than by a runtime
check. `get_person` and `get_organization` each gain one `include` parameter typed as a `Literal`
of their table's keys, so an invalid name is rejected at the MCP boundary and the input schema
self-documents the options.

The registry is deliberately **not** a generic recursive hydrator over `included`. A hydrator that
walks `relationships` would inline an opportunity's `stage` correctly and leave 45 stage-history
entries holding unresolved inline pointers — and 3 of the 6 stages they point at are not in
`included` at all. It would also faithfully reproduce fields the model then has to reconcile:
`contact-locations` ships four literal duplicate pairs (`country`/`countryResolvedName`,
`city`/`cityResolvedName`, `state`/`stateResolvedName`, `isPrimaryLocation`/`primaryLocation`) out of
17 fields. The projection layer is where the value is; the existing `follow_included` already
handles every depth the agreed scope needs, including collection documents.

**A `get_opportunities` tool.** Same party-resolution shape as `get_activity_history`
(`party_type` plus a trusted `party_id` or a `search`, with an optional `search_type` echo). One
paginated call to `/{segment}/{id}/opportunities?include=stage,stageHistory`, plus a TTL-cached
`GET /opportunity-stages`, then filtering and ordering in memory.

**Documentation as an output, not prose.** Projection models carry docstrings and per-field
descriptions; all seven tools return typed models so FastMCP publishes an `outputSchema` carrying
those descriptions; a `describe_data_model` tool renders the registry plus a tool-ownership map and
the stage vocabulary; and `FastMCP(instructions=…)` carries a short orientation. The generated
paths cannot drift from the payload because they *are* the payload's schema.

### Architecture

**`features/includes/`**

- `types.py` — `IncludeSpec(relationship, resource_type, model, to_one)`, and `ResourceRef` for the
  inline `{resourceType, resourceId, resourceLink}` format so that second format is handled
  explicitly wherever it appears rather than silently mishandled.
- `projections.py` — `ContactLocation`, `ContactEmail{email, retired}`, `ContactCard`, `CompanyRef`,
  `InternalOwner`. Each has a model docstring and `Field(description=...)` on every field; this is
  the single source for the entity documentation. `extra="ignore"` does the trimming: 8 fields kept
  of a location's 17; 5 of a person's 25 for a contact card.
- `registry.py` — `ORGANIZATION_INCLUDES` (`locations`, `email_addresses`, `primary_contact`,
  `representative`) and `PERSON_INCLUDES` (`locations`, `email_addresses`, `company`,
  `representative`).
- `resolve.py` — `include_param(specs, requested)` building the query string, and
  `project(document, resource, specs, requested)` returning `{name: model | [model]}` on top of
  `follow_included`.

`InternalOwner` is documented as *our* account owner (a `system-users` resource, e.g. "Margaret
Lucas" with an internal `userName` and office phone), explicitly not a way to contact the investor.

**`get_person` / `get_organization`** gain the `include` parameter, pass `include_param(...)` into
their existing single GET, and add `included` to their response models. `get_person` keeps its
unconditional `entityRelationships` side-load for `employments`; the registry composes with it.

Record `attributes` keep their current `extra="allow"` passthrough, **including
`regularCustomFieldValues`**. This is a deliberate deviation from UN-23680's "no read tool returns
all 51 organization fields" criterion: write-back (UN-23685) needs `definitionId` to round-trip, so
stripping the values now would only have to be undone. The deviation is recorded rather than
presented as met.

**`features/opportunities/`**

- `stages.py` — TTL-cached `GET /opportunity-stages` (7 rows), following the `custom_fields_service`
  pattern.
- `projections.py` — `OpportunityRecord` (name, `stage`, `previous_stage`, `is_open`, `probability`,
  `requested_amount`, `allocated_amount`, `currency`, `expected_investment_date`, `closed_date`,
  `days_open`, `days_in_current_stage`, `date_entered_current_stage`, `custom_field_values`) and
  `StageChange(stage, effective_date)`.
- `fetch.py` — walks the sub-collection with `client.paginate()` at `page[limit]=100`, resolves each
  opportunity's current stage from `included` via `follow_included`, resolves each history entry's
  inline `ResourceRef` against `included` then the cached vocabulary, then filters by `status`
  (`open` / `closed` / `all`) and orders by `dateEnteredCurrentStage` descending.

**`get_opportunities`** exposes **no cursor**. Filtering and ordering require the whole set: paging
outward would let a party whose open deals sit on page 3 receive an authoritative-looking empty
answer for `status="open"`, and would order each page correctly but the list wrongly. Since no party
in the instance exceeds 50 opportunities, one request at `page[limit]=100` covers every party today.
A configured `max_opportunities` (default ~200) bounds growth: exceeding it returns what was
fetched plus `total` and `truncated: true`, so a partial answer can never read as complete. This
differs from `get_activity_history`, which *does* expose cursors — because activity streams are
genuinely unbounded (355+ per party) while opportunities are bounded and need whole-set operations.

`status` defaults to `all`, with `open_count` and `closed_count` on the response so the split is
visible without a second call.

**Cross-cutting**

- `OmitNoneModel` — a base carrying `@model_serializer(mode="wrap")` that drops `None`-valued keys,
  preserving the absent-vs-null semantics `get_activity_history` currently gets from
  `exclude_none=True`. Because a wrap serializer returning a bare dict erases the serialization
  schema, tools using it pass an explicit
  `@tool(..., output_schema=Response.model_json_schema(mode="validation"))`. Both properties verified
  together: `structuredContent` omits the key, and the schema still documents the field.
- All seven tools return typed models instead of `CallToolResult`. `results.py` is deleted —
  `tool_error` has zero call sites, and `tool_result`'s nine call sites become plain returns. Test
  helpers `tool_model` / `tool_model_union` collapse to the returned value, and `test_results.py`
  goes away.
- `describe_data_model` — a read-only tool rendering, from the registry: each entity's purpose, its
  fields with descriptions, which tool and which `include` produces it, the 7-stage vocabulary, and
  an ownership map (contact details → `get_person`/`get_organization`; meetings, calls, notes,
  emails, documents → `get_activity_history`; pipeline → `get_opportunities`; custom field names →
  `list_custom_fields`). The ownership map is the part that stops a model reaching for
  `get_organization` to get meeting history.
- `FastMCP(instructions=…)` — currently unused. Gains a short orientation: the entity vocabulary,
  the ownership map, and a pointer to `describe_data_model`. Kept brief because it is in context
  every conversation.

### Error Handling

- **Invalid include names never reach runtime.** The `Literal` parameter type means FastMCP rejects
  them at the boundary; `include_param` treats an unrecognised name as an internal invariant.
- **Party resolution is unchanged** — the existing `ambiguous` / `not_found` union responses and
  elicitation.
- **Upstream failures propagate.** `BackstopClient` already raises `BackstopAuthError` /
  `BackstopRateLimitError` / `BackstopApiError`; tools do not catch. `get_opportunities` issues its
  opportunities and vocabulary fetches together and lets either failure fail the call — the same
  rationale `get_activity_history` documents for its `gather`: a partial result that silently omits
  data is worse than an error.
- **A malformed side-loaded resource is dropped, not fatal.** `project()` validates each `included`
  entry independently and warns-and-drops on `ValidationError`, matching
  `data_hygiene._parse_resources`. One unreadable location must not lose the other.
- **An unresolvable stage is labelled, not guessed.** If a history entry's stage id is in neither
  `included` nor the vocabulary, the entry is returned with its id and a null name.
- **Absent versus empty is meaningful.** A requested to-many include with no data returns `[]`
  ("we looked, there are none"); an include that was not requested is absent from the payload
  entirely via `OmitNoneModel`.
- **Truncation is loud.** Exceeding `max_opportunities` sets `truncated: true` alongside `total`.

### Testing Strategy

The existing harness fits: `respx`-mocked upstream, real `Services` installed through
`runtime.get_services()`, direct tool invocation. Behavioural cases:

- Locations returned with `is_primary` and both `locationTitle`s; the duplicate source fields
  collapse to one projected field each.
- A retired email is present **and** flagged; the live one is distinguishable.
- Organisation `contactEmails` empty → `[]`, distinct from the include not being requested.
- `primary_contact` projected to 5 fields from a 25-attribute person resource.
- `representative` labelled as internal.
- Opportunities filtered `open` / `closed` / `all`, with `open_count` / `closed_count` correct.
- Current stage named from `included`; `previous_stage` carried from the attribute and absent when
  the deal has never moved.
- A history stage named from the cached vocabulary when absent from `included`.
- An unnameable stage id surfaced with a null name rather than dropped.
- Ordering by `dateEnteredCurrentStage` descending across a multi-page fetch.
- `truncated` / `total` set when the cap is exceeded.
- `include` omitted → no `included` key at all.
- Output schema published and documenting a nullable field on a tool using `OmitNoneModel`.

`include_param`, the status filter, the ordering key and stage resolution are pure functions and get
direct unit tests.

## Out of Scope

- Topic/content search across activity content (`POST /activity-search`) — the other half of
  UN-23680's activity scope, already partly served by `get_activity_history`.
- Balances, invested amounts, account status — UN-23681.
- Any write operation — UN-23684 / UN-23685.
- Report generation / summarisation — UN-23682.
- A generic recursive `included` hydrator. Reconsider only if a real depth-2+ JSON:API include
  enters scope; the agreed includes are all depth-1 and `follow_included` already covers the
  collection-document case.
- `employees`, `categories`, `aums`, `tasks`, `contactSource` includes — measured and deliberately
  excluded above.
- Trimming record `attributes` or moving `regularCustomFieldValues` behind a flag — deliberately
  deferred until write-back defines what it needs.
- A task activity stream (`tasks` has 3 records on Koch and no stream exists today).

## Tasks

1. **Include registry and projection models** — Add `features/includes/` with `IncludeSpec`,
   `ResourceRef`, the five projection models (docstrings plus per-field descriptions), and the
   `ORGANIZATION_INCLUDES` / `PERSON_INCLUDES` tables. Add `include_param()` and `project()` on top
   of the existing `follow_included`.

2. **Wire `include` into `get_person` and `get_organization`** — Add the `Literal`-typed `include`
   parameter, pass the built `include=` param into the existing single GET, and add `included` to
   both response models. Keep `get_person`'s unconditional `entityRelationships` side-load.

3. **Stage vocabulary cache** — Add a TTL-cached `GET /opportunity-stages` service following the
   `custom_fields_service` pattern, exposing id → (name, closed, sort order).

4. **Opportunities fetch, projection, filter and sort** — Add `features/opportunities/` with
   `OpportunityRecord` and `StageChange`, a paginated sub-collection fetch using
   `include=stage,stageHistory`, current-stage resolution from `included`, history resolution via
   the inline `ResourceRef` then the vocabulary, `status` filtering, `dateEnteredCurrentStage`
   ordering, and the `max_opportunities` truncation guard.

5. **`get_opportunities` tool** — Wire party resolution to the fetch, return `open_count` /
   `closed_count` / `total` / `truncated` alongside the records, and register the tool. Document in
   the docstring that `previous_stage` names the vacated stage and that there is no cursor.

6. **Typed returns and output schemas** — Add `OmitNoneModel`, convert all seven tools to typed
   returns with `output_schema=` where the serializer is used, delete `results.py`, simplify
   `tests/server/tools/helpers.py`, and remove `test_results.py`.

7. **`describe_data_model` tool** — Render the registry into entities, fields, include names, the
   stage vocabulary and the tool-ownership map. Register it.

8. **Server instructions** — Populate `FastMCP(instructions=…)` with the short orientation and a
   pointer to `describe_data_model`.

9. **Tests** — Cover the behavioural cases and pure-function unit tests listed in the testing
   strategy.
