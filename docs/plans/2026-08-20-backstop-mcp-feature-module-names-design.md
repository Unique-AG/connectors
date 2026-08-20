# Design: name backstop-mcp feature modules after the function they expose

## Problem

`services/backstop-mcp/src/backstop_mcp/features/` names its logic modules after a mechanism
rather than after what they do. Six packages have a `fetch.py`; three have a `service.py`;
`accounts/` alone has `fetch.py`, `latest.py`, `positions.py`, `product.py` and `project.py`.
Reading the file tree does not tell you where anything lives — you have to open files or grep for
`def`. The model layers (`api_responses.py`, `internal_dto.py`, `responses.py`) are exempt: PR
#813 gave those a convention and they follow it.

Two consequences follow from the same root, and both are in scope:

**Construction escaped the model layer.** PR #813 moved model construction onto
`from_<source>` classmethods. `accounts/project.py` is 138 lines of exactly that work — mapping
`/accounts` resources and their side-loads into DTOs — that the sweep missed. Three services
still have free `create_*` factories. `activity_history/activity_handle.py` is a parse function
sitting beside the DTO it parses into.

**The test suite made 14 functions public purely to be tested.** `test_layering.py:71` exempts
`tests/` from rule 4 ("a package is entered through its `__init__`") with the stated reason that
it keeps "the pieces a package composes directly testable". The result is that
`latest_figure`, `fetch_positions`, `fetch_product_aum`, `reconcile`, `product_label`,
`match_product`, `project_owner`, `stage_names_from_included`, `resolve_stage_name`,
`matches_status`, `date_entered_order_key`, `order_by_date_entered`, `looks_like_email` and
`client_supports_elicitation` are called by no production code outside their own file. A further
seven are file-local or dead but publicly named: `project_investor_type`,
`project_included_product`, `is_party_search_type`, `stage_ref_id`, `current_stage_id`,
`project_opportunities`, `fetch_opportunity_stages`.

## Solution

### Overview

One rule for module names: **a module is named after the function it exposes.** Where two or
three functions form a single utility consumed together, they may share a file — named after the
entry point, never after a mechanism. Type and enum vocabulary modules (`api_responses.py`,
`internal_dto.py`, `responses.py`, `entity_types.py`, `includes/types.py`, `settings.py`) keep
their names.

The rule applies to every function imported across files, not only to `__all__` entries. That
removes the "is this public?" judgement call, and it is mechanically checkable — a new assertion
in `test_layering.py` verifies each logic module's name matches a symbol it defines.

Finishing PR #813's construction sweep is a precondition rather than a follow-up: several of the
worst-named files (`accounts/project.py`, `activity_history/activity_handle.py`, the three
`service.py` factories) stop existing once construction moves onto the models, so renaming them
first would be wasted work.

Tests then enter each feature package through its `__init__`, the same way production code does.
The `tests/` carve-out in `test_layering.py` is deleted and rule 4 extended to cover them. Suites
for functions that become private fold into the suite for the public function they serve.

`features/auth/` is out of scope for this design.

### Architecture

Target tree (unchanged files omitted):

```
accounts/
  fetch_accounts_for_party.py       <- fetch.py (split)
  fetch_accounts_for_product.py     <- fetch.py (split)
  fetch_product_positions.py        <- positions.py  (+ _fetch_positions, _fetch_product_aum, _reconcile)
  fetch_series.py                   <- latest.py     fetch_series, fetch_latest_from_series, _latest_figure
  resolve_product.py                <- product.py    (+ _match_product, _product_label)
  split_open.py                     <- project.py    the one genuine utility; stays a free function
  project.py                        DELETED, mappings move onto the models:
      project_owner             -> AccountOwnerDto.from_included()
      project_investor_type     -> InvestorTypeDto.from_included()
      project_included_product  -> ResolvedProductDto.from_included()
      account_owner / project_account / project_accounts / account_is_open
                                -> AccountRecordDto.from_resource() / .from_resources()
      AccountApiResponse alias  -> api_responses.py, with the other BackstopApiResource aliases

activity_history/
  fetch_activities_page.py          <- fetch_activities.py  (three fns, one utility: one page of one stream)
  fetch_activity_detail.py          unchanged
  extract_gist_from_html.py         <- gist_from_html.py    (to_gist -> extract_gist_from_html)
  group_activity_page.py            <- group.py             (group_page -> group_activity_page)
  activity_handle.py                DELETED:
      ActivityHandleDto      -> ResourceIdentifierDto (stays in internal_dto.py)
      parse_activity_handle  -> ResourceIdentifierDto.from_activity_id() classmethod

custom_fields/
  fetch_custom_field_definitions.py <- fetch.py
  custom_fields_service.py          <- service.py   CustomFieldsService.with_ttl_minutes()

data_hygiene/
  project_entity_relationships.py   <- entity_relationships.py (fn renamed off the bare noun)
  employment_index.py               <- employment.py  EmploymentIndex only: the fold in __init__ and its lookups
  employment_index_factory.py       <- service.py     EmploymentIndexFactory.from_vocabulary(), .index(),
                                                      and _employment_edges / _classify_employment /
                                                      _outranks / _to_record as its privates
  build_employment_index            DELETED - its body becomes EmploymentIndexFactory.index()

includes/
  include_plan.py                   <- resolve.py    (+ IncludePlan)

opportunities/
  fetch_opportunities.py            <- fetch.py      (eight helpers privatised)
  fetch_opportunity_stages.py       <- stages.py (split)
  opportunity_stages_service.py     <- stages.py (split, OpportunityStagesService.with_ttl_minutes())

org_people/
  fetch_people_for_organization.py  <- fetch.py

party_resolver/
  resolve_party.py                  <- resolve.py    (+ resolve_parties: singular and batch of one operation)
  quick_search.py                   <- search.py (split)
  search_by_email.py                <- search.py (split, + _normalized_email, _looks_like_email)
  fetch_party_name.py               <- search.py (split)
  _party_search_types.py            <- search.py     the shared SearchType -> Backstop constant maps
```

