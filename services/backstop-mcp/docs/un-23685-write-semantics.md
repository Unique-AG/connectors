# UN-23685 write semantics, measured against a live instance

Everything below was measured on the **fb-rm-lg-26 sandbox**
(`https://fb-rm-lg-26.backstopsolutions.com/backstop/api`), not on Capstone production, and
not read off the swagger. Where a live response and the swagger disagree, this file records
the response.

Every record created for these probes was deleted, and the follow-up `GET` confirmed `404`.

The probe scripts live in `agent-explore/` and are re-runnable:

| Script | Covers |
| --- | --- |
| `step0_patch_semantics.sh` | attribute merge-vs-replace on `/opportunities` |
| `step0_patch_relationships.sh` | relationship merge-vs-replace, `/bulk-opportunity-stage-history` |
| `step0_bulk_vs_patch.sh` | A/B: does the bulk endpoint move a stage? |
| `step0_party_patch.sh` | `/people` and `/organizations`, to-many `categories`, maxLength |
| `probe_bulk_custom_fields.sh` | `/bulk-custom-field-values`, regular vs time-series |
| `probe_locations.sh` | `/contact-locations` |
| `probe_locations_employment.sh` | `/entity-relationships` employment + endDate |

---

## Step 0 verdict: PATCH is merge, not replace

**A single-field PATCH is safe.** Omitted fields are left alone, so no tool needs to resend
the fields it read, and `people.lastName` / `people.gender` / `organizations.name` do not
need to be echoed back on every write. The ticket's replace-semantics contingency is not
needed.

Verified on `/opportunities`, `/people`, `/organizations`, `/contact-locations` and
`/entity-relationships`:

- **Omitted attributes are preserved.** PATCHing only `description` on a fully-populated
  opportunity left `name`, both amounts, `probability`, `otherId`, `aliases`,
  `expectedInvestmentDate`, `currencyCode` and `isErisa` untouched.
- **Omitted relationships are preserved.** PATCHing only `relationships.product` left
  `stage` and `investor` intact; PATCHing one attribute left every relationship intact.
- **Explicit `null` clears an optional attribute.** `"otherId": null` removed the value.
- **Explicit `null` on a required attribute is rejected.**
  `"lastName": null` → `400 InvalidParameterException "Field lastName is required"`.

### The exception: a to-many PATCH appends

This is the one case where PATCH is neither merge-per-field nor replace:

```
categories before: [9615, 12467]
PATCH relationships.categories.data = [12469]
categories after:  [9615, 12467, 12469]
```

`data: []` clears the whole collection. There is no way to remove a single member in one
call — a "set the categories to exactly this list" operation is clear-then-add, i.e. two
writes with a window where the party has no categories. Any future category tool needs to
say so out loud.

### maxLength is enforced inconsistently — validate locally

| Field | Documented limit | Sent | Result |
| --- | --- | --- | --- |
| `people.jobTitle` | 140 | 200 chars | **stored all 200**, no error |
| `organizations.name` | 50 | 80 chars | **stored all 80**, no error |
| `contact-locations.locationTitle` | 30 | 50 chars | `400 "Maximum length of locationTitle is 30"` |

Two of the three silently accept over-length data. The ticket's "enforce maxLength locally"
is therefore mandatory, and the reason is silent acceptance rather than a clean rejection.

### Backstop rewrites some values it stores

Phone numbers are normalized server-side:

- `people.mobilePhone`: sent `+1 555 0100`, stored `555-0100`
- `contact-locations.phoneNumber`: sent `+41 44 000 0000`, stored `+41 44 000 00 00`

So a `confirm=true` response must report the value read back after the write, not the value
the caller asked for. Echoing the request as `new` is wrong for any phone field.

---

## Tool 1 — `update_opportunity` (`PATCH /opportunities/{id}`)

**A stage move is one call.** Setting `relationships.stage` makes Backstop derive the rest:
`previousStage`, `dateEnteredCurrentStage`, `daysInCurrentStage`, and a new `stageHistory`
row. Moving into a `closed: true` stage also sets `isOpen: false` and `closedDate`.
`weightedValue` / `weightedAllocatedValue` are computed from `probability` and the amounts
(0.42 × 1,000,000 → 420,000). None of these should ever be sent.

**`stageEffectiveDate` in the past silently cancels the move.** Sending
`stageEffectiveDate: 2026-06-01` alongside a move to Client Approval returned **200**, wrote
a history row dated 2026-06-01 — and left the deal in its previous stage with
`previousStage` unchanged. `stageEffectiveDate` also reads back as `null` on a subsequent
`GET`; it is a transient write input, not a stored attribute.

