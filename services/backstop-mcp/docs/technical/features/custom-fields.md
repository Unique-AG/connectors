<!-- confluence-page-id: tobefilled -->
<!-- confluence-space-key: PUBDOC -->

## Overview

Most of what a firm configures in Backstop lives in custom fields: picklists, flags, dates, and
links to other records, laid out in tabs and groups on each record type. This chapter covers reading
the catalog, how values appear on records, and writing values.

Code: [`features/custom_fields`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/custom_fields).

| Question | Tool |
|---|---|
| Which custom fields exist, their types and options | `list_custom_fields` |
| How fields are arranged in the CRM layout | `list_custom_field_groups` |
| Values on one record | `get_person`, `get_organization`, `get_opportunities`, `get_opportunities_by_ids`, `search_products` |
| Records whose field has a given value | `search_people`, `search_organizations`, `search_opportunities`, `search_products` (`custom_fields` filter) |
| Change values | `update_custom_field_values` |

## The Catalog

`list_custom_fields` returns definitions for the `entity_types` asked for (at least one of
`organizations`, `people`, `accounts`, `opportunities`, `products`, and `party`). Each definition has
its id, name, field type, whether it is a time series, select options, layout name, tab, group and
group id, whether it is required, and its description. `search` keeps definitions whose name, tab,
group, layout, or one of the options contains the text, ignoring case.

- **`party` fields** are shared by people and organizations and are listed only under `party`, so ask
  for it alongside `people` or `organizations`.
- **Select options are the field's list of values.** Backstop calls a picklist's allowed values a
  list of values (LOV). Each definition carries its options inline as `selectOptions`, and the
  server returns them as select options. It does not read or edit Backstop's LOV lists directly.
- **Names repeat.** Several fields can share a name (for example one per event); the tab and group
  tell them apart.
- **Business terms are looked up, not assumed.** The server instructions tell the model to search the
  catalog for a term it does not know, decide from names, options, tabs, and groups which field is
  meant, and ask when none or several fit.

`list_custom_field_groups` returns the layout: each tab and section with its full path, its parent,
and the fields in it.

Both catalogs are cached for `BACKSTOP_CUSTOM_FIELD_SCHEMA_TTL_MINUTES` (120) by default, because
large tenants have thousands of definitions and one read takes several seconds. `refresh=true` reads
them again, for a field a CRM administrator just added. See
[Configuration: Catalog caches](../../operator/configuration.md#Catalog-Caches).

## Values on Records

There are two ways values appear, depending on the tool:

| Where | Shape |
|---|---|
| One-record reads (`get_person`, `get_organization`, `get_opportunities`, `get_opportunities_by_ids`) and `search_products` | Joined to the catalog: definition id, name, tab, group, type, and value. A value no longer among the field's options is kept and flagged `outside_current_options`. A value that references a record carries its id, resource type, and, for parties, a `search_type` |
| Searches (`search_people`, `search_organizations`, `search_opportunities`) and `get_product_investors` (account fields) | The stored value as text, straight from the record, without needing the catalog |

When the catalog cannot be loaded, the opportunity reads set `custom_fields_unavailable: true`; then
an empty list does not mean the deal has no values. `get_person`, `get_organization`, and
`search_products` have no such flag and return an empty list. Search rows still carry the stored
text. A joined read also leaves out a value whose definition is newer than the cached catalog, until
the catalog refreshes.

The one-record reads accept filters that narrow the values returned (`custom_field_names`,
`custom_field_definition_ids`, and for people and organizations also tabs, groups, and group ids).
Filters combine with AND.

Search filters (`custom_fields`) match by definition id and a list of allowed values. A record with no
value never matches.

## Writing Values

`update_custom_field_values` writes values on one `people`, `organizations`, or `opportunities` record
through Backstop's `POST /bulk-custom-field-values`.

```json
{"update": {"entity_type": "people", "entity_id": "<id from get_person>",
  "values": [{"definition_id": "<id from list_custom_fields>", "value": "Active Client"}]}}
```

- **Up to 15 values per call.**
- **Fields are identified by definition id**, never by name.
- **Values are checked against the catalog first.** The field must belong to `entity_type`; shared
  `party` fields are accepted on people and organizations only. A picklist value must be one of the
  current options. A time-series field needs `effective_date`; a regular field rejects one. A
  required field cannot be cleared, and a text value longer than the field's maximum length is
  rejected.
- **Only the listed fields change.** To clear a field, send `"value": null`. The server sends the
  `null` to Backstop explicitly, so a clear is not mistaken for "nothing to write".
- **Success is per value.** Backstop answers `201` even when values fail. The response has
  `total_count`, `applied_count`, and a `records` entry per value with `applied` or `failed` and the
  error. Success means `applied_count == total_count`. Messages Backstop did not tie to one value are
  in `warnings`.
- This is the only tool that writes custom fields. Person, organization, and opportunity write tools
  do not take custom-field values.

## Related

- [Features overview](./README.md)
- [Contacts](./contacts.md)
- [Opportunities](./opportunities.md)
- [Tools: Custom Fields](../tools.md#Custom-Fields)