`features/entity_types.py` is vocabulary and keeps its name. `features/resolution.py` is the
cross-cutting generic resolution machinery that `test_layering.py:52` already exempts by name,
and is out of scope.

Three functions are renamed so the file name reads well rather than literally: `to_gist` ->
`extract_gist_from_html`, `group_page` -> `group_activity_page`, `entity_relationships` ->
`project_entity_relationships`. The last two were a vague verb and a bare noun respectively.

Service factories become classmethods, continuing the convention PR #813 states in its own body:

- `create_custom_fields_service(ttl_minutes=)` -> `CustomFieldsService.with_ttl_minutes()`
- `create_opportunity_stages_service(ttl_minutes=)` -> `OpportunityStagesService.with_ttl_minutes()`
- `create_employment_index_factory(...)` -> `EmploymentIndexFactory.from_vocabulary()`

All three are called once each, in `app.py:105-116`. Three names leave `__all__`.

### Error handling

No behaviour changes. Published field names, tool names, tool arguments and MCP-facing shapes are
unchanged; `tests/server/tools/test_output_descriptions.py` is the guard on that. The only
observable difference is import paths inside the package, which nothing outside the service
consumes.

The one judgement call with a behavioural edge: `LARGE_CATALOG` in `accounts/product.py` is an
internal warning threshold that a test currently imports directly. Rather than export it, that
test asserts on the emitted log record. `MAX_ORG_PEOPLE` and `MAX_POSITION_ACCOUNTS` are
different -- the tools publish their truncation counts, so they are contract and join `__all__`.

### Testing strategy

The unit under test for `features/` is each package's `__all__`. Tests import
`from backstop_mcp.features.accounts import resolve_product`, never
`...features.accounts.resolve_product import ...`. `tests/server/tools/` stays as the tool-level
layer and already works this way.

Mocking is at the HTTP boundary only, via `respx` -- which the suite already does everywhere.
Assertions are on returned models and on the shape of the outgoing request
(`route.calls.last.request.url.params`): the request this service sends is its observable
behaviour, and the query-param contract has caught real Backstop quirks. `route.call_count`
survives only in the TTL-cache suites, where it is the sole way to observe that a cache cached.

The carve-out at `test_layering.py:71-73` is deleted and rule 4 extended to `tests/`, so the
front-door rule is enforced rather than agreed.

Suite mapping:

| today | becomes |
| --- | --- |
| `accounts/test_match.py`, `test_resolve.py` | `test_resolve_product.py` |
| `accounts/test_positions.py` | `test_fetch_product_positions.py` |
| `accounts/test_project.py` | mapping cases -> `test_internal_dto.py`; rest -> `test_split_open.py` |
| `accounts/test_latest.py` | `test_fetch_series.py` |
| `accounts/test_fetch.py` | `test_fetch_accounts_for_party.py`, `test_fetch_accounts_for_product.py` |
| `activity_history/test_fetch_activities.py` | `test_fetch_activities_page.py` |
| `activity_history/test_gist_from_html.py` | `test_extract_gist_from_html.py` |
| `activity_history/test_group.py` | `test_group_activity_page.py` |
| `custom_fields/test_fetch.py` | `test_custom_fields_service.py`, `test_fetch_custom_field_definitions.py` |
| `data_hygiene/test_employment.py`, `test_service.py` | `test_employment_index.py`, `test_employment_index_factory.py` |
| `data_hygiene/test_entity_relationships.py` | `test_project_entity_relationships.py` |
| `includes/test_resolve.py` | `test_include_plan.py` |
| `opportunities/test_fetch.py` | `test_fetch_opportunities.py` |
| `opportunities/test_stages.py` | `test_fetch_opportunity_stages.py`, `test_opportunity_stages_service.py` |
| `org_people/test_fetch.py` | `test_fetch_people_for_organization.py` |
| `party_resolver/test_resolve.py`, `test_disambiguate.py` | `test_resolve_party.py`, `test_quick_search.py` |
| `party_resolver/test_email.py` | `test_search_by_email.py` |

