# Design: backstop-mcp model layers

## Problem

Every feature package in `services/backstop-mcp/src/backstop_mcp/features/` uses `types.py` as a
catch-all. `features/accounts/types.py` (297 lines) holds three distinct kinds of model at once:

* Backstop wire shapes — `AccountAttributes`, `OwnerAttributes`, `SeriesPointAttributes`:
  camelCase aliases, `extra="ignore"`, parsed off a JSON:API `attributes` object.
* Internal computation models — `AccountRecord`, `SeriesFigure`, `ProductPositions`: frozen,
  snake_case, no field descriptions.
* …and it feeds a separate `responses.py` holding the MCP-facing models.

Three layers, one filename, and nothing at a call site says which one you are holding. The
`Attributes` suffix is applied inconsistently and sometimes backwards: `server/tools/get_person.py`
`PersonAttributes` and `get_organization.py` `OrganizationAttributes` are *outward* models wearing
the wire suffix.

Construction is scattered across ~25 module-level factory functions that sit beside the classes
they build but are not attached to them. One of them, `data_hygiene/responses.py` `as_of_response`,
is a pure identity function. Two of them project by untyped dict round-trip
(`Model.model_validate({**dto.model_dump(), ...})`), which can raise.

Finally, "pydantic across the board" is unevenly applied: 20 `@dataclass` types and 2 `TypedDict`s
remain, most of them plain data carriers with no reason to differ.

## Solution

### Overview

Each feature package gets up to three modules, and the suffix on a class names the boundary it
touches:

| Module | Suffix | Role |
| --- | --- | --- |
| `api_responses.py` | `*Attributes` | parsed off a Backstop JSON:API `attributes` object — camelCase aliases, `extra="ignore"` |
| `internal_dto.py` | `*Dto` | computed and passed around inside the service; never published |
| `responses.py` | `*Response` | published to MCP clients — `OmitNoneModel`, every field described |

Dependency runs one way: `responses.py` → `internal_dto.py` → `api_responses.py`. A model that
starts internal and later gets published moves to `responses.py` and takes the `Response` suffix.

Enums and `type` aliases carry no suffix and sit with the layer that owns them — `EmploymentStatus`,
`DepartureSignal`, `SeriesName`, `ProductResolution` in `internal_dto.py`, which `responses.py` may
import downward.

Any of the three files may become a directory when it gets unwieldy. ~300 lines is the guideline,
not a gate. On current sizes only `accounts/responses.py` (~590) is a clear candidate.

Construction moves onto the class as `from_<source>` classmethods — matching the three that already
exist in the tree (`ResolvedProduct.from_attributes`, `BackstopClientFactory.for_credential`,
`TypeVocabulary.for_employment`). The free factory functions go away.

### Architecture

#### Per-package moves

| Package | `api_responses.py` | `internal_dto.py` | `responses.py` |
| --- | --- | --- | --- |
| `accounts` | `ProductAttributes`, `ProductConfigurationAttributes`, `AccountAttributes`, `OwnerAttributes`, `InvestorTypeAttributes`, `InvestorQualificationAttributes`, `SeriesPointAttributes` | `ResolvedProductDto`, `AccountOwnerDto`, `InvestorTypeDto`, `AccountRecordDto`, `AccountListingDto`, `SeriesPointDto`, `SeriesFigureDto`, `SeriesErrorDto`, `AccountPositionDto`, `AumReconciliationDto`, `ProductPositionsDto` | existing 13, split into a `responses/` package |
| `party_resolver` | `PartyAttributes` | `ResolvedPartyDto`, `PartyResolveItemDto`, `QuickSearchOptionsDto` | existing 2, unchanged |
| `data_hygiene` | `EntityRefAttributes`, `EntityRelationshipAttributes`, `RelationshipTypeAttributes`, `ProvenanceAttributes` ← `ProvenanceFields` | `DepartedEmploymentDto`, `TypeVocabularyDto`, `EmploymentEdgeDto`, `EmploymentRecordDto`, `EmploymentRulesDto`, `EntityRelationshipsDto` ← TypedDict | `AsOfResponse` ← `AsOf`, plus existing 2 |
| `activity_history` | `ActivityAttributes`, `EmailAttributes`, `SpecificResourceAttributes`, `ActivityDetailAttributes`, `MeetingSpecificAttributes`, `AttendeeAttributes` — all currently private in `fetch_*.py` | `ActivityItemDto`, `EmailItemDto`, `ActivityPageDto`, `EmailPageDto`, `ActivityDetailDto`, `MeetingSpecificsDto`, `AttendeeDto`, `DateRangeDto`, `ActivityHandleDto` | existing 4, plus `activity_detail_responses.py` folded in, plus `ActivityContinuationResponse` and `ActivityGroupResponse` |
| `opportunities` | `OpportunityStageAttributes` | `OpportunityStageDto` | existing 2, plus `OpportunityFetchResponse` ← `OpportunityFetchResult` |
| `org_people` | — | `PersonAtOrganizationDto`, `OrgPeopleListingDto` | existing 2, unchanged |
| `custom_fields` | `CustomFieldDefinitionAttributes` | `CustomFieldDefinitionDto` | — |
| `includes` | *exempt — see below* | — | projection models unchanged |

