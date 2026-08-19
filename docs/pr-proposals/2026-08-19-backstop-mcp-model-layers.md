# PR Proposal

Landing as a stack of five, reviewed together and merged as a whole stack.

## PR 1

### Title
`refactor(backstop-mcp): split feature models into api_responses, internal_dto, and responses`

### Description
- Split each feature's catch-all `types.py` into `api_responses.py` (`*Attributes`, parsed off
  Backstop JSON:API) and `internal_dto.py` (`*Dto`, computed internally and never published), leaving
  `responses.py` for `*Response` models published to MCP clients.
- Lift the six private `_*Attributes` wire shapes out of `activity_history/fetch_*.py`, and fold
  `activity_detail_responses.py` into `responses.py`.
- Move the four double-duty models that already carry FastMCP descriptions into `responses.py`:
  `AsOf` → `AsOfResponse`, `ActivityContinuation`/`ActivityGroup` → `*Response`,
  `OpportunityFetchResult` → `OpportunityFetchResponse`.
- Rename three outward models wearing the wire suffix: `PersonAttributes` → `PersonRecordResponse`,
  `OrganizationAttributes` → `OrganizationRecordResponse`, `PartyAttributes` (in
  `get_activity_history_utils.py`) → `PartyRecordResponse`; and `ProvenanceFields` →
  `ProvenanceAttributes`.
- Split `accounts/responses.py` (~590 lines) into a `responses/` package. `features/includes/` keeps
  its single-layer projection models, deliberately — they are wire shape and response at once.
- Moves and renames only. The only published-schema difference is `$defs` keys; field names and
  structure are unchanged.

## PR 2

### Title
`test(backstop-mcp): enforce the model layering in test_layering.py`

### Description
- Add a fifth structural rule to the existing AST walk: `*Attributes` must live in `api_responses*`,
  `*Dto` in `internal_dto*`, `*Response` in `responses*`.
- Assert imports run one way only — `responses` → `internal_dto` → `api_responses`.
- Assert no model declares `extra="forbid"`.
- `features/includes/` is allowlisted, with the reason documented so nobody "fixes" it later.

## PR 3

### Title
`refactor(backstop-mcp): construct models via from_<source> classmethods`

### Description
- Replace ~25 module-level factory functions with `from_<source>` classmethods on the model they
  build, matching the convention already in the tree (`ResolvedProduct.from_attributes`,
  `BackstopClientFactory.for_credential`).
- Nullable projections return `Self | None`, keeping the omit-when-blank rule beside the model that
  defines what blank means. Union returns (`ProductAmbiguousResponse | NotFoundResponse`) land on
  the ambiguous class.
- Drop the `model_validate({**dto.model_dump(), ...})` round-trips in `accounts/responses.py`, so a
  DTO → Response projection can no longer raise.
- Delete `as_of_response`, which was a pure identity function.
- `backstop_client` too: `parse_json_api_error` → `BackstopApiError.from_response`,
  `build_retry_policy` → `RetryPolicy.from_settings`.

## PR 4

### Title
`refactor(backstop-mcp): state the permissive validation policy on api_responses models`

### Description
- Ban `extra="forbid"`; `*Attributes` default to `extra="ignore"`, with `allow` only where relaying
  tenant custom fields is the point.
- Give every `*Attributes` field a default, or a lenient annotation that coerces junk to `None`,
  wherever absence is survivable.
- Keep required — with the reason in a comment — the fields whose absence makes a record invalid or
  unsafe: `ActivityItem.id`, `ActivityItem.stream`, `ActivityPage.end_of_stream`,
  `ContactEmailResponse.retired`.
- No runtime behaviour change: `parse_page` still fails a page on one malformed record. Per-item
  tolerance is a follow-up.

## PR 5

### Title
`refactor(backstop-mcp): replace remaining dataclasses with pydantic models`

### Description
- Convert the 20 remaining `@dataclass` types and 2 `TypedDict`s to pydantic models.
- Keep six as-is for documented reasons: `Include` (a `BaseModel` inside `Annotated[...]` erases
  nested schema descriptions), `AsyncpgConnectArgs` (splatted as `**kwargs`), `_Gate`/`_GateRegistry`
  (hold asyncio primitives), `Services` (holds live service objects),
  `_PlannedInclude`/`IncludePlan` (hold `type[BaseModel]` and carry behaviour), and `_Accumulator`
  (mutable, owns a private dedup set).
- Build `SinglePage` and `PageResult` via `model_construct`: they are assembled from an
  already-validated `_Page[T]`, so validating again would re-check every item on every page of a
  10k-record walk.
