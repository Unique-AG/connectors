# UN-23685 implementation plan

Write-back MCP tools for opportunities, custom fields, contact corrections and employment.
This plan is prescriptive: the API behaviour is already measured, the open product questions
are already answered, and the slices below are meant to be implemented in order without
re-deciding anything.

## Before you write any code

Read these, in this order:

1. `docs/un-23685-write-semantics.md` — what the Backstop API actually does. **Every payload
   shape here comes from there.** Do not "correct" a payload against the swagger; the swagger
   is wrong or silent about most of it. Create/delete tools built on those measurements:
   `docs/un-23685-create-delete-semantics.md`.
2. `AGENT_README.md` — repo conventions. Especially "Feature shape", "Names and suffixes",
   "Write tools and commands", "Write payloads", "Tests".
3. `src/backstop_mcp/features/activity_writes/` — the reference write feature.
4. `tests/features/activity_writes/` — the reference write tests.

**When this plan and `activity_writes` disagree, `activity_writes` wins.** Tell the reviewer
rather than inventing a third shape.

**Do not call the live Backstop API.** Everything needed was already probed. Tests mock the
HTTP boundary with respx. `src/` and `tests/` must never import or mention `agent-explore/`.

### Ground rules that are already tested and will fail CI if broken

- Never mutate a function argument. Return new data.
- `assert` for internal invariants; `raise` only at the boundary (user input, Backstop errors).
- Enter a feature package through its `__init__`; `__all__` is the contract.
- Model layers flow one way: `responses` → `internal_dto` → `api_responses`.
- A logic file is named after the symbol it defines.
- Every tool module must be in `server/tools/registry.py` `TOOLS`.
- Every `@lru_cache` provider must be in `teardown.py` `PROVIDERS`.
- No `Any`. No `extra="forbid"`.

---

## Decisions already made (do not re-open)

| Decision | Why |
| --- | --- |
| **No `confirm` parameter and no preview mode.** | The agent discusses the change with the user, and `destructive_hint=True` makes the host approval prompt the confirmation — the same gate `update_activity` / `delete_activity` already rely on. A `confirm` flag would be a second, redundant gate. |
| Tool 2 is named **`backfill_opportunity_stage_history`** | It is built on `POST /bulk-opportunity-stage-history`, which appends history rows and **does not move a deal's stage**. The old name `update_opportunity_stages` promised something the endpoint does not do. |
| **There is no bulk stage-move tool.** Moving several deals is the agent calling `update_opportunity` once per deal. | Product decision. It keeps one honest write path per deal — each call reads, patches and re-reads that one deal, so a deal whose stage did not move is reported against that deal instead of being averaged into a batch summary. |
| `update_custom_field_values` is **entity-agnostic**, not party-only | `POST /bulk-custom-field-values` accepts `resource.resourceType` of `people`, `organizations` **and** `opportunities` — verified live. One tool covers all three; no per-entity custom-field section anywhere. |
| An entity-update tool exposes **every updatable field**, not a hand-picked subset | Product decision. The exclusion list below is the documented boundary. |
| Contact locations are edited **through `update_person` / `update_organization`**, not a separate tool | Product decision: if it belongs to the contact, it goes on the contact tool. |
| Bulk cap is **15** records | Product decision. |
| A PATCH sends **only the fields being changed** | PATCH is merge on every endpoint we touch. No resend of `lastName` / `gender` / `name`. |
| Every stage write **re-reads** and reports the stage Backstop landed on | A stage move can silently not happen. |
| The connector **never** derives `probability` from the stage | Backstop does not do this; there is no implied value. The caller sets it or it is untouched. |
| Custom-field regular-vs-time-series branching comes from **the catalog**, never the caller | Both wrong branches are hard per-record failures with opposite messages. |
| `end_employment` writes a non-past end date and **says it is not yet former** | Product confirmed. The read path compares `ended < today` strictly. |

There are no open questions. Every product decision this ticket needed has been answered.

---

## Tool inventory

| Tool | Feature package | Endpoint |
| --- | --- | --- |
| `update_opportunity` | `opportunity_writes` | `PATCH /opportunities/{id}` |
| `backfill_opportunity_stage_history` | `opportunity_writes` | `POST /bulk-opportunity-stage-history` |
| `update_custom_field_values` | `custom_fields` (existing) | `POST /bulk-custom-field-values` |
| `update_person` | `org_people_writes` | `PATCH /people/{id}` + `/contact-locations` |
| `update_organization` | `org_people_writes` | `PATCH /organizations/{id}` + `/contact-locations` |
| `end_employment` | `org_people_writes` | `PATCH /entity-relationships/{id}` |

