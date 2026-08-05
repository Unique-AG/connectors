# Design: employment index

**Ticket:** UN-22647

## Problem

`detect_departed_employment` answers "is this person departed, period." It buckets relationships
by organization internally, then collapses to a single verdict via `_strongest_departure`,
discarding every other organization the person is linked to. Employment is only meaningful as a
`(person, organization)` pair, so that collapse is the defect: a person who is current at org A
and departed from org B can be reported as departed with org B's id attached, and no caller can
ask "is this person still at org A?"

Its only call site (`server/tools/get_person.py`) passes the person's entire side-loaded
relationship set and uses the result as a boolean plus an informational echo — it never compares
the returned `organization_id` against anything, because `get_person` has no organization to
compare against. Any future org-contact listing tool would need the question the current API
cannot express.

Two further problems the payloads expose:

- The organization GET returns **mirror** relationship types (`is employee of (mirror)` id
  456441, `is a former employee of (mirror)` id 459797) — different ids and names from the
  person-side types, and pointing the other direction. Nothing today reads that shape.
- A `CURRENT`-typed relationship can carry an elapsed `endDate` (rel 78305487, type 456441,
  `endDate: 2022-12-31`), and a person can hold **both** a current and a former relationship to
  the same organization (person 341833933 → org 341208613). Resolving that needs a dated rule,
  not "any current edge clears all departures."

## Solution

### Overview

Replace the single collapsed verdict with an **index of employment edges** keyed by
`(person_id, organization_id)`. One class, one resolution rule, two thin readers — one for each
payload shape.

Every relationship that links a person to an organization normalises to an employment edge:

```
person_id, organization_id, organization_type, status, effective_date, evidence
```

`status` comes from the existing `classify_employment` (`CURRENT` / `FORMER`; `IRRELEVANT` edges
are dropped). `effective_date` is the edge's comparable date. `evidence` is the existing
`DepartedEmployment` payload, so tool responses keep their shape.

Per pair, the winning edge is the one with the greatest `effective_date`. Ties break toward
**departed**: a same-day former record is the more recent human action, and under-reporting a
departure is the costlier error for a "who do we contact" answer.

### Effective date

Business date when present, creation timestamp as the fallback. `modifiedTimestamp` is never
used — it moves whenever anyone touches the record and would silently reorder history.

| Edge | Effective date |
|---|---|
| `CURRENT` type | `startDate`, else `createdTimestamp` |
| `FORMER` type | `endDate`, else `createdTimestamp` |
| `CURRENT` type with an **elapsed** `endDate` | rewritten to a departure dated at `endDate`, signal `END_DATE` |

An edge with no usable date at all is still indexed but sorts last, so it wins only when it is
the sole edge for its pair.

### Direction

Reading the person payload, the person is `sourceEntity` and the organization is
`destinationEntity`. Reading the organization payload it is reversed. A `person_side` parameter
on the edge extractor is the only difference between the two builders; everything downstream is
shared.

### Naming convention

Three spellings exist today (`departed.py`, `DepartureRules`, `BACKSTOP_EMPLOYMENT_*`). The rule
going forward:

> **"Employment" names the domain. "Departure/departed" names only the finding.**

| Now | After |
|---|---|
| `departed.py` | deleted — contents absorbed into `employment.py` |
| `DepartureRules` | `EmploymentRules` |
| `DepartedContactDetector` | `EmploymentIndexFactory` |
| `create_departed_contact_detector` | `create_employment_index_factory` |
| `runtime.get_departed_contact_detector` | `runtime.get_employment_index_factory` |
| `EmploymentStatus` | unchanged |
| `DepartedEmployment`, `DepartureSignal`, `DepartedContactEcho` | unchanged — these *are* the finding |
| `BACKSTOP_EMPLOYMENT_*`, `BACKSTOP_FORMER_EMPLOYMENT_*` | unchanged — renaming breaks deployments |

`EmploymentIndexFactory` rather than `...Builder` because it is a configured, long-lived object
built once in `create_app()`, not a per-call helper.

### Architecture

All within `features/data_hygiene/`.

**`types.py`**

- `EntityRelationshipAttributes` gains `start_date` (`startDate`) and `created_timestamp`
  (`createdTimestamp`). Both already ride along on every relationship in the payload.
- `EmploymentEdge` (frozen dataclass) — one normalised relationship.
- `EmploymentRecord` (frozen dataclass) — the resolved per-pair answer: `status` plus
  `departure: DepartedEmployment | None`.
- `DepartureRules` → `EmploymentRules`.

**`employment.py`** (new, replaces `departed.py`)

- `classify_employment`, `_parse_date`, `_side_type`, `_is_organization` — moved verbatim from
  `departed.py`, now shared by both directions.
- `_employment_edges(*, relationships, relationship_types, rules, today, person_side)` — parses,
  filters to person↔organization pairs, classifies, drops `IRRELEVANT`, computes
  `effective_date`, rewrites elapsed-`endDate` current edges.