In `server/tools/`: `PersonAttributes` → `PersonRecordResponse`, `OrganizationAttributes` →
`OrganizationRecordResponse`, `get_activity_history_utils.py` `PartyAttributes` →
`PartyRecordResponse`. All three are outward models; `*RecordResponse` matches `EmailRecordResponse`
and `AccountRowResponse` already in the tree.

`features/resolution.py` and `models.py` are cross-cutting rather than per-feature and keep their
filenames. `resolution.py` already holds its internal generics (`Candidate`, `Resolved`,
`Ambiguous`) alongside its `*Response` generics in one file; the suffixes already tell them apart.

#### The `includes/` exception

`features/includes/` stays a single layer, deliberately. Its models carry *both* camelCase aliases
(9) and FastMCP descriptions (38) under a shared `_PROJECTION_CONFIG`, because
`IncludePlan.project()` validates raw Backstop side-loads straight onto `into: type[ResponseT]` —
the response class *is* the wire shape. Splitting it would mean authoring a parallel `*Attributes`
set plus a `from_attributes` for each, doubling the code so the generic projection can throw the
intermediate away.

#### Construction: `from_<source>` classmethods

Every factory becomes a classmethod on the model it builds, named for what it consumes:
`AccountRowResponse.from_record(dto)`, `ResolvedProductDto.from_attributes(id, attributes)`,
`RetryPolicy.from_settings(settings)`. Three shapes need a stated convention:

* **Nullable projections.** `owner_response`, `figure_response`, `investor_type_response` and
  `investor_qualification_response` return `None` for a `None` input — and
  `investor_qualification_response` also returns `None` when every field is blank. These become
  classmethods returning `Self | None`, keeping the omit-when-blank rule next to the model that
  defines what blank means rather than scattering it across callers.
* **Union returns.** `unresolved_product_response` returns
  `ProductAmbiguousResponse | NotFoundResponse`. It lands on the *ambiguous* class —
  `ProductAmbiguousResponse.from_unresolved(result)` — with `NotFound` as the degenerate arm.