Custom-field writes live in the existing `custom_fields` feature because the catalog they
validate against, and the picklist matcher they reuse, are already there. Adding
`commands/` and `tools/` packages to that feature is expected — `AGENT_README.md` says to add
the package when the first command appears.

## Response shapes

Follow `UpdatedActivityResponse`: a write response is **small**. It reports the id, the
resource type, and only the extra fields a measured trap requires.

In `opportunity_writes/responses.py` and `org_people_writes/responses.py` respectively:

```python
class UpdatedOpportunityResponse(OmitNoneModel):
    id: str
    resource_type: str  # "opportunities"
    stage: str | None  # stage name READ BACK after the write
    stage_id: str | None
    warnings: tuple[str, ...]  # empty when nothing needs saying
```

`warnings` is how a silent failure becomes visible — a requested stage that did not move, an
end date that is not yet in the past. Never return an empty success for those.

For the multi-record tools (`backfill_opportunity_stage_history`,
`update_custom_field_values`), add to the owning feature's `responses.py`:

```python
class RecordOutcomeResponse(OmitNoneModel):
    index: int  # 0-based position in the request
    record_id: str | None
    status: Literal["applied", "failed"]
    error: str | None
```

and a wrapper with `total_count`, `applied_count` and `records`. There is no `"preview"`
status — there is no preview.

---

## Slice 1 — `update_opportunity`

New feature package `src/backstop_mcp/features/opportunity_writes/`.

```
features/opportunity_writes/
  __init__.py
  dependencies.py
  api_responses.py
  responses.py
  update_opportunity_input.py
  commands/
    __init__.py
    _json_api_utils.py
    update_opportunity_command.py     UpdateOpportunityCommand
  tools/
    update_opportunity.py             update_opportunity
```

### Input — every updatable field

`UpdateOpportunityInput(BaseModel)`. `opportunity_id: NonEmptyStr` is required; everything
else defaults to `None` and is omitted from the payload when unset.

