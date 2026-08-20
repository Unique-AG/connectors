# PR Proposal

Three stacked PRs. Base of the stack is `backstop-mcp/feat/UN-23684-model-layers`
(PR #813, https://github.com/Unique-AG/connectors/pull/813). Each PR sets `--base` to the branch
below it; the stack rebases forward as #813 changes.

```
main
 └── backstop-mcp/feat/UN-23684-model-layers        PR #813 (open)
      └── backstop-mcp/refactor/construct-on-models        PR 1
           └── backstop-mcp/refactor/name-modules-after-functions   PR 2
                └── backstop-mcp/test/features-front-door           PR 3
```

---

## PR 1

### Branch
`backstop-mcp/refactor/construct-on-models` (base: `backstop-mcp/feat/UN-23684-model-layers`)

### Title
`refactor(backstop-mcp): construct feature models on the models`

### Description
- Move `accounts/project.py`'s seven mapping functions onto `from_included` / `from_resource` /
  `from_resources` classmethods on `AccountOwnerDto`, `InvestorTypeDto`, `ResolvedProductDto` and
  `AccountRecordDto`; delete `project.py`, keeping `split_open` as a free utility.
- Rename `ActivityHandleDto` to `ResourceIdentifierDto` and fold `parse_activity_handle` into its
  `from_activity_id()` classmethod, deleting `activity_history/activity_handle.py`.
- Replace the three free service factories with classmethods:
  `CustomFieldsService.with_ttl_minutes`, `OpportunityStagesService.with_ttl_minutes`,
  `EmploymentIndexFactory.from_vocabulary`.
- Reduce `EmploymentIndex` to the fold and its lookups; move all index assembly into
  `EmploymentIndexFactory` as private methods and delete `build_employment_index`.
- Completes the `from_<source>` construction convention PR #813 states; no behaviour change.

---

## PR 2

### Branch
`backstop-mcp/refactor/name-modules-after-functions` (base: `backstop-mcp/refactor/construct-on-models`)

### Title
`refactor(backstop-mcp): name feature modules after the function they expose`

### Description
- Rename every logic module in `features/` after the function it exposes: `custom_fields/fetch.py`
  becomes `fetch_custom_field_definitions.py`, `accounts/fetch.py` splits into
  `fetch_accounts_for_party.py` and `fetch_accounts_for_product.py`, the three `service.py` files
  take their class's name, and so on across eight packages.
- Split `party_resolver/search.py` into `quick_search.py`, `search_by_email.py` and
  `fetch_party_name.py`, with the shared `SearchType` maps in a private `_party_search_types.py`.
- Rename three functions whose names read badly under the rule: `to_gist` ->
  `extract_gist_from_html`, `group_page` -> `group_activity_page`, `entity_relationships` ->
  `project_entity_relationships`.
- Add a `test_layering.py` rule asserting each logic module defines a symbol matching its filename;
  the model-layer and vocabulary modules stay exempt.
- Import paths only. No behaviour change, no change to tool names, arguments or published fields.

---

## PR 3

### Branch
`backstop-mcp/test/features-front-door` (base: `backstop-mcp/refactor/name-modules-after-functions`)

### Title
`test(backstop-mcp): enter feature packages through the front door`

### Description
- Restructure the feature suites so each drives its package's `__all__` through `respx` rather than
  importing internals: `test_match.py` folds into `test_resolve_product.py`, `test_disambiguate.py`
  and `test_email.py` into the `party_resolver` suites, `test_service.py` into
  `test_employment_index_factory.py`, and the rest are renamed to mirror their modules.
- Privatise the 14 functions that only tests called and the seven that were file-local or dead;
  export `MAX_ORG_PEOPLE` and `MAX_POSITION_ACCOUNTS`, which the tools publish as truncation counts.
- Delete the `tests/` carve-out in `test_layering.py` and extend rule 4 to walk `tests/`, so
  "a package is entered through its `__init__`" is enforced rather than agreed.
- Keeps `respx` as the only mock and assertions on returned models and outgoing request shape;
  `route.call_count` survives only in the TTL-cache suites where it is the sole observable.
- Deletes cases that only reach states unreachable from the wire rather than contorting them into
  HTTP fixtures.

---

## Implementation notes

All three scopes landed on `backstop-mcp/feat/UN-23684-refactor-file-names` (base: PR #813)
rather than the stacked branches above.

Deviations from the design that are intentional:

- `split_open` is exported from `features.accounts` so `test_split_open.py` can drive it as a
  public utility. Tools still go through `fetch_accounts_for_*`.
- Mapping-table files that would have tested unexported functions were not created.
  `fetch_series` coverage lives on `test_fetch_product_positions.py`; email / quick-search
  coverage on `test_resolve_party.py`; custom-field fetch and opportunity-stage fetch coverage
  on their service suites. `fetch_opportunity_stages` stayed public — it has its own module
  after the stages split.
- `looks_like_email` / `normalized_email` live unprefixed in `_party_search_types.py` so sibling
  modules can import them without private-name ignores; they are not in `party_resolver.__all__`.
- Dead `is_party_search_type` was deleted rather than underscore-prefixed.
  `client_supports_elicitation` was left public — it lives in out-of-scope `resolution.py`.
- `LARGE_CATALOG` is `_LARGE_CATALOG`. `RetryPolicy`, `paginate_all`, and `parse_page` were
  added to `backstop_client.__all__` so client tests enter that package through its front door.
- Rule 4 walks `tests/` as well as `src/`. Auth tests may still import `features.auth.*`
  internals (auth was out of scope) but must enter `db` / `backstop_client` through `__init__`.
  Tool tests import the tool module under test (`get_*` / `list_*`) and `TOOLS` from
  `server.tools`.