* **Generic plumbing.** `resolution.py`'s `unresolved_response(result, ambiguous_model=...,
  to_candidate=<callable>)` keeps its free functions, since no single class owns them. Call sites
  pass a bound classmethod where they passed a function: `to_candidate=ProductCandidateResponse.from_candidate`.

Scope is the whole service, `backstop_client/` included: `BackstopApiError.from_response(response)`
replaces `parse_json_api_error` (a classmethod on the base that may return a
`BackstopRateLimitError` is a legitimate polymorphic factory), and `RetryPolicy.from_settings`
replaces `build_retry_policy`.

#### Validation policy

Three rules, stated because they are currently only de facto — the tree has 35 `extra="ignore"`,
5 `extra="allow"`, and zero `extra="forbid"`, but nothing says so.

1. **`extra="forbid"` is banned.** `*Attributes` default to `ignore`. `allow` only where passthrough
   is the point — `PersonRecordResponse` and `OrganizationRecordResponse` deliberately relay tenant
   custom fields.
2. **Permissive about what a model doesn't need; strict about what makes a record a record.**
   Unknown props are ignored, absent optional fields default to `None`, malformed scalars coerce to
   `None` via lenient annotations like `LenientDate`. But a field whose absence makes the record
   invalid or unsafe to use stays required, with the reason in a comment beside it — today
   `ActivityItem.id`, `ActivityItem.stream`, `ActivityPage.end_of_stream`, and
   `ContactEmailResponse.retired` (documented at `includes/responses.py`: an address whose retired
   status is unknown is worse than one that is absent). Such a record fails validation rather than
   arriving half-formed and being treated as real data.
3. **The DTO → Response projection cannot fail.** `from_<source>` classmethods assign named fields
   from an already-validated DTO, replacing the `model_validate({**dto.model_dump(), ...})` round
   trips in `accounts/responses.py`. There is no second validation step left to raise.

#### Pydantic across the board

The remaining `@dataclass` and `TypedDict` types become pydantic models, except six with real
reasons:

| Type | Why it must stay |
| --- | --- |
| `features/includes/types.py` `Include` | A `BaseModel` inside `Annotated[...]` erases nested descriptions from the published schema — already documented there |
| `config.py` `AsyncpgConnectArgs` | Splatted as `**kwargs` into asyncpg; the TypedDict is the contract |
| `backstop_client/factory.py` `_Gate`, `_GateRegistry` | Hold `asyncio.Semaphore` / `asyncio.Lock` |
| `server/runtime.py` `Services` | Holds live service objects |
| `features/includes/resolve.py` `_PlannedInclude`, `IncludePlan` | Hold `type[BaseModel]` class objects; `IncludePlan` carries `project()` |
| `backstop_client/pagination.py` `_Accumulator` | Mutable accumulator owning a private dedup set |

`db/models.py` is SQLAlchemy and out of scope entirely.

Converting: the 5 `data_hygiene` dataclasses, `org_people`'s 2, `Gist`, `BackstopAuthContext`,
`ThrottleConfig`, `_RefreshRotated`/`_RefreshRejected`, `BackstopCredentialSecret`, `RetryPolicy`,
`SinglePage`, `PageResult`, `FetchArgs`, `TimedGate`, and the `EntityRelationships` TypedDict.

`SinglePage` and `PageResult` sit on the hot path: `SinglePage` is built from an
*already-validated* `_Page[T]`, so making it a `BaseModel` would re-validate every item on every
page of a 10k-record walk. They are constructed via `model_construct` to keep the conversion free.

### Error Handling

The refactor removes failure modes rather than adding any. No new exception types and no changed
ones.

`BackstopResponseSchemaError` keeps its current blast radius: `deserialize()` validates
`_Page[Record]`, so one malformed record still fails its whole page. **This means "never fail on
deserialization" is not fully achieved by this stack** — a record missing a required `id` still
fails its page rather than being dropped. Per-item tolerance in `parse_page` (validate items
individually, drop and count failures on `SinglePage`) is a deliberate follow-up, kept out so this
stack carries no runtime behaviour change.

Renaming `PersonAttributes` → `PersonRecordResponse` changes `$defs` keys in the published output
schema. Field names and structure are unchanged, so it is semantically identical to an MCP client,
but it is a visible diff — so the stack includes a manual before/after comparison of every tool's
published schema rather than assuming it.

### Testing Strategy

No new behavioural tests. The existing ~40 test files are the safety net, and for a mechanical
refactor they should pass with only import lines and class names edited — any test needing a real
change is a signal that something non-mechanical happened, and is worth stopping on.

One addition: rule 5 in `tests/test_layering.py`, which already walks the AST for four structural
rules without importing anything. Rule 5 asserts that a `*Attributes` class lives in
`api_responses*`, `*Dto` in `internal_dto*`, `*Response` in `responses*`; that imports run one way
only (`responses` → `internal_dto` → `api_responses`); and that no model declares
`extra="forbid"`. `features/includes/` is exempt by an explicit allowlist entry, with the reason in
the test's docstring so nobody "fixes" it later.

`tests/server/tools/test_output_descriptions.py` walks tool return models asserting every field has
a description, and `test_models.py` covers the `OmitNoneModel` machinery. Neither snapshots `$defs`,
so the renames break neither and there is no snapshot to update.

## Out of Scope

* **Per-item page tolerance.** `parse_page` keeps failing the page on one bad record. Own follow-up.
* **Splitting `features/includes/`** into wire + response layers. Justified above.
* **`db/models.py`.** SQLAlchemy declarative models are not in the three-layer scheme.
* **Any change to tool names, tool arguments, or published field names.** Only `$defs` keys move.
* **New tools, new fields, new Backstop endpoints.** Nothing about behaviour changes.
* **Reworking `features/resolution.py`'s generics** into the new filenames. Its suffixes already
  disambiguate and it is not per-feature.

## Tasks

1. **Split `accounts` into the three modules** — Move the 7 wire shapes from `types.py` into
   `api_responses.py` and the 11 computation models into `internal_dto.py` with the `Dto` suffix.
   Update `__init__.py` re-exports and every import inside the package.

2. **Split `accounts/responses.py` into a `responses/` package** — It is ~590 lines. Divide along
   the two tools plus the shared account-row / figure vocabulary its docstring already describes.

3. **Split the remaining feature packages** — `party_resolver`, `data_hygiene`, `activity_history`,
   `opportunities`, `org_people`, `custom_fields`, per the per-package table. Includes lifting the
   six private `_*Attributes` classes out of `activity_history/fetch_*.py` and folding
   `activity_detail_responses.py` into `responses.py`.

4. **Move the double-duty models to `responses.py`** — `AsOf` → `AsOfResponse`,
   `ActivityContinuation` → `ActivityContinuationResponse`, `ActivityGroup` →
   `ActivityGroupResponse`, `OpportunityFetchResult` → `OpportunityFetchResponse`. Each already
   carries FastMCP descriptions and is published as-is.

5. **Rename the three mislabelled `server/tools` models** — `PersonAttributes` →
   `PersonRecordResponse`, `OrganizationAttributes` → `OrganizationRecordResponse`, and
   `get_activity_history_utils.py` `PartyAttributes` → `PartyRecordResponse`. Rename
   `data_hygiene`'s `ProvenanceFields` mixin to `ProvenanceAttributes` and move it to
   `api_responses.py`.

6. **Compare published output schemas before and after** — Dump every tool's published output
   schema on `main` and on the branch, and confirm the only differences are `$defs` keys.

7. **Add rule 5 to `tests/test_layering.py`** — Suffix-to-module mapping, one-way import direction,
   no `extra="forbid"`, with `features/includes/` allowlisted and the reason documented.

8. **Convert the response factories to `from_<source>` classmethods** — All ~25, across `features/`
   and `server/tools/`. Nullable ones return `Self | None`; `unresolved_*` union returns land on the
   ambiguous class; `resolution.py`'s generics keep their free functions and receive bound
   classmethods. Delete `as_of_response`.

9. **Remove the dict round-trip projections** — `account_row_response` and `position_row_response`
   currently go through `model_validate({**dto.model_dump(), ...})`. Their classmethods assign named
   fields from the DTO instead.

10. **Convert the `backstop_client` factories** — `parse_json_api_error` →
    `BackstopApiError.from_response`, `build_retry_policy` → `RetryPolicy.from_settings`.

11. **Audit `*Attributes` fields against the validation policy** — Default every field where absence
    is survivable; document in a comment each field that stays required because absence makes the
    record invalid. Confirm no model declares `extra="forbid"`.

12. **Convert the remaining dataclasses and TypedDicts to pydantic** — Everything except the six
    documented exclusions. Build `SinglePage` and `PageResult` via `model_construct` so the hot
    pagination path does not re-validate already-validated items.