**Attributes** — `name`, `description`, `aliases`, `other_id`,
`classification` (wire `type` — the deal's classification, *not* the JSON:API resource type),
`currency_code`, `is_erisa`, `requested_amount`, `allocated_amount`, `probability`
(a fraction, not a percentage), `expected_investment_date`, `stage_effective_date`,
`waitlist_id`.

**Relationships** — `stage` (a stage **name**, resolved against the vocabulary),
`investor_id` (`contacts`), `product_id` (`products`), `primary_contact_id` (`people`),
`referral_source_id` (`contacts`), `owner_login` (a `list_system_users` `userName`,
resolved through `SystemUsersService` — never a raw id; Backstop's `representative`),
`investor_type_id` (`investor-types`), `add_users_to_notify` / `replace_users_to_notify`
(to-many; Backstop's `ccedUsers` — see the append trap below).

**Excluded, with reasons — put each reason in the field docs or the module docstring:**

| Excluded | Reason |
| --- | --- |
| `weightedValue`, `weightedAllocatedValue`, `isOpen`, `previousStage`, `daysOpen`, `daysInCurrentStage`, `dateEnteredCurrentStage`, `closedDate`, `effectiveDate`, `landingPageUrl`, `associationType` | Derived or read-only. Backstop computes them; sending them is wrong. |
| `regularCustomFieldValues` | Goes through `update_custom_field_values`, which validates against the catalog. Writing it inline here skips picklist and time-series validation. |
| `permissionBucket` | Permissions are not in this ticket's scope. |

Add a `@model_validator(mode="after")` requiring at least one change field — copy
`_at_least_one_change` from `activity_writes/update_activity_input.py`, treating
`opportunity_id` as the only identity field. Add a second validator: `stage_effective_date`
without `stage` is a `ValueError`.

Export `UPDATE_OPPORTUNITY_INPUT_DESCRIPTION` alongside the model, the way
`UPDATE_ACTIVITY_INPUT_DESCRIPTION` is.

### Command — `UpdateOpportunityCommand`

Constructor: `client: BackstopClient`,
`opportunity_stages_service: OpportunityStagesService`,
`system_users_service: SystemUsersService`.

`async def run(self, *, opportunity: UpdateOpportunityInput) -> UpdatedOpportunityResponse`

1. **Read the record** — `GET /opportunities/{id}?include=stage` into
   `BackstopApiSingleResourceDocument[OpportunityResourceAttributes]`. A missing id is
   Backstop's own 404; let the client raise. This read is needed for the stage guard, not for
   a preview.
2. **Resolve the stage name → id** against `opportunity_stages_service.get_catalog()`
   (`dict[str, OpportunityStageResponse]` keyed by stage id), matching `name` casefolded. No
   match → `raise ToolError` listing every available stage name, before any write.
3. **Resolve logins → system-user ids** through `SystemUsersService` for
   `owner_login` (unknown is a `ToolError`) and the notify-list fields (unknown logins
   are skipped and listed in `warnings`).
4. **Guard the silent no-move.** If `stage_effective_date` is earlier than the record's
   `date_entered_current_stage`, `raise ToolError`: Backstop would record a history row
   without moving the deal; omit the date to move it today.
5. **PATCH**, then **re-read** step 1 and build the response from the re-read.
6. If a stage was requested and the re-read stage does not match, return with a `warnings`
   entry saying the move was not applied. Do not report a bare success.

### Payload

```json
{"data": {"type": "opportunities", "id": "<id>",
  "attributes": {"name": "...", "requestedAmount": 1000000, "probability": 0.3,
                 "stageEffectiveDate": "2026-09-14"},
  "relationships": {"stage": {"data": {"type": "opportunity-stages", "id": "42482"}},
                    "product": {"data": {"type": "products", "id": "1292283"}},
                    "ccedUsers": {"data": [{"type": "system-users", "id": "2967455"}]}}}}
```

Omit every key the caller did not set (`omit_none_values`). `stage` and the other pointers are
**relationships**, never attributes.

### The to-many append trap — notify list (`ccedUsers`)

A to-many relationship PATCH **appends**; it does not replace. `data: []` clears the whole
collection. So a "set the notify list to exactly these people" operation is clear-then-add, i.e.
two writes.

Expose this honestly as two fields rather than one that lies:

- `add_users_to_notify` — appends. One PATCH. The natural operation.
- `replace_users_to_notify` — clears then adds. Two PATCHes, and the field description says
  so. An empty tuple clears.

Setting both is a `ValueError`. Do not offer "remove one member" — the API cannot express it.

### Tool

```python
@tool(
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=True,
        idempotent_hint=True, open_world_hint=False,
    ),
    output_schema=published_output_schema(UpdatedOpportunityResponse),
)
```

Docstring must say: `stage` is a **name** resolved against this instance's vocabulary;
`probability` is a fraction and is **not** changed by setting a stage (pass it explicitly);
a `closed` stage closes the deal automatically; custom fields go through
`update_custom_field_values`; omit a field to leave it unchanged. Include a `Call like:` JSON
sample.

It must also say that **this is the only way to move a deal's stage, and moving several deals
means calling it once per deal** — there is no bulk stage-move tool, and
`backfill_opportunity_stage_history` does not move anything. Without that sentence the model
will eventually find the backfill tool and use it for a status change.

### Dependencies, exports, registration

- `dependencies.py`: `@lru_cache(maxsize=1) get_update_opportunity_command_factory(...)`
  depending on `get_backstop_client_for_current_caller`,
  `get_opportunity_stages_service_factory` and `get_system_users_service` — all already cached.
- Export command, input, description, response and factory from `__init__.py` `__all__`.
- Add `update_opportunity` to `TOOLS`; add the factory to `teardown.PROVIDERS`.

### Stage-vocabulary DTO extension (ticket item)

Add `probability` to `OpportunityStageAttributes` and `OpportunityStageResponse` in
`features/opportunities/`, and side-load `include=opportunityTypes` in
`OpportunityStagesService._fetch_stages` so a stage carries its entity types.

**Scoping cannot be tested against real data:** all seven stages map to the single entity type
`16` ("Opportunity") and every opportunity has `clientDefinedEntityType = 16`, so every stage
is valid for every deal. Build the mechanism, cover it with a synthetic respx fixture that has
two types, and do not expect the out-of-type rejection to fire in the sandbox.

### Tests — `tests/features/opportunity_writes/`

Follow `tests/features/activity_writes/` exactly: **flat `test_<symbol>.py` files**, no
`conftest.py` in the feature folder, helpers imported from `tests/helpers.py`
(`BASE_URL`, `client_factory`, `credential`, `recorded_json_bodies`, `resource`, `collection`,
`system_users_service`), a local `client` fixture yielding
`client_factory().for_credential(credential())`, and a module-level `TypeAdapter` for the
input model. Build `OpportunityStagesService.with_ttl_minutes(client=client, ttl_minutes=60)`
directly, as `tests/features/opportunities/conftest.py` does — and copy its `VOCABULARY`
fixture shape for stage rows.

Add an `opportunity_stages_service(client, *, ttl_minutes=60)` helper to `tests/helpers.py`
beside the existing `custom_fields_service` / `system_users_service` / `time_zones_service`.

`test_update_opportunity_command.py`:

- `test_stage_is_patched_as_a_relationship` — assert on the recorded body that
  `relationships.stage.data.type == "opportunity-stages"`.
- `test_derived_fields_are_never_sent` — assert `attributes` has no `previousStage`,
  `isOpen`, `weightedValue`, `daysOpen`, `closedDate`.
- `test_only_supplied_fields_appear_in_the_payload`
- `test_unknown_stage_name_lists_valid_stages_and_does_not_write`
- `test_backdated_stage_effective_date_is_rejected_before_writing`
- `test_stage_that_does_not_move_is_reported_in_warnings` — respx returns a re-read whose
  stage is unchanged.
- `test_add_users_to_notify_sends_one_patch`
- `test_replace_users_to_notify_clears_then_adds`
- `test_owner_login_is_resolved_to_a_system_user_id`

`test_update_opportunity_input.py` for the validators, and
`tools/test_update_opportunity.py` for the tool wiring.

**Done when:** `uv run pytest tests/features/opportunity_writes tests/features/opportunities tests/test_layering.py tests/test_teardown.py tests/server/tools/test_output_descriptions.py tests/server/tools/test_input_descriptions.py` passes.

---

## Slice 2 — `backfill_opportunity_stage_history`

Same feature package. `POST /bulk-opportunity-stage-history`.

**This tool does not move any deal's stage.** It appends rows to stage history, for
backfilling a pipeline's past. The tool name, docstring and response must all say so — the
previous name (`update_opportunity_stages`) is what made this endpoint look like a status
update. It also rewrites `previousStage` on the affected deals as a side effect; mention that.

To actually move a deal, callers use `update_opportunity`.

### Files

```
commands/backfill_opportunity_stage_history_command.py   BackfillOpportunityStageHistoryCommand
backfill_opportunity_stage_history_input.py
tools/backfill_opportunity_stage_history.py
```

### Input

`OpportunityStageHistoryRecordInput`: `opportunity_id: NonEmptyStr`, `stage: NonEmptyStr`
(name), `effective_date: date` (required — this is a historical record; a row with no date is
meaningless).

`BackfillOpportunityStageHistoryInput`: `records: tuple[..., ...]` with
`Field(min_length=1, max_length=MAX_STAGE_HISTORY_RECORDS)` where
`MAX_STAGE_HISTORY_RECORDS = 15` is a module constant named in the field description.

### Payload — note the pointer shape

```json
{"data": {"type": "bulk-opportunity-stage-history", "attributes": {"records": [
  {"effectiveDate": "2026-02-01",
   "opportunity": {"resourceId": "5755101", "resourceType": "opportunities"},
   "stage": {"resourceId": "42482", "resourceType": "opportunity-stages"}}]}}}
```

`opportunity` and `stage` are `{resourceId, resourceType}` **attributes**, not JSON:API
`{type, id}` relationships. This endpoint is the exception — do not copy slice 1's shape.

### Command behaviour

1. Resolve every record's stage name → id first. If **any** record fails, raise before writing
   anything — a validation failure never writes.
2. One POST for the whole batch.
3. **Read `bulkLoadSummary`.** The response is `201` even when nothing was written:
   `{"totalCount": 2, "successCount": 1, "errorMessages": [{"index": 1, "message": "..."}]}`.
   `index` is 0-based. Map each `errorMessages` entry onto its record as
   `status="failed"` with that message; the rest are `"applied"`. Never treat `201` as success
   and never swallow a partial failure.

Model the summary in `opportunity_writes/api_responses.py` as `BulkLoadSummaryAttributes`.

### Tests

- `test_pointers_use_resource_id_and_resource_type`
- `test_over_the_cap_is_rejected_by_the_input_model`
- `test_one_invalid_stage_name_blocks_the_whole_batch`
- `test_partial_failure_is_reported_per_record`
- `test_total_failure_on_201_is_not_reported_as_success`

---

## Slice 3 — `update_custom_field_values`

Extend the **existing** `features/custom_fields/` feature. Add `commands/` and `tools/`.

### Why it lives here and covers three entity types

`POST /bulk-custom-field-values` takes a polymorphic `resource` pointer. Verified live against
`people` and `opportunities` (an opportunity dropdown definition wrote and read back). So one
tool covers people, organizations and opportunities, and no entity tool needs a custom-field
section. The catalog and its picklist matcher already live in this feature.

`PATCH /opportunities/{id}` also accepts `regularCustomFieldValues` inline — **do not use
it.** The bulk endpoint addresses individual definitions and validates them; the inline
attribute skips all of that.

### Input

`UpdateCustomFieldValueInput`: `definition_id: int`, `value: object`,
`effective_date: date | None`.

`UpdateCustomFieldValuesInput`:

- `entity_type: CustomFieldWriteEntityType` — a `Literal["people", "organizations",
  "opportunities"]` owned by the command (see AGENT_README "Small owned types stay on the
  query"). This is the wire `resource.resourceType` verbatim.
- `entity_id: NonEmptyStr`.
- `values: tuple[UpdateCustomFieldValueInput, ...]`, `min_length=1`, `max_length=15`.

**Fields are identified by `definition_id` only — never by name.** Two definitions can share
a name, and on this tenant an opportunity has a custom field literally called **"Probability"**
(`8648265`, a `PERCENT`) that is *not* the native `probability` attribute. Name matching would
write the wrong one. Say that in the field description.

Party identity resolution is **not** used here — this tool takes an id, because the entity may
be an opportunity, which the party resolver does not resolve. Callers get ids from
`get_person` / `get_organization` / `get_opportunities`. Say so in the description.

### Command behaviour

1. Load the catalog through the injected `CustomFieldsService`.
2. Unknown `definition_id` → validation failure, no write.
3. **Branch on the definition's `is_time_series`, not on the caller's input:**
   - `is_time_series=True` and no `effective_date` → failure naming the definition id.
   - `is_time_series=False` **with** an `effective_date` → failure. Backstop rejects this
     per-record (`RegularCustomField(...) does not need effectiveDate`).
4. **Picklist validation.** When the definition has `select_options`, validate against them.
   Add a public method to `CustomFieldsService` — e.g.
   `is_outside_current_options(value, select_options)` — wrapping the existing private
   `_not_in_current_options` / `_current_option_texts`, and call it from the command so read
   and write agree. **Do not copy the matcher.** On failure list the allowed values; Backstop's
   own message does the same, and ours should match it.
5. Enforce the definition's `required` and `maxLength` locally.
6. POST, then read `bulkLoadSummary` exactly as in slice 2.

### Tests — `tests/features/custom_fields/test_update_custom_field_values_command.py`

- `test_unknown_definition_id_is_rejected_without_writing`
- `test_time_series_field_requires_an_effective_date`
- `test_regular_field_rejects_an_effective_date`
- `test_invalid_picklist_value_lists_allowed_options_and_does_not_write`
- `test_opportunity_entity_type_is_sent_as_the_resource_type`
- `test_partial_bulk_failure_is_reported_per_record`
- `test_total_failure_on_201_is_not_reported_as_success`

---

## Slice 4 — `update_person` and `update_organization`

New feature package `src/backstop_mcp/features/org_people_writes/`. Two tools, two commands
(`UpdatePersonCommand`, `UpdateOrganizationCommand`), one shared
`commands/_json_api_utils.py`.

Party identity uses the existing resolver exactly as `get_person` does: `search`, `party_id`,
`search_type`, plus `require_exactly_one_party_selector` and `blank_to_none` from
`features.party_resolver`. Do not invent a second identity shape.

### `update_person` — every updatable field

**Attributes:** `first_name`, `middle_name`, `last_name`, `nick_name`, `prefix`, `suffix`,
`salutation`, `pronunciation`, `gender`, `birthday`, `spouse_name`, `job_title`, `department`,
`company_name`, `contact_description`, `email`, `email2`, `email3`, `mobile_phone`, `website`,
`other_id`, `investable_assets`, `is_employee`.

**Relationships:** `company_id` (`organizations`), `contact_source_id` (`contact-sources`),
`referral_source_id` (`contacts`), `owner_login` (resolved via `SystemUsersService`;
Backstop's `representative`),
`add_category_ids` / `replace_category_ids` (`contact-categories`, to-many — same append
trap and same two-field treatment as slice 1's `add_users_to_notify` /
`replace_users_to_notify`).

### `update_organization` — every updatable field

**Attributes:** `name`, `legal_name`, `aliases`, `contact_description`, `date_founded`,
`email`, `email2`, `email3`, `website`, `other_id`, `investable_assets`,
`number_of_employees`, `internal_organization`, `ria`, `matching_domains` (a list of strings).

**Relationships:** `contact_source_id`, `referral_source_id`, `owner_login`,
`primary_contact_id` (`people`), `add_category_ids` / `replace_category_ids`.

### Excluded from both, with reasons

| Excluded | Reason |
| --- | --- |
| `name`, `legalName` **on people** | Derived from the name parts. Writing `first_name` / `last_name` is how you change them. |
| `categoriesAsString` | A denormalized mirror of the `categories` relationship. Write the relationship. |
| `groupEntities` | A nested list of relationship records with their own ids and dates — a separate feature, not a field on this tool. |
| `regularCustomFieldValues` | Goes through `update_custom_field_values`. |
| `permissionBucket`, `contactTemplate`, `syncDisabled`, `hasRecommendationViewed` | Permissions, templating and system sync flags. Out of scope. |

### Rules

- **Send only the changed attributes.** PATCH is merge.
- **A required attribute cannot be nulled** — `"lastName": null` is
  `400 "Field lastName is required"`. Treat clearing `last_name` (person) or `name`
  (organization) as a validation error in the input model rather than letting Backstop answer.
- **Enforce `maxLength` locally with `max_length=` on the input:** `email*` ≤ 255,
  `jobTitle` ≤ 140, organization `name` ≤ 50. Backstop **silently stores over-length values**
  on these two endpoints — local validation is the only protection.
- **Report the value read back, not the requested one.** Backstop normalizes phone numbers
  (`+1 555 0100` is stored as `555-0100`). Re-read after the write.
- **Do not touch `contact-emails`.** Read-only; no write endpoint exists. Email corrections go
  through `email` / `email2` / `email3`.

### Locations, on these same two tools

The ticket's separate `update_contact_location` tool is **not** built. Locations are edited
through the contact, via an optional block on each tool:

- `location: ContactLocationInput | None` — omit `location_id` to create, pass it to patch
- `delete_location_id: str | None`

`location_id` comes from `get_person` / `get_organization` with
**`include=contactLocations`** — **not** `include=locations`, which is a hard
`400 "The system does not support includes for locations"`. Fix that in the field description.

`ContactLocationInput` fields: `location_id` (omit to create), `location_title` (**required on create**, `max_length=30`), `address`,
`city`, `state`, `country`, `postal_code`, `phone_number`, `secondary_phone_number`, `fax`,
`note`, `is_primary_location`.

Create payload:

```json
{"data": {"type": "contact-locations",
  "attributes": {"locationTitle": "Office", "address": "...", "city": "..."},
  "relationships": {"contact": {"data": {"type": "contacts", "id": "<party id>"}}}}}
```

- `contact.type` is **`contacts`**, unconditionally. Both `contacts` and `people` are
  accepted, but `contacts` is the one value that works for a person *or* an organization; a
  mismatched concrete type is a `404`.
- **`locationTitle` must be unique per party** —
  `400 "Location Names for a party must be unique."` Catch it and return a clear collision
  message rather than the raw Backstop error. Applies to a create *and* to a rename.
- `locationTitle` ≤ 30 **is** enforced server-side here, but keep `max_length=30` on the input
  so the rejection is local.
- Never send the derived read-only attributes: `cityResolvedName`, `countryCode`,
  `countryResolvedName`, `stateResolvedName`, `primaryLocation`.
- Delete is `client.delete(path)` with **no `schema=`** — a `204` with an empty body.
- A delete can fail `404 PartyNotFoundException "Party with id ... was not found."` when the
  parent party is gone (locations are orphaned, not cascaded). **Do not report that as
  "location not found"** — it names a party the caller never mentioned. Translate it.

**Annotation note for the reviewer:** folding an additive location create into a tool whose
`destructive_hint` is already `True` over-warns rather than under-warns, which is the safe
direction, and it is why `AGENT_README`'s "split when the annotations cannot tell the truth"
rule is satisfied here. Say this in the tool docstring so the next reader does not re-litigate
it.

### Tests — `tests/features/org_people_writes/`

- `test_only_the_changed_attribute_is_sent`
- `test_over_length_job_title_is_rejected_by_the_input_model`
- `test_clearing_a_required_attribute_is_rejected_by_the_input_model`
- `test_reported_value_comes_from_the_reread_not_the_request` — respx returns a normalized
  phone on the re-read.
- `test_add_categories_appends_and_replace_categories_clears_first`
- `test_location_create_links_the_contact_as_type_contacts`
- `test_duplicate_location_title_is_reported_as_a_collision`
- `test_location_delete_sends_no_body_and_no_schema`
- `test_party_not_found_on_location_delete_is_translated`

---

## Slice 5 — `end_employment`

Same `org_people_writes` package. `PATCH /entity-relationships/{id}` with `endDate` only.

### Input

Person identity + organization identity (both through the resolver) + `end_date: date`.
**No relationship id parameter** — the read path (`EmploymentLinkResponse`) does not expose
one, so the command finds it.

### Command behaviour

1. Resolve both parties.
2. `GET /people/{person_id}/entityRelationships` (paginate) and find the record whose
   `destinationEntity.resourceId` is the organization and whose type is employment. No match →
   a clear error naming both parties. More than one open match → report them rather than
   guessing which to end.
3. **One PATCH is enough.** Employment is stored as two directional rows, but end-dating
   either propagates to the reverse — measured. Do **not** find and patch the second row; the
   ticket's "PATCH endDate on both" is wrong for this instance.
4. Re-read and confirm.

### Payload

```json
{"data": {"type": "entity-relationships", "id": "<id>",
          "attributes": {"endDate": "2026-09-14"}}}
```

`endDate` only. **Never** send `entityRelationshipType` — `400 "Relationship type can not be
modified"`. Do not delete and recreate the relationship, and do not delete the person. The
tenant has a separate `is a former employee of` type; it is *not* reachable by patching the
type, and end-dating is the only route.

### The off-by-one-day trap

`features/data_hygiene/employment_index_factory.py` downgrades a current relationship to a
departure only when:

```python
elif ended is not None and ended < today:
```

**Strictly before today.** So an `end_date` of today writes fine and our own read path still
reports the person as a **current** contact until tomorrow. Product confirmed we write it
anyway, so:

1. When `end_date` is not strictly before today, add a `warnings` entry saying the date is
   recorded but the person still reads as a current contact until it passes. Same sentence in
   the tool docstring. Do not report a bare success.
2. The round-trip test uses a **past** date.

### Tests

- `test_one_patch_end_dates_the_relationship`
- `test_payload_contains_only_end_date`
- `test_relationship_type_is_never_sent`
- `test_missing_employment_pair_is_reported`
- `test_ambiguous_employment_pair_is_reported_rather_than_guessed`
- `test_end_date_of_today_warns_that_it_is_not_yet_former`
- `test_after_end_employment_the_read_path_reports_the_link_as_former` — the ticket's
  round-trip requirement. Call the command, then run the person read over the same respx
  fixtures and assert the resulting `EmploymentLinkResponse` has `status == "former"` and
  `signal == "end_date_passed"`. `EmploymentLinkResponse` is exported from
  `features.data_hygiene` (**not** `org_people`), and there is no field literally named
  `end_date_passed` — that string is the `DepartureSignal.END_DATE` value on `signal`.

---

## Per-slice completion checklist

1. Model layers added (`api_responses` → `internal_dto` only if there are real `*Dto`s →
   `responses`), every published field with a `Field(description=...)`.
2. Command(s) under `commands/`, one logical write each.
3. Tool under `tools/`, one `@tool` per file, filename equals function name.
4. `ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=False)` on
   every tool in this ticket. All of them are destructive.
5. Factories in `dependencies.py`, `@lru_cache(maxsize=1)`, depending only on other cached
   factories or `get_backstop_client_for_current_caller`. Read `BackstopConfig` in the body.
6. Exports added to the feature `__init__.py` `__all__`.
7. Tool added to `TOOLS` in `server/tools/registry.py`.
8. Factory added to `PROVIDERS` in `teardown.py`.
9. Spans and logs on the tool entry and each command `run` — dotted event names, structured
   `extra`, a login only as `IdentifiableValue`, never a raw Backstop body.
10. Tests as listed, asserting on recorded wire bodies and published output.

Then run:

```
uv run pytest tests/features/<name> tests/test_layering.py tests/test_teardown.py \
  tests/server/tools/test_output_descriptions.py tests/server/tools/test_input_descriptions.py
uv run ruff format <touched> && uv run ruff check <touched> && uv run basedpyright <touched>
```

If `basedpyright` reports thousands of errors, the worktree has no synced `.venv` — see the
git-worktree trap in `DEVELOP.md` before believing it.

---

## Traps that already cost a round of rework

Each was measured. A payload contradicting one of these will pass a mocked test and fail
against Backstop.

1. **`POST /bulk-opportunity-stage-history` does not move a stage.** It writes history and
   rewrites `previousStage`. Only `PATCH /opportunities/{id}` moves a deal.
2. **A bulk endpoint returns `201` even when nothing was written.** Read `bulkLoadSummary`.
3. **A to-many relationship PATCH appends, it does not replace.** `data: []` clears
   everything; single-member removal is not expressible.
4. **`stageEffectiveDate` in the past silently cancels the stage move** and reads back as
   `null`. Guard it and re-read.
5. **`maxLength` is enforced inconsistently.** `locationTitle` gets a clean `400`;
   `jobTitle` and organization `name` silently store over-length data.
6. **Phone numbers are rewritten server-side.** Report the re-read value.
7. **Identity pointers are relationships** (`stage`, `contact`, `product`). Resource pointers
   on the two bulk endpoints are `{resourceId, resourceType}` attributes with the **plural**
   resource name — never Bean casing. The two shapes are not interchangeable.
8. **`contact-emails` has no write endpoint.**
9. **`entityRelationshipType` is not patchable.**
10. **`include=locations` is a 400.** It is `contactLocations`.
11. **`/custom-field-definitions` ignores `page[limit]` and most filters.** Only
    `filter[entityType]` works. `CustomFieldsService` already owns the catalog.
12. **An employment `endDate` of today still reads as `current`** (`ended < today`).
13. **A custom field can share a name with a native attribute** — an opportunity has a
    `PERCENT` custom field called "Probability" alongside the native `probability`. Always
    address custom fields by `definition_id`.

---

## Existing helpers — reuse, do not reinvent

| Need | Import from |
| --- | --- |
| `NonEmptyStr`, `OmitNoneModel`, `published_output_schema`, `CoercedId` | `backstop_mcp.models` |
| Lenient wire scalars | `backstop_mcp.lenient` |
| `LenientDate`, `LenientDatetime` | `backstop_mcp.dates` |
| Single-resource POST/PATCH response document | `backstop_mcp.backstop_client.BackstopApiSingleResourceDocument` |
| `SearchType` (plural party resource string) | `backstop_mcp.features.entity_types` |
| Party identity helpers and shared field descriptions | `backstop_mcp.features.party_resolver` |
| `OpportunityStagesService`, `OpportunityStageResponse`, `OpportunityResourceAttributes` | `backstop_mcp.features.opportunities` |
| `CustomFieldsService`, `CustomFieldDefinitionDto` | `backstop_mcp.features.custom_fields` |
| `SystemUsersService` (login → id) | `backstop_mcp.features.system_users` |
| `EmploymentLinkResponse`, `EmploymentIndex`, `DepartureSignal` | `backstop_mcp.features.data_hygiene` |
| Hashed logging of a login | `backstop_mcp.utils.IdentifiableValue` |
| Test helpers | `tests/helpers.py` — `BASE_URL`, `client_factory`, `credential`, `recorded_json_bodies`, `recorded_params`, `resource`, `collection`, `system_users_service`, `custom_fields_service` |

`activity_writes/commands/_json_api_utils.py` is **private to that feature** — copy the two or
three helpers you need (`omit_none_values`, `json_api_update`, `relationship_data`) into the
new feature's own `commands/_json_api_utils.py` rather than importing across features.

## Out of scope

Activity logging (UN-23684, shipped), account transactions, creating or editing custom-field
definitions, changing relationship types, `groupEntities`, permission buckets, and any
hardcoded tenant-specific field id or option label. "Status", "Grade" and "Investor Status"
are one client's labels; every custom field is addressed by `definition_id`.
