# Design: Backstop MCP — answering the IR team's question list

## Problem

Margaret Lucas surveyed the Capstone IR team for the questions they would put to the Backstop MCP —
roughly 90 questions across 10 categories, from "how much money does X investor have in CGM" to
"which prospects are stuck in diligence".

The connector today has nine tools — seven party-scoped, `get_product_positions` product-scoped,
`list_custom_fields` a catalog read — and answers about 15% of that list. The gaps, ordered by how
many questions each one blocks:

1. **No activity-tag support at all.** Zero references in the service. Capstone's 301 activity tags
   *are* their vocabulary for topic, product, activity type and content: `AT: Meeting`, `AT: Call`,
   `AT: Paul Email`, `AT: Cap Intro Notes`, `AT: Dispersion`, `AT: Convert Arb`,
   `Dispersion Presentation`, `CVM DDQ`, `Follow up`, `Operational Feedback`, `Reverse Inquiry`.
   Without tags, every "about product Y" / "on topic X" / "what content did they get" question is
   unanswerable.
2. **Custom-field values are an unsliceable dump.** `get_organization` returns
   `regularCustomFieldValues` as a flat list — on a live org ~86-134 entries where `Status` appears
   8 times with 8 different `definitionId`s. The tenant's entire semantic model (Grade, Status,
   Investor Status, the product-interest matrix, the `Readers` newsletter lists, the `Events`
   attendance fields, `New Product Targeting` campaigns) lives there and cannot be addressed.
3. **No firm-wide queries.** Every tool resolves one party (or one product) and fetches its
   children. Nothing can ask "which meetings happened last quarter" or "what does the whole
   pipeline look like".
4. **Account performance series unused.** `irrs`, `returns` and `percentageOfFundHistory` are all
   available and none are surfaced, so ITD performance and share of fund — two of the things
   Margaret called out as her most-used meeting-prep facts — are missing. Tenure is the exception:
   `accountStartDate` already ships on every account row.
5. **No product-side view.** "Provide a list of organizations invested in Dispersion" — Margaret's
   demonstrated fund view — has no tool, despite being one call.

## Solution

### Overview

Two kinds of change and no new architecture. The existing nine tools gain **data and filters**; new
tools are added only for axes no current tool has — topic (activity tags), the product side, and
bounded firm-wide collections.

Every API claim below was re-confirmed against the live instance (`fb-rm-lg-26`) on 2026-08-20,
after the DI refactor. Where the re-check contradicted the first pass, the measurement wins and the
task changed — see **Cost and latency** below and the Error Handling notes.

Three API facts found during exploration make this far cheaper than the existing backlog assumed
(see `docs/backstop-mcp-cohort-questions.md` §1 for the measurements):

- **`regarding` attributes every firm-wide activity row to a party.** This settles ticket B1's open
  question — firm-wide activity does *not* require walking parties.
- **`filter[activityTagIds]` composes with date filters and genuinely filters.** `AT: Dispersion`
  since 2024 → 418 rows out of 4,578. So *topic + period + which investor* is one call.
- **Sparse fieldsets (`fields[<type>]=…`) are honoured**, worth 27× on opportunities. Already used
  in this codebase (`fields[employees]` in
  `features/org_people/fetch_people_for_organization.py`, and `fields=` plus parallel paging on
  both `/accounts` walks), so no client work.

Deliberately excluded: anything needing predicates over all organizations or all people. That is 14
questions, parked with full reasoning in `docs/backstop-mcp-cohort-questions.md` for its own design
session.

### Cost and latency

**A tool call is one request per collection it reads, plus its cached reference walks. Nothing here
may fetch per returned row.** Three confirmed API properties are what make that achievable, and one
confirmed absence is what constrains it.

- **Party attribution is on the row.** `/meeting-or-calls` and `/notes` carry `regarding`;
  `/documents` and `/tasks` carry `attachedTo` (documents have **no** `regarding` — checked). So
  "which investor was this about" never costs a second request.
- **Nested includes work**: `include=fundAccount.owner` on subscriptions returns the account *and*
  the owning party; `include=originalSubscription.fundAccount` on redemptions returns the account a
  redemption belongs to. That is the difference between one call and one call per row, and it is
  what makes `get_capital_flows` viable at all.
- **Sparse fieldsets are the cost lever.** A `/meeting-or-calls` row is 11.5 KB full and 543 B with
  `fields[meeting-or-calls]=title,startTimestamp,regarding,type` — 21×. Adding
  `include=activityTags&fields[activity-tags]=name` costs ~700 B/row. So 418 tagged meetings is
  ~230 KB, a few parallel pages.
- **There is no bulk time-series path.** `GET /time-series` is `400 Find all time-series is not
  allowed.` `include=values` on the accounts walk *does* work but returns the **entire** series —
  164 points, 56 KB, for one account; three series for two accounts is 330 KB. `fields[time-series]`
  trims only ~29%, and `filter[values.date]` on the parent walk is `400`. Account figures are
  therefore an irreducible fan-out of one request per account per series.