- `EmploymentIndex` — folds edges to one winner per pair. Query surface:
  - `status(*, person_id, organization_id) -> EmploymentStatus`
  - `departure(*, person_id, organization_id) -> DepartedEmployment | None`
  - `pairs(*, status) -> tuple[EmploymentRecord, ...]` for list annotation
  - An unknown pair returns `IRRELEVANT` — "no employment evidence" — never a false `CURRENT`.
- `build_person_employment_index(...)` and `build_organization_employment_index(...)` — thin
  wrappers differing only in `person_side`.

**`service.py`**

`EmploymentIndexFactory` keeps owning the vocabulary and the clock, so the index needs no client,
cache or lock. Methods become `index_for_person(document)` and `index_for_organization(document)`.

**`server/tools/get_person.py`**

Builds the person index. `departed: bool` stays as "any departure"; `departed_detail` becomes
`departures: list[DepartedContactEcho]`, each entry already carrying its own `organization_id`.

### Error handling

The index is built from a payload we do not control, so every malformed part is dropped rather
than raised. No exception crosses the index boundary.

- A relationship that fails `BackstopApiResource` validation is skipped.
- A relationship-type resource that fails validation or has no name is dropped from the id→name
  map; its relationships then classify with `type_name=None`, which `classify_employment`
  already reads as `CURRENT` — never as an invented departure.
- A person or organization side with no `resourceId` is skipped: every such side would otherwise
  collide into one bucket, letting a relationship to one unnamed company clear a departure from
  a different one.
- An unparseable `endDate` / `startDate` / `createdTimestamp` falls through to the next
  fallback; an edge with no usable date sorts last.
- Builders stay keyword-only: `relationships` and `relationship_types` are the same type and a
  silent transposition would report every person as current.

### Testing strategy

Behavioural, against the real payload shapes, in the existing `pytest` setup under
`services/backstop-mcp/tests/`.

1. **Same-org conflict, person side** — person 341833933: `is employee of` created 2022 plus
   `is a former employee of` created 2021 → `CURRENT`.
2. **Same-org conflict, reversed dates** → `DEPARTED`, `signal=FORMER_TYPE`.
3. **Elapsed `endDate` on a current type** — rel 78305487 → `DEPARTED`, `signal=END_DATE`,
   `end_date="2022-12-31"`.
4. **Future `endDate`** → `CURRENT`.
5. **`startDate` beats `createdTimestamp`** — a current edge whose `startDate` predates its own
   `createdTimestamp` loses to a former edge dated between the two.
6. **Multi-org** — departed from A, current at B: both queryable, neither collapses.
7. **Organization-side index** — mirror types 456441 / 459797 classify identically to their
   person-side counterparts; `owns account` and `management company of` edges drop as
   `IRRELEVANT`.
8. **Both builders agree** — the same logical pair fed from either payload shape yields the same
   `EmploymentRecord`.
9. **Malformed input** — missing `resourceId`, unparseable dates, un-side-loaded type.

## Out of scope

- **Organization-side tools.** The organization builder ships because it is a few lines on top of
  the shared machinery, but no tool calls it yet. No "list current employees of org X."
- **Fetching the other side.** The index is built only from relationships side-loaded on the
  caller's own GET. No second request, no merging of two indexes.
- **Caching.** The factory stays stateless and synchronous.
- **Future `startDate`.** A not-yet-started employment counts as current; suppressing pipeline
  hires would hide real contacts.
- **`isEmployee` / `companyName` on the person record.** Denormalised, unversioned; the
  relationship graph is the source of truth.
- **Config renames.** `BACKSTOP_EMPLOYMENT_*` env vars keep their names.

## Tasks

1. **Extend the relationship attribute model** — add `start_date` and `created_timestamp` to
   `EntityRelationshipAttributes`. Add `EmploymentEdge` and `EmploymentRecord`. Rename
   `DepartureRules` to `EmploymentRules`.
2. **Build `employment.py`** — move `classify_employment`, `_parse_date` and the side helpers out
   of `departed.py`, add edge extraction with the `person_side` parameter and the effective-date
   rules, and delete `departed.py`.
3. **Add `EmploymentIndex`** — fold edges to the max-dated winner per pair with ties breaking
   toward departed; expose `status`, `departure` and `pairs`.
4. **Add the two builders** — `build_person_employment_index` and
   `build_organization_employment_index`, differing only in which side holds the person.
5. **Rework the service** — `EmploymentIndexFactory` with `index_for_person` and
   `index_for_organization`; rename the factory function and the runtime accessor and update
   `create_app()`.
6. **Update `get_person`** — build the person index and replace `departed_detail` with
   `departures: list[DepartedContactEcho]`, keeping `departed: bool` as "any departure."
7. **Document the mirror types in `.env.example`** — id-based `FORMER` configuration needs the
   `(mirror)` type's id as well; the name markers already cover both.
8. **Write the behavioural tests** — the nine cases above.