Consequence for the tool: either reject a past `stage_effective_date` in the pydantic input,
or re-read after the write and report the stage Backstop actually landed on. A preview that
promises the requested stage will be wrong on a 200.

**Stage-implied probability does not exist server-side.** Moving a deal to IDD
(stage `probability` 0.3) and then to Invested (1.0) left the opportunity's own `probability`
at `null` both times. Backstop never copies the stage's probability onto the deal. "Explicit
wins over stage-implied" describes a behaviour this API does not have — if the product wants
stage-implied probability, the connector has to write it.

**Stage scoping is a no-op on this tenant.** All 7 stages expose
`opportunityTypes = [entity-types 16 "Opportunity"]`, and every sampled opportunity has
`clientDefinedEntityType = 16`. `include=opportunityTypes` works and the DTO extension is
trivial, but every stage is valid for every opportunity here, so the "out-of-type name
fails" path has no test data on fb-rm-lg-26.

Incidentally, `relationships.stage` **is** accepted on `POST /opportunities` even though the
swagger's create example omits it.

---

## Tool 2 — `update_opportunity_stages`: the endpoint does not do this

`POST /bulk-opportunity-stage-history` is a **history-backfill** endpoint. It does not move
an opportunity's current stage.

A/B on two identical deals, both created in Prospect, both targeted at Invested:

| | `PATCH /opportunities/{id}` | `POST /bulk-opportunity-stage-history` |
| --- | --- | --- |
| current stage | Prospect → **Invested** | Prospect → **Prospect** (unchanged) |
| `previousStage` | → `"Prospect"` (correct) | → **`"Invested"`** (the target stage) |
| `isOpen` | → `false` | `true` (unchanged) |
| `closedDate` | → today | `null` (unchanged) |
| response | `200` | **`201`, `successCount: 1`** |

The bulk call did append a correct `stageHistory` row (history went from 1 row to 2), and it
reported success — while `relationships.stage` never changed. It also leaves `previousStage`
naming a stage the deal was never in. Backdating the row changes nothing either.

**Recommendation:** keep the tool name and parameters from the ticket, but implement it as a
fan-out of N × `PATCH /opportunities/{id}` (connector-side cap, per-record outcomes collected
from the individual responses). Built on the bulk endpoint, the tool would report "50 deals
moved" and move none. If a "record a historical stage change" capability is wanted later,
that is a separate tool and should be described as writing history.

### `bulkLoadSummary` (shared by both bulk endpoints)

```json
{"totalCount": 2, "successCount": 1,
 "errorMessages": [{"index": 1, "message": "Error load record #1, Resource opportunities not found by id 999999999"}]}
```

`index` is 0-based and the `#N` in the message matches it. **A partial failure — and a total
failure — still returns `201`.** HTTP status carries no information here; only
`bulkLoadSummary` does.

---

## Tool 3 — `update_custom_field_values` (`POST /bulk-custom-field-values`)

Payload is `attributes.records[]` plus `attributes.resource.{resourceId, resourceType}`.
Both `people` and `contacts` are accepted as `resourceType`.

Measured per-record behaviour (every one of these returned HTTP **201**):

| Case | `successCount` | Message |
| --- | --- | --- |
| regular field, valid value | 1 | — |
| regular field, same definition written again | 1 | overwrites in place, no duplicate row |
| regular picklist, invalid option | **0** | `Invalid value for NotARealOption, valid options are [Profund, Direct, Portal, No - Profund, No - Portal]` |
| time-series field, **no** `effectiveDate` | **0** | `TimeSeriesCustomField(8746199) need effectiveDate` |
| time-series field, with `effectiveDate` | 1 | — |
| regular field, **with** `effectiveDate` | **0** | `RegularCustomField(9910127) does not need effectiveDate` |
| unknown `definitionId` (+ one valid sibling) | 1 of 2 | `Resource custom-field-definitions not found by id 999999999`; sibling still written |

Two things this settles for the ticket:

- **Branching on the catalog's `is_time_series` is required, in both directions.** Sending
  `effectiveDate` to a regular field is a hard per-record failure, not an ignored extra — the
  mirror of the missing-date case. Neither can be guessed from the caller's input.
- Backstop *does* validate picklist options server-side and enumerates the valid ones. Local
  validation is still worth doing for a clean pre-write rejection, but it is not the only
  line of defence.

### Reading the catalog

`/custom-field-definitions` **ignores `page[limit]`** and ignores most filters: both
`filter[isTimeSeries][eq]=true` and `filter[fieldType][eq]=TEXT` returned the full 3,274
definitions. Only `filter[entityType]` is honoured (`OpportunityBean` → 13 rows). Plan any
catalog narrowing around `entityType` alone.