That last point inverts what this design originally said about `get_product_positions`, and it sets
the rule for every tool that touches account figures: **series are opt-in and capped, never a
default.** `values`/`totalInvested`/`totalRedemptions` is already 3 requests per account; adding
`irrs`/`returns`/`percentageOfFundHistory` makes it 6. At the current `MAX_POSITION_ACCOUNTS` of 500
that is 3,000 queued requests behind a per-user gate of 5 — a batch job wearing a tool call's
clothes. `filter[date][ge]` does work on a series subcollection (`/accounts/{id}/values` → 8 rows of
164), so each call can be narrowed, but the request *count* is what hurts.

Two paths that look like the fast answer and are not, recorded so they are not retried:

- **`/accounts/{id}/analytics`** advertises 150+ metrics (`netIrrs`, `annualizedReturn`,
  `maxDrawdown`, …) selectable with `fields=`, returns `200` in ~400 B, and every metric comes back
  as `{start, end}` with **no value** on this instance. It is not an ITD-performance path.
- **`GET /reports`** is one call for 721 rows — and it took >180 s on two of three attempts, against
  a `reports_timeout_seconds` default of 120. `run_report` is a slow tool by nature; it must not sit
  on the answer path for anything a walk can serve.

### Name resolution and search

The IR team names things the way they say them — "Dispersion", "CGM", "Tail Hedging", "Paul B" —
and none of those are what Backstop stores. Two primitives cover it, and the split between them is
not the one this codebase currently assumes.

**`filter[<field>][like]` exists and is case-insensitive.** Both the skill notes and
`party_resolver/quick_search.py` state that Backstop's operators are `eq, neq, gt, ge, lt, le`.
`LIKE` is also supported — on some fields, on some collections:

| Collection | `[like]` on | Measured |
| --- | --- | --- |
| `/activity-tags` | `name` | `Dispersion` → 15, `CGM` → 3, `Tail` → 5 |
| `/products` | `name` | `dispersion` → 3 (lowercase matches) |
| `/organizations` | `name` | `Pension` → 603 of 5,105 |
| `/system-users` | `name` | `Lazarus` → 1 |
| `/accounts` | `name` | `Tobin` → 1 |
| `/people` | `lastName` **only** | `Tobin` → 1. `name` is `Unsupported filter operator: LIKE`; `firstName` is not a filter field; `email` rejects `LIKE` |
| `/opportunities` | — | `name` is not a filter field at all |
| `/custom-field-groups` | — | `name` is not a filter field |
| `/custom-field-definitions` | — | **accepted and silently ignored**: returns all 3,274 rows, 2.9 MB |

**`/quick-search` is prefix-anchored, not fuzzy.** `Dispersion` returns **0** products;
`Capstone Dispersion` returns 3; `Capstone Disp` also returns 3, so it matches a leading substring
of the whole name rather than any word in it. Its full type enum is wider than the four party
types this connector uses — `ALL, ACCOUNT, ASSET_GROUP, FUND_PRODUCT, HOLDING, OPPORTUNITY, DEAL,
ORGANIZATION, PERSON_FIRST_NAME, PERSON_LAST_NAME, PHONE_NUMBER, EMAIL_ADDRESS, STRATEGY, PROJECT,
VEHICLE, PRODUCT` — and hits carry `resourceId` plus `baseResourceType`, so extending it to
non-party types is mechanical.

So: **a resolve tool over `/quick-search` does not fix name identification on its own.** It cannot
resolve the tenant's short names, which is exactly the failing case. The division of labour:

- **People** — `/quick-search` (`PERSON_FIRST_NAME,PERSON_LAST_NAME`), as today. `filter[name][like]`
  is unsupported there; `filter[lastName][like]` is a useful second attempt when quick-search misses.
- **Organizations** — `resolve_party` as today (quick-search plus the email path and elicitation),
  with `filter[name][like]` as the fallback when quick-search returns nothing, since that is what
  turns a mid-name fragment into a hit.
- **Opportunities** — `/quick-search` with `OPPORTUNITY` is the *only* name path (`filter[name]` is
  rejected). Confirmed: `3M` → the 3M Pension Plan deal.
- **Products, activity tags, system users, accounts** — `filter[name][like]`, one request, no
  catalog walk. This is what makes "Dispersion", "CGM" and "Paul B" resolvable.