Roughly 3,500 lines need real restructuring rather than a mechanical rename: `test_employment.py`
(921), `test_resolve.py` (977), `opportunities/test_fetch.py` (826), `test_positions.py` (291),
`test_project.py` (292), `test_latest.py` (198), plus `test_match.py` and `test_email.py`.

Converting a pure-function suite into an HTTP-driven one is not lossless, and the design accepts
that rather than working around it. `match_product` has 18 assertions over hand-built
`ResolvedProductDto` lists; through `resolve_product` each needs a `/products` JSON page. Cases
covering a DTO shape that cannot arise from the wire become unreachable and are deleted rather
than contorted into existence. That is a genuine coverage reduction and the correct one: an
unreachable state is not behaviour.

## Out of Scope

- `features/auth/` -- excluded entirely at the user's request.
- `features/resolution.py` -- cross-cutting, already exempted by name in `test_layering.py`.
- `backstop_client/`, `server/`, `db/` -- only `features/` names are wrong.
- Tool names, tool arguments, published field names, MCP-facing shapes.
- Splitting `features/resolution.py` into a package, however tempting at 419 lines.
- Any behaviour change. If a test has to change because behaviour changed, the change is wrong.

## Tasks

1. **Move `accounts/project.py` mappings onto the models** - Turn `project_owner`,
   `project_investor_type`, `project_included_product`, `account_owner`, `project_account`,
   `project_accounts` and `account_is_open` into `from_included` / `from_resource` /
   `from_resources` classmethods on the DTOs they build. Move the `AccountApiResponse` alias to
   `api_responses.py`. Keep `split_open` a free function; delete `project.py`.

2. **Fold `parse_activity_handle` onto its DTO** - Rename `ActivityHandleDto` to
   `ResourceIdentifierDto` and turn `parse_activity_handle` into its
   `from_activity_id()` classmethod. Delete `activity_history/activity_handle.py` and update the
   `__init__` and call sites.

3. **Turn the three service factories into classmethods** - `CustomFieldsService.with_ttl_minutes`,
   `OpportunityStagesService.with_ttl_minutes`, `EmploymentIndexFactory.from_vocabulary`. Update
   `app.py:105-116` and drop the three `create_*` names from their packages' `__all__`.

4. **Rearrange the employment index** - Reduce `EmploymentIndex` to the fold and its lookups in
   `employment_index.py`. Move all assembly into `EmploymentIndexFactory` in
   `employment_index_factory.py` as private methods. Delete `build_employment_index` and
   `employment.py`.

5. **Rename the remaining feature modules** - Apply the tree above across `accounts`,
   `activity_history`, `custom_fields`, `data_hygiene`, `includes`, `opportunities`, `org_people`
   and `party_resolver`. Split `party_resolver/search.py` into three modules plus a private
   `_party_search_types.py`. Rewrite each package's `__init__` imports.

6. **Rename the three functions whose names read badly** - `to_gist` ->
   `extract_gist_from_html`, `group_page` -> `group_activity_page`, `entity_relationships` ->
   `project_entity_relationships`, and their modules to match.

7. **Assert the naming rule in `test_layering.py`** - Add a rule that every logic module in
   `features/` (excluding the vocabulary modules) defines a symbol matching its own filename.
   Document it in the module docstring alongside the existing five.

8. **Privatise the functions that only tests call** - Underscore-prefix the 14 test-only functions
   and the seven file-local ones, and remove them from any `__all__`. Export `MAX_ORG_PEOPLE` and
   `MAX_POSITION_ACCOUNTS`, which are contract.

9. **Restructure the feature test suites** - Rework the suites per the mapping table so each
   drives its package's public function through `respx`. Fold helper suites into the public
   function's suite; delete cases that only reach unreachable states.

10. **Enforce the front door for tests** - Delete the `tests/` carve-out at
    `test_layering.py:71-73` and extend rule 4 to walk `tests/` as well as `src/`. Update the
    module docstring to say why the carve-out went.
