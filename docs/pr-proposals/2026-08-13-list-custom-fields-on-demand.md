# PR Proposal

## Title
feat(backstop-mcp): fetch custom fields on demand instead of glossary prefetch

## Description
- Stop appending custom-field glossaries on `tools/list`. `list_custom_fields` takes a list of
  types (`organizations`, `people`, `accounts`, `opportunities`, `products`, `party`) and returns
  the mapped definitions for those types, including layout fields and `selectOptions`.
- Map those names onto the live Backstop Beans (`OrganizationBean`, …, `PartyBean`). Lookups
  are case-insensitive. Omit `contacts` / `employees` — those are not valid `entityType` enum
  constants.
- Cache the full `/custom-field-definitions` walk in process memory
  (`BACKSTOP_CUSTOM_FIELD_SCHEMA_TTL_MINUTES`, default 60, max 24h; `page[limit]=1000`, no LOV
  fetch). Optional `refresh=true` only when the user reports a missing field. First caller
  fills the catalog for everyone.
- Remove glossary middleware (and the empty leftover package), the Postgres snapshot table, the
  service-account env pair, boot warmup, `/lov-entries`, and `BACKSTOP_CUSTOM_FIELD_OVERRIDES`.