Every new list tool therefore takes an optional `search` argument, and it is a `[like]` query on the
collections above rather than client-side filtering after a walk. `resolve_product` can drop to a
single request: its docstring records that "`/products` filters only on `createdTimestamp,
entityTypeId, modifiedTimestamp, name, otherId`, so nothing filters on either one" — `name` does
filter, with `[like]`.

### Architecture

No new layers. Every item follows the shape the DI and model-layer refactors settled:

- `features/<domain>/` with the three model layers `api_responses.py` (`*Attributes`) →
  `internal_dto.py` (`*Dto`) → `responses.py` (`*Response`), and each fetch in a module named
  after the function it defines (`fetch_activities_page.py`, `fetch_accounts_for_product.py`).
- `features/<domain>/tools/<tool_name>.py` owning exactly one `@tool` named after the file, plus
  that tool's own wire models — a tool's contract lives beside it, not in a shared `responses.py`.
- Collaborators arrive as `Depends(...)` parameters (`get_backstop_client`,
  `get_custom_fields_service`, …), which stay out of the published schema. A new long-lived
  service means an `@lru_cache(maxsize=1)` provider in that feature's `dependencies.py`, exported
  through `__init__` and listed in `teardown.PROVIDERS`.
- The tool is reachable only once it is on `server/tools/registry.py`.
- Tests under `tests/features/<domain>/tools/`, driving `respx` routes through a real client from
  `tests.helpers.tool_client` and passing collaborators as kwargs — no Postgres.

`tests/test_layering.py` enforces the rules this leans on: `features/` ↛ `server/`, packages
entered through their `__init__`, the model-layer direction, module-named-after-its-symbol, and
rule 7 — every tool module appears in `TOOLS`. `tests/test_teardown.py` enforces the provider
teardown list.

Two existing mechanisms to extend rather than duplicate:

- **`features/includes/`** is the `?include=` allowlist: a field per exposed include carrying its
  Backstop `Include` metadata and its projected shape, read into an `IncludePlan`. The new
  `activityTags` / `attendees` side-loads on activity, and `owner` on the product-side accounts
  walk, belong there — not in a second hand-rolled `included` walker.
- **`features/accounts/fetch_accounts_for_product.py`** already lists a product's accounts with
  `filter[product.id][eq]`, `include=owner,investorType` and `ACCOUNT_LISTING_FIELDS`. That is
  most of `get_product_investors` already written and tested.

**Enhancements to the nine shipped tools**

| Tool | Change | Backlog ref |
| --- | --- | --- |
| `get_activity_history` | Side-load `activityTags` and `attendees`; surface `regarding`; add a tag-id filter. The date window (`since`/`until` per stream) and `activity_types` already ship | E2 |
| `get_product_positions` | **Not** the side-load collapse this design first proposed — that returns full history (§ Cost and latency). Keep the fan-out, lower the cap, put `values`/`totalInvested`/`totalRedemptions` behind one opt-in and `irrs`/`returns`/`percentageOfFundHistory` behind a second, and narrow each series call with `filter[date][ge]`. `accountStartDate`/`closedDate` already ship on `AccountRowResponse` | L1, H2 |
| `get_accounts_for_party` | Optional, capped series on the same fan-out. Affordable here because a party owns few accounts (815 across the instance), unlike the product side | L2 |
| `get_organization` / `get_person` | Join custom-field values to their definitions; return `definitionId`, `name`, `layoutName`, `groupName`, `fieldType` and resolved value; select by tab, group, definition id or name. Free at request time — the catalog is already cached. Must join against **`party` plus** the entity's own definitions: a measured org is 61 `OrganizationBean` + 31 `PartyBean`, and a measured person is 61 values, **100% `PartyBean`**, layouts `Events` (49) and `Readers` (12) | A1 |
| `list_custom_fields` | Fix the ~4× duplication (1028 rows for 257 unique ids) and carry `groupId`. `layoutName`, `groupName` and `tabName` already ship on `CustomFieldDefinitionDto` | A2 |
| `get_people_for_party` | Add `categories`. `jobTitle` already ships, from the `fields[employees]` contact card | H3 |
| `get_opportunities` | Resolve the `Master Pipeline` custom-field entries it already passes through (`definitionId` / `name` / `value`) against their definitions; keep the standard `probability` attribute and any rep-entered probability custom field distinctly named. Also surface `weightedValue` / `weightedAllocatedValue`, which Backstop computes on the row — this design had parked weighted pipeline value as agent-side arithmetic | D1 (the naming half only) |

**New tools**

| Tool | Source | Answers |
| --- | --- | --- |
| `list_activity_tags` | `GET /activity-tags` — **1 call**, 301 rows, cached. Carries `quantityTagged` and a `viewable` flag | Foundation for everything tag-scoped |
| `list_custom_field_groups` | `GET /custom-field-groups` — **1 call**, 1,458 rows, cached. `fullPathName` is an array of segments, `parent` is `{id, name, parentId}`. No field-membership relationship: membership is the definition's `groupId` (task 1) | Discovery of `Events`, `Readers`, `Trip Outreach`, `New Product Targeting`, `Investor Information`, `Master Pipeline`, `CI Notes`, `Capital Activity` |
| `find_activities` | `/meeting-or-calls`, `/notes`, `/documents` — **1 sparse walk per stream**, `filter[startTimestamp]`/`filter[createdTimestamp]` + `filter[activityTagIds]`, party from `regarding` (meetings, notes) or `attachedTo` (documents) | The workhorse — follow-ups last week, calls about product Y, cap-intro mentions, feedback by fund, who hasn't received the deck, pipeline groups with no contact |
| `get_product_investors` | `fetch_accounts_for_product` (already shipped: `filter[product.id][eq]`, `include=owner,investorType`) — **1 call**; series opt-in and capped | "List all organizations invested in Dispersion", with current value, share of fund, tenure |
| `find_opportunities` | `GET /opportunities` sparse walk — 1,206 rows, ~2 parallel pages, `include=investor,product` for the investor's geography in the same walk. Only `filter[representative.name]` filters server-side, and it matches the **login** (`blazarus`, not `Ben Lazarus`); stage, product, `isOpen` and amount are all `400 Invalid filter field` and stay client-side | Pipeline gaps, stuck in diligence, closing in 180 days, US investors in pipeline for Y |
| `get_capital_flows` | `/hedge-fund-account-subscriptions?include=fundAccount.owner` + `…-redemptions?include=originalSubscription.fundAccount` — **2 calls total**, party attribution included, `filter[transactionDate]` mandatory | Flows in and out, redeemed-from-one-product candidates |
| `get_tasks_for_party` | `GET /tasks` (540) — **1 call** with `filter[entityType][eq]=OrganizationBean` **and** `filter[entityId][eq]` sent together, plus `assignedUser`, `dueDate`, `status` from the row | Open follow-ups and commitments |
| `list_system_users` | `GET /system-users` — **1 call**, 99 rows, cached. Not optional: its `userName` is the key `find_opportunities` filters on | Resolving "Paul B" / "my coverage" to a representative |
| `run_report` | `GET /reports?asOfDate=…&reportName=…` — one call, 721 rows, but >180 s on two of three attempts. Slow by nature; not on any other tool's answer path | The team's own curated reports, projected and capped |

**Response discipline.** Two of the new tools (`find_activities`, `find_opportunities`) read whole
collections. Neither may relay them. Both take sparse fieldsets on the wire, return only
caller-selected fields, cap rows, and state rows scanned plus whether the result was truncated. Both
offer an aggregate mode (counts grouped by tag, type, party or period) so a counting question never
pays for row bodies. This is a new pattern for this codebase — every shipped tool projects one
resolved party or product — so it gets settled once in `find_activities` and reused.

### Error Handling

- **Collections that reject unfiltered reads.** `/meeting-or-calls` returns 400
  `"You can not query all meetings without filter criteria."`, and both
  `/hedge-fund-account-subscriptions` and `/hedge-fund-account-redemptions` return
  `"You can not query this resource without filter criteria."` So `find_activities` must always
  send a date window and `get_capital_flows` must always send `filter[transactionDate]`; a missing
  window is a tool-level validation error, not a passthrough 400.
- **Three different failure modes for a wrong filter, all of them silent-ish.** A genuinely unknown
  field errors cleanly (`filter[zzzNope]` → `400 Invalid filter field`). But `/tasks`
  `filter[entityId]` or `filter[entityType]` **alone** is accepted and ignored — 540 rows, the
  whole collection — and only validates when paired, where `organizations` and `ORGANIZATION` both
  fail and `OrganizationBean` works. And `/opportunities`
  `filter[representative.name][eq]=Ben Lazarus` returns **0 rows** while `blazarus` returns 157: a
  filter that fails *closed*, silently. Tests pin the exact param names, the Bean casing, the
  pairing, and the login-not-display-name semantics, because each of these looks like an answer.
- **`[like]` is a fourth failure mode.** On `/custom-field-definitions` it is accepted, ignored,
  and returns the entire 3,274-row / 2.9 MB catalog — the most expensive fail-open in this API. On
  `/people` and `/opportunities` it errors cleanly instead. Only send `[like]` where the table in
  *Name resolution and search* says it filters, and pin each one.
- **Comma-separated tag ids are AND, not OR.** `filter[activityTagIds][eq]=474963,438197` returns
  1 row where each tag alone returns 418 and 18. A union needs one call per tag; the tool must say
  which it does.
- **`/emails` has no tag support and no includes.** `filter[activityTagIds]` is
  `400 Invalid filter field activityTagIds`, and a firm-wide `/emails` date query did not return
  within 180 s. Email cannot participate in tag analytics. `find_activities` states the excluded
  stream in its output rather than letting totals look complete.
- **Unknown report name.** `GET /reports` returns a clean 400
  `"Report 'X' not found."`, and report names **cannot be enumerated** from the API. `run_report`
  surfaces this as a not-found response naming the report, and cannot offer suggestions.
- **Legacy custom-field values.** Values outside a field's current option list are preserved and
  flagged, never dropped or coerced — a live org holds `CGM = "Dialogue"` while that field's options
  are `4 - Client … 0 - Not Relevant`.
- **Missing series stay omitted, never zeroed** — the existing `get_product_positions` convention,
  extended to the new performance series.
- **`ENTITY`-typed custom-field values** carry a `resourceType`/`resourceId`; surface them as
  resolvable party references, not raw blobs.

### Testing Strategy

Behavioural, using the existing setup — `respx` routes through `tests.helpers.tool_client`, tool
tests under `tests/features/<domain>/tools/` with collaborators passed as kwargs. No new harness,
and no Postgres for a tool test.

- Recorded-response tests per tool, asserting the projection rather than the transport.
- **Regression test for the `list_custom_fields` duplication**, since that is a counting bug.
- **Filter-param pinning tests**: assert the exact query strings, because every wrong form of these
  fails quietly rather than loudly — `filter[activityTagIds]`, `filter[startTimestamp]` /
  `filter[createdTimestamp]`, `filter[transactionDate]`, the `/tasks` `entityType`+`entityId` pair
  with `OrganizationBean` casing, and `filter[representative.name]` receiving a login.
- **Request-count assertions.** Every tool that reads a collection asserts the number of requests
  `respx` saw, so a per-row fetch cannot creep back in: `find_activities` is one walk per stream,
  `get_capital_flows` two calls, `get_tasks_for_party` and `get_product_investors` one each, and
  `get_product_positions` is `accounts + 3n` (or `6n`) with the cap enforced.
- **Truncation and scan-coverage assertions** on `find_activities` and `find_opportunities`.
- The structural suites cover the rest without new work per tool, provided each tool follows the
  shape above: `tests/test_layering.py` (rules 1–7, including registration in `TOOLS`),
  `tests/server/tools/test_output_descriptions.py` (every published field described),
  `tests/server/tools/test_models.py` (`OmitNoneModel` / `published_output_schema`),
  `tests/test_validation_policy.py` (new `*Attributes` stay permissive) and
  `tests/test_teardown.py` (any new cached provider is torn down).

## Coverage against the question list

Margaret's survey, re-read against the confirmed API surface. "Deferred" means the cohort file, not
a gap in this design.

| # | Category | In scope | Deferred | No path |
| --- | --- | --- | --- | --- |
| 1 | Investor profile, holdings, accounts | 7 | — | — |
| 2 | Interaction history & meeting intelligence | 9 | — | — |
| 3 | Follow-ups, tasks, next best actions | 6 | 1 (region predicate) | 1 (`/emails`) |
| 4 | Investor targeting & prioritization | 4 | 5 | — |
| 5 | Relationship intelligence & coverage risk | 6 | 3 | — |
| 6 | Fundraising & pipeline intelligence | 6 | — | 1 (product capacity) |
| 7 | Accounts, allocations, flows, redemption risk | 6 | 1 (firm-wide cross-sell) | — |
| 8 | Marketing effectiveness & content engagement | 3 | 2 | 1 (`/emails`) |
| 9 | Events, conferences, invitations | 1 (+1 reasoning) | 2 | — |
| 10 | External intelligence | — | — | 1 (not in Backstop) |

Three things moved **into** scope on the strength of the re-check:

- **"U.S. investors in the pipeline for Y"** and the geography axis of the pipeline-gap question —
  `include=investor` on the opportunities walk carries `country`/`state`/`city`, so no organization
  walk is needed. `/organizations` rejects `filter[country]` and `filter[city]`, which is why this
  looked like cohort work.
- **"Which contacts have gone quiet despite previously strong engagement?"** — two date-windowed
  `find_activities` aggregations grouped by `regarding`. No party walk.
- **"I am looking to do outreach for Convertible Arbitrage"** partially — products carry a
  `Strategy` custom field (`Strategy: Dispersion` on the Dispersion LP), so strategy → product is a
  lookup. Only the "which orgs to target" half stays deferred.

Two hard gaps, both worth telling Margaret about rather than designing around:

- **Anything anchored on email.** "From the emails Paul B has sent year-to-date, how many follow-up
  calls or meetings have been scheduled?" `/emails` rejects `filter[activityTagIds]` and a firm-wide
  date query does not return within 180 s. Follow-ups sourced from meetings, calls, notes and tasks
  are answerable; the email-origin count is not.
- **"How much Dispersion capacity is left?"** The product's custom fields are `Fee Structure`,
  `Domicile`, `Strategy`, `Onshore/Offshore`, `Fund Structure` — no capacity field. The inflows half
  (pipeline for the product) is answerable; capacity has no Backstop source on this instance.

## Out of Scope

- **The 14 cohort questions** — anything needing predicates over all 5,105 organizations or all
  20,524 people. Reasoning, measurements and options in `docs/backstop-mcp-cohort-questions.md`.
- **External intelligence** (category 10: public pension IC calendars, board dates, mandate reviews).
  No Backstop path exists.
- **The GVS seating chart.** A reasoning task over data this design delivers, not a missing tool.
- **Write-back (Epic K).** No question on Margaret's list requires it. It remains a separate
  commitment.
- **Dashboard arithmetic (Epics D, G, H1).** RAG bands, cohort indices and the page-11 briefing
  panel stay agent-side projections over these tools. Weighted pipeline value is the exception and
  moves in: Backstop already computes `weightedValue` / `weightedAllocatedValue` on the opportunity
  row, so relaying it is cheaper and more faithful than recomputing it.
- **Tenant semantic profile (A5).** `list_custom_field_groups` plus resolved values is what lets an
  agent learn the tenant; role-name config is not needed for any question here.
- **`/activity-search`, `/entity-activities`, `/entity-activities-filters`.** In the swagger, 404 on
  this instance. No full-text activity search exists.

## Tasks

1. **Fix `list_custom_fields` duplication and add `groupId`** — The whole catalog is **13,096 rows
   for 3,274 unique definition ids**; every id appears exactly 4× and the four copies are
   byte-identical (same `layoutName`, `tabName`, `groupName`, `groupId`), so dedupe by id is
   lossless. (The "1028 rows for 257 unique" in the first pass was just the `OrganizationBean`
   slice.) `groupId` is already on the wire and simply missing from
   `CustomFieldDefinitionAttributes`; it is the join key to `custom-field-groups`. Also document
   what the entity split means for callers: `PartyBean` holds 11,720 of the 13,096 rows (2,930
   unique) against 1,028 organization and **84** person rows, so `entity_types=["people"]` returns
   21 definitions and looks empty — the tenant's model is `party`. Blocking for every custom-field
   task below; add a counting regression test.
2. **Add `list_custom_field_groups`** — Wrap `GET /custom-field-groups`, returning the tab → section
   hierarchy from `fullPathName` and `parent` with field membership. This is how an agent discovers
   `Events`, `Readers`, `Trip Outreach` and `New Product Targeting` without us naming them.
3. **Resolve and slice custom-field values on `get_organization` / `get_person`** — Join values to
   definitions and add selection by tab, group, definition id or name. The join is exact: a measured
   org resolved **92 of 92** values, a measured person **61 of 61**. Resolve against the `party`
   catalog *and* the entity's own — the org split 61 `OrganizationBean` / 31 `PartyBean`, the person
   was 100% `PartyBean` (`Events` 49, `Readers` 12). No extra requests: the catalog is cached.
   Preserve and flag out-of-option-list values; surface `ENTITY`-typed values — confirmed shape
   `{resourceType, resourceId, resourceLink}` — as party references.
4. **Add `list_activity_tags`** — Wrap `GET /activity-tags` with the same caching as other reference
   vocabularies. One call, 301 rows, attributes `name` / `quantityTagged` / `viewable` — publish
   `quantityTagged` so an agent can tell a live tag from a dead one, and `viewable` because some
   tags are hidden in the UI. Small, and unblocks tasks 5 and 6.
5. **Put tags, attendees and `regarding` on `get_activity_history`** — Side-load `activityTags`
   and `attendees` through a `features/includes/` allowlist model, surface `regarding`, and add a
   tag-id filter to `fetch_activities_page`. The per-stream date window and `activity_types`
   already ship; keep that module's documented filter quirks (`ge`+`le` returns zero rows; never
   send `filter[sentTimestamp][ge]`).
6. **Add `find_activities`** — Firm-wide activity query over `/meeting-or-calls`, `/notes` and
   `/documents` by date window and tag. One sparse walk per stream, no per-row follow-up: party
   attribution is `regarding` on meetings and notes and **`attachedTo` on documents**, which carry
   no `regarding`. Tag filtering is confirmed on all three (`/notes` 8,168 → 159, `/documents`
   6,657 → 9) and comma-separated ids intersect rather than union. Establishes the rows-vs-aggregate
   response pattern, row caps and scan-coverage reporting. Document the excluded email stream.
7. **Bound `get_product_positions` and make its series opt-in** — Replaces this design's original
   "collapse the fan-out into one walk", which the measurements killed: `include=values` returns the
   whole 164-point history per account (56 KB), `fields[time-series]` trims ~29%, there is no
   `/time-series` collection, and includes cannot be date-filtered. So keep
   `fetch_product_positions`' fan-out and make it honest instead:
   - `values`/`totalInvested`/`totalRedemptions` behind one opt-in flag, `irrs`/`returns`/
     `percentageOfFundHistory` behind a second — the second doubles requests per account from 3 to 6.
   - Lower `MAX_POSITION_ACCOUNTS` from 500 accordingly, and keep publishing what was omitted.
   - Narrow each series call with `filter[date][ge]` (confirmed: `/accounts/{id}/values` → 8 rows of
     164), keeping `fetch_series`' rule that the newest row may be dated but unvalued.
   All three new series are the same `{date, value}` shape as the existing ones, so `fetch_series`
   works unchanged — including `returns`, whose newest row arrived with a `date` and no `value`.
   Account start/closed dates already ship. Do **not** reach for `/accounts/{id}/analytics`: it
   advertises 150+ metrics, returns 200, and every metric is an empty `{start, end}` envelope.
8. **Add optional balances to `get_accounts_for_party`** — Reuse task 7's fan-out, same opt-in and
   cap. Affordable here in a way it is not on the product side: a party owns a handful of the
   instance's 815 accounts, so this is a few requests, not a few hundred. The tool stays a single
   fast listing when the flag is off.
9. **Add `get_product_investors`** — A tool over the shipped `fetch_accounts_for_product`, which
   already returns owners in one call. Series and share-of-fund are task 7's opt-in, and here the
   cap matters: a product carries tens to low hundreds of accounts, so series-on is a few hundred
   requests. Default off, and say so in the docstring. Note "Dispersion" resolves to several product
   records (the US LP alone has 20 accounts), so product ambiguity is the caller's to settle through
   `resolve_product`.
10. **Add `find_opportunities`** — Sparse firm-wide pipeline walk: 1,206 rows, 908 B/row sparse
    against 7.2 KB full, ~2 parallel pages. Exactly one filter is server-side and it is a trap —
    `filter[representative.name][eq]` matches the system user's **login**, so `blazarus` returns 157
    rows and `Ben Lazarus` returns 0 with no error. It therefore depends on task 13 to translate a
    name into a login, and the docstring must say the parameter takes a login. `filter[stage.name]`,
    `filter[product.name]` and `filter[isOpen]` are all `400 Invalid filter field`; stage, product,
    date and amount stay client-side over the walk. Side-load `investor,product` so geography comes
    back in the same walk — that is what answers "U.S. investors in the pipeline for Y" and the
    geography axis of the pipeline-gap question without a second call, since `/organizations`
    rejects `filter[country]` and `filter[city]`. **The investor include arrives as a `contacts`
    resource**, so the sparse key is `fields[contacts]=name,country,state,city`; without it every
    row drags a ~7 KB `contactDescription`.
11. **Add `get_capital_flows`** — Two calls, no per-row work:
    `/hedge-fund-account-subscriptions?include=fundAccount.owner` and
    `/hedge-fund-account-redemptions?include=originalSubscription.fundAccount`. Both confirmed:
    nested includes return the account and, for subscriptions, the owning party. The asymmetry is
    real and worth a comment — a redemption has no `fundAccount` relationship of its own and reaches
    its account only through `originalSubscription`, so a redemption with no original subscription
    cannot be attributed and must be reported as such rather than dropped. `filter[transactionDate]`
    is mandatory (unfiltered is 400) and genuinely filters (1,244 since 2020 / 411 since 2024 / 164
    since 2026). Actuals only; targets are a caller input.
12. **Add `get_tasks_for_party`** — One call against `GET /tasks` (540 rows), with **both**
    `filter[entityType][eq]` and `filter[entityId][eq]` — the pair filters (→ 1 row for a test org),
    either alone is silently ignored and returns all 540, and the entity type is Bean-cased:
    `OrganizationBean` works, `organizations` and `ORGANIZATION` are 400. Assignee, `dueDate` and
    `status` come off the row; the party ref is `attachedTo`. `status` is not filterable
    (`400 Invalid filter field status`), so open-vs-completed is a client-side split.
13. **Add `list_system_users`** — Wrap `GET /system-users` (one call, 99 rows, cached) so "Paul B"
    or "my coverage" resolves to a representative. `features/includes/` already projects that
    resource as `InternalOwnerResponse` for the `representative` include — reuse the shape rather
    than inventing a second one. Not the small independent task it looked like: it publishes the
    `userName` that task 10's only server-side filter matches on, so it ships before or with
    `find_opportunities`. Publish `disabled` too, so a departed colleague's name does not silently
    return an empty pipeline.
14. **Add `run_report`** — `GET /reports` by `asOfDate` + `reportName`, projecting and capping the
    tabular result. Report names come from configuration or the caller; they cannot be enumerated,
    and an unknown name must surface as a clear not-found (confirmed: `400 Report 'ZzzNope' not
    found.`). `BackstopConfig` already carries the `/reports` knobs (`reports_timeout_seconds`, the
    reports page size), so no new config. Treat latency as a first-class part of this tool's
    contract: the same `Accounts` report returned 721 rows once and exceeded 180 s on two further
    attempts, against a 120 s default timeout. It is a last resort, and no other tool may depend on
    it.
15. **Give the list tools a `search` argument, and simplify `resolve_product`** — One optional
    `search` on `list_activity_tags`, `list_system_users` and the product path, implemented as
    `filter[name][like]` (one request, case-insensitive) rather than a walk plus client-side
    matching. Add the `filter[name][like]` fallback to organization resolution for the mid-name
    fragment case, and `filter[lastName][like]` as a second attempt for people. Correct the two
    docstrings that state the wrong operator set (`resolve_product`, `quick_search`) and note that
    `/quick-search` is prefix-anchored. Do **not** send `[like]` to `/custom-field-definitions`.

16. **Add `categories` to `get_people_for_party`** — Small addition supporting relationship maps
    and distribution-list membership. `jobTitle` already ships.
17. **Update `instructions.py` and `registry.py`** — Register the nine new tools and rewrite the
    orientation text to route questions to the right tool, including the tag and custom-field-group
    discovery path. If `2026-08-20-backstop-mcp-tool-discovery-design.md` lands first, registration
    becomes automatic and only the orientation text is left.

## Implementation sequence

The task numbering above is grouped by subject, not by order of work. This is the order, and the
dependencies are real rather than stylistic — each one is a case where doing the later task first
means writing something twice or shipping something that cannot be called.

**Before slice 1:** reconcile against the UN-236xx sub-tasks and the Confluence requirements page
(first item under *Open questions*). These 17 tasks were written from the question list and the API,
not from the tickets, so some of them may already exist as tickets with different boundaries.

### Slice 1 — the custom-field foundation: tasks 1 → 2, 3

Task 1 (dedupe, `groupId`) blocks both others: task 2's group hierarchy is joined to fields by
`groupId`, and task 3's value resolution reads the deduped catalog. Tasks 2 and 3 are then
independent of each other.

Do this first because task 3 is the single largest coverage unlock in the design — it is what makes
`Events`, `Readers`, Grade / Status / Investor Status and the product-interest matrix addressable at
all, and categories 3, 4, 5, 8 and 9 of the question list all lean on it. Every request here is
either cached or free: no new fan-out, so there is nothing to measure.

### Slice 2 — the topic axis: tasks 4 → 5 → 6

Task 4 (`list_activity_tags`) is a one-call reference tool and unblocks the other two, which need
tag ids. Task 5 puts tags on the existing party-scoped tool; task 6 (`find_activities`) is the
firm-wide one.

Land task 6 **before** task 10. It is where the rows-vs-aggregate response shape, the row cap and
the scan-coverage statement get settled, and `find_opportunities` is meant to reuse that pattern
rather than invent a second one. Getting these in the other order means rewriting one of them.

### Slice 3 — pipeline: tasks 13 → 10

Task 13 (`list_system_users`) is not the small independent chore it looks like. It publishes the
`userName` that `filter[representative.name]` matches on, and that filter fails **closed** — a
display name returns zero rows with no error. `find_opportunities` without it is a tool that
silently answers "no pipeline" for every coverage question.

### Slice 4 — money: tasks 7 → 8, 9

Task 7 is the only slice with an open quantity in it: the default position cap, which needs the
latency measurement described under *Open questions*. Take that measurement here, in this slice, and
record the number in the code with the measurement beside it — tasks 8 and 9 both reuse task 7's
opt-in flags and cap, so settling it once is the point of doing 7 first.

### Slice 5 — the one-call additions: tasks 11, 12, 15, 16

Mutually independent, each one call or fewer, any order. Task 15 (`search` arguments) is worth doing
inside this slice rather than after it: it is what makes the tools from slices 2-4 usable with the
names the IR team actually says, and it corrects two docstrings that currently state the wrong
filter-operator set.

### Slice 6 — task 17, last

`instructions.py` can only route questions to tools that exist. Rewriting it earlier means rewriting
it again. Note the routing hazard recorded under *Open questions*: custom-field questions must be
routed through `party`, not `people`.

### Held back — task 14 (`run_report`)

Do not build this on spec. It cannot enumerate report names, it exceeded 180 s on two of three
attempts against a 120 s default timeout, and nothing else in the design depends on it. Wait for
Margaret's report names and definitions, then decide whether it is worth building at all.

### Definition of done, per tool

Beyond the behavioural tests: a **request-count assertion** (so a per-row fetch cannot creep in),
and a **filter-param pinning test** for every filter the tool sends. The second is not optional
paranoia — this API has four distinct ways for a wrong filter to look like an answer, catalogued
under *Error Handling*.

## Open questions

- **No Jira ticket is linked to this work.** Existing backstop-mcp features have UN-236xx sub-tasks
  and the backlog references a Confluence requirements page; these 17 tasks should be reconciled
  against them before implementation rather than duplicating tickets.
- **~~Do `Events` and `Readers` custom-field groups hang off people or organizations?~~**
  **Answered: neither — they are `PartyBean`.** A `Read` definition carries
  `entityType: PartyBean`, `resourceType: contacts`, `layoutName: Readers`,
  `groupName: December 2024 CPPM Newsletter`. A measured person's 61 custom-field values are 100%
  `PartyBean`, split `Events` (49) and `Readers` (12), and a single person's values read fast — the
  earlier 120 s timeout was a bulk walk, not a record read. The consequence is a routing hazard, not
  a gap: an agent asking `list_custom_fields(entity_types=["people"])` gets 21 definitions and
  concludes there is nothing there, so `instructions.py` (task 17) must route custom-field questions
  through `party`.
- **~~Tag filter on `/documents` and `/emails`~~** **Answered.** `/documents` filters (6,657 → 9);
  `/emails` returns `400 Invalid filter field activityTagIds` and a firm-wide date query does not
  return within 180 s. State the exclusion in output as planned.
- **~~`.gitcommitizen` has no scope covering `docs/plans/`~~** — settled in practice: the design
  docs on this branch are committed as `docs(main)`, which the hook accepts. Only the choice of
  *where* these docs live is still open (`docs/plans/` at the repo root vs
  `services/backstop-mcp/docs/`, which the `backstop-mcp` scope covers).
- **Is share class a holdings answer or a flows answer?** "Which share class or share classes is
  Investor Name invested in within Fund Name?" reads as a holdings question, but `shareClass` /
  `shareSeries` live on the subscription, not on the account — `/accounts` has no share-class
  relationship. So it is answered by `get_capital_flows`, not `get_accounts_for_party`. Confirm that
  is acceptable, or task 8 needs to reach into subscriptions to label each holding.
- **How low should the position cap go, and is series-on-by-default ever right?** Task 7 makes
  series opt-in; what it does not settle is the default cap once 6 requests per account is possible.
  A concrete answer needs a latency measurement of the fan-out at 25 / 50 / 100 accounts through the
  real per-user gate, which is a task-7 implementation step rather than a design decision.
- **Is there a saved report that returns balances for all accounts in one call?** The `Accounts`
  report exists, returns 721 rows and carries `Backstop Party ID`, which would make firm-wide
  balances one call instead of a fan-out — but it exceeded 180 s twice, and Margaret has offered the
  report names and definitions her team uses. Worth asking her for the column list before assuming
  `run_report` can stand in for the series path.