For reference, the definitions used above: `9910127` regular `DROPDOWN`, `9823191` regular
`SMALL_TEXT`, `8746199` time-series `DROPDOWN`. Only 14 of the 3,274 definitions are
time-series.

---

## Tool 4 — `update_person` / `update_organization`

Covered by Step 0. `email` / `email2` / `email3`, `mobilePhone`, `jobTitle`, `department` on
people and `email` / `website` / `legalName` on organizations are all individually
PATCH-able, and omitted fields survive. Required fields cannot be nulled (400). Remember the
phone normalization above, and that `people.name` and `people.legalName` are derived from the
name parts.

---

## Tool 5 — `update_contact_location`

- **`contact` accepts both `contacts` and `people`** (both `201`). Passing `organizations`
  with a person id is `404 "Resource organizations not found by id ..."`, so the type is
  resolved against the id. `contacts` is the one value that works for either party type,
  which is the real reason to prefer it — not that `people` is rejected.
- **`locationTitle` must be unique per party:**
  `400 InvalidParameterException "Location Names for a party must be unique."` This is not in
  the ticket. Both create and a title-changing update have to handle the collision.
- `locationTitle` maxLength 30 **is** enforced server-side (400).
- PATCH merges: changing `address` left `city`, `country`, `phoneNumber`, `postalCode` and
  `locationTitle` intact.
- `DELETE` returns `204` with an empty body; the follow-up `GET` is `404`.
- **The relationship is `contactLocations`, not `locations`.** `include=locations` is
  `400 "The system does not support includes for locations"`. The ticket's
  "from `get_person` / `get_organization` `include=locations`" needs correcting.
- Read-only derived attributes to leave alone: `cityResolvedName`, `countryCode`,
  `countryResolvedName`, `stateResolvedName`, and `primaryLocation` (which mirrors
  `isPrimaryLocation`).
- **Deleting a party does not cascade to its locations, and the orphan cannot be deleted.**
  After `DELETE /people/{id}`, the party's locations still return `200` on
  `GET /contact-locations/{id}` with their attributes intact, but
  `DELETE /contact-locations/{id}` then fails with
  `404 PartyNotFoundException "Party with id ... was not found."` — the delete handler
  resolves the parent party first. Two such rows (`144016587`, `144016589`) are stranded on
  the sandbox from these probes and cannot be removed through the API.

  For the tool this means `delete=true` can fail with a `PartyNotFoundException` that names a
  party the caller never mentioned, and that error must not be reported as "location not
  found". For any future probe: delete child locations *before* the party.

---

## Tool 6 — `end_employment` (`PATCH /entity-relationships/{id}`)

**Employment is two records, but one PATCH end-dates both.** A single
`POST /entity-relationships` (`is employee of`, type `456439`) created two rows:

```
127921399  source=person  destination=org
127921401  source=org     destination=person
```

Each party's `entityRelationships` collection shows only its own direction
(`totalResourceCount: 1` on each side). PATCHing `endDate` on `127921399` alone left **both**
rows with `endDate: 2026-09-14`.

So the ticket's "PATCH `endDate` on both — end-dating one side leaves the reverse edge open"
is not what this instance does. One PATCH is enough, which is convenient because the read
path (`EmploymentLinkResponse`) does not expose the reverse record's id anyway. The tool
should still re-read to confirm, rather than assuming propagation.

Confirmed as the ticket states: `entityRelationshipType` cannot be changed —
`400 InvalidParameterException "Relationship type can not be modified"`, and the type stayed
`456439`. Note the tenant has a distinct `is a former employee of` type (`459795`), which is
*not* reachable by patching the type; end-dating is the only route.

---

## Probing caveats for whoever picks this up

- **Some endpoints reject unknown query params.** `/opportunities/{id}/stageHistory` and
  `/people/{id}` answer `400 InvalidParameterException "Invalid filter field bust"`. Since
  `agent-explore/explore.py` caches by path + query, you cannot cache-bust a repeated read
  with a dummy param on those paths; the scripts here delete their own cache entry after
  each read instead. This contradicts the general "Backstop silently ignores unrecognized
  params" assumption — which *is* true of `/custom-field-definitions`, but not universal.
- `explore.py` stays GET-only. Writes go through `agent-explore/write_probe.py`.

## Not yet measured

- `people.gender` null-rejection (only `lastName` was tested).
- `/resource-metadata/` as the source of required / maxLength / readOnly flags.
- Value encoding for `MULTI_SELECT` (1 definition on the tenant) and `ENTITY` field types.
- Whether a time-series write at an existing `effectiveDate` overwrites or duplicates.
- The ticket's "verified absent" list (`contact-emails` writes, `custom-field-definitions`
  writes) was taken on trust and not re-probed.
