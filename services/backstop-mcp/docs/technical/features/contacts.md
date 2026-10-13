<!-- confluence-page-id: tobefilled -->
<!-- confluence-space-key: PUBDOC -->

## Overview

Organizations and people are the core records of Backstop. This chapter covers reading and writing
them, the employment links between them, and the reference lists used when writing them.

Code: [`features/org_people`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/org_people),
[`features/org_people_writes`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/org_people_writes),
[`features/data_hygiene`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/data_hygiene),
[`features/system_users`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/system_users),
[`features/contact_categories`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/contact_categories),
[`features/contact_sources`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/contact_sources).

| Question | Tool |
|---|---|
| One organization or person, in full | `get_organization`, `get_person` |
| Who works at an organization | `get_people_for_party` |
| Every organization or person matching some criteria | `search_organizations`, `search_people` |
| Our own colleagues (Backstop users) | `list_system_users` |
| Valid category and contact-source ids for a write | `list_contact_categories`, `list_contact_sources` |

## Reading One Record

`get_organization` and `get_person` take a trusted `party_id` or a `search` (name or email).
`get_organization` accepts only the `organizations` collection; `get_person` defaults to `people` and
also accepts `contacts` and `employees` ids.

Both return:

- The record's own fields. Fields the server does not model are passed through as Backstop sent them.
- `as_of` provenance (Backstop's modified timestamp and modifying user) when Backstop provides it. It
  says when the record last changed, not whether it is out of date.
- `custom_field_values`, joined to the custom-field catalog: definition id, name, layout tab, group,
  type, and value. Values from the shared `party` catalog are included. Optional filters
  (`custom_field_tabs`, `custom_field_groups`, `custom_field_group_ids`,
  `custom_field_definition_ids`, `custom_field_names`) narrow the list; they combine with AND and
  names match case-insensitively. A value no longer in the field's option list is kept and flagged.
  A value that points at another record carries its id, resource type, and, for parties, the
  `search_type` to look it up with. If the catalog cannot be loaded the list is empty with no flag,
  and a value whose definition is newer than the cached catalog is left out until it refreshes.
- Optional side-loads through `include`, fetched in the same request:

| Record | `include` values |
|---|---|
| Organization | `locations`, `email_addresses`, `primary_contact`, `representative` |
| Person | `locations`, `email_addresses`, `company`, `representative` |

A requested list include comes back as `[]` when nothing is on file. `representative` is the colleague
at your own firm who owns the relationship. `email_addresses` is the address book; it is named that
way because Backstop's own `emails` relationship holds email messages.

`get_person` also returns `employments`: every organization the person is or was linked to, each
`current` or `former`. Its `is_key_employee` value is unreliable; the roster below is the source.

## Who Works at an Organization

`get_people_for_party` lists the people linked to one organization, each marked `current` or
`former` at that organization, with name, email, and key-employee flag. Former staff are counted in
`former_omitted` and listed only with `include_former=true`.

- At most 500 people are returned; `people_omitted` counts the rest.
- The roster comes from Backstop's `/organizations/{id}/employees`, plus the organization's
  relationship records for people who have left.
- The organization's `numberOfEmployees` field is not a roster and is often `0` while people are on
  file.
- Department is not on the roster; `get_person` has it.

### Current or former

Whether a link is current or former comes from the relationship's type and end date. Firms often
record a departure as a separate relationship type ("is a former employee of") rather than filling in
an end date. Which types count as employment and which as former employment is configurable; see
[Configuration: Departed-contact detection](../../operator/configuration.md#Departed-Contact-Detection).
A person fetched by id is always returned, with their links, even if every link is former.

## Searching Firm-Wide

`search_organizations` and `search_people` filter a whole collection and return one page of rows per
call, in Backstop id order (not by name), with a cursor. By default each row has its id, name,
email, city, country, and `locations` (organizations add `legal_name`; people add `job_title` and
`company_name`); `fields` selects others, including `url`. Every row also carries its custom-field
values as stored text.

Some filters are sent to Backstop; Backstop rejects the rest as query filters, so they are applied by
the server to each page it reads (see
[Where filters run](./README.md#Where-filters-run)).

| | Sent to Backstop | Applied by the server |
|---|---|---|
| `search_organizations` | `name` (substring), `email` (primary email only), `other_id`, `matching_domain`, location `city` and `street_address` | `legal_name`, other location fields, `website`, `ria`, `internal_organization`, `custom_fields` |
| `search_people` | `name` (exact display name, usually "Last, First"), `last_name` (substring), `other_id`, `email_domain`, location `city` and `street_address` | `email` (matches `email`, `email2`, or `email3`), `first_name`, `job_title`, `company_name`, `department`, other location fields, `website`, `custom_fields`, `min_current_organizations` |

- **Location filter.** All fields in one `location_filter` must match the same address. `city` and
  `street_address` must equal the stored value exactly, including case. `state` must be the whole
  value and `country` whole words, in any case; other fields are case-insensitive substrings. Any of
  the party's addresses may match unless `primary_only` is true. A party with no address never matches.
- **Custom-field filter.** Matches by definition id from `list_custom_fields`, not by label. A record
  without a value does not match.
- **A search with only filters applied by the server reads the whole collection** until it fills a
  page. Large tenants have thousands of organizations, so such calls are slower. Whenever any filter
  is applied by the server, later pages are fetched in parallel within the user's 5-request limit.
- **`exclude_custom_fields`** drops the stored custom-field values from the read. It exists to
  diagnose a call that timed out.
- `coverage.visible_count` is Backstop's total for the filters sent to Backstop, before the filters
  applied by the server.
- `search_people` reads `/people` only. People are the contacts and employees of organizations in
  the CRM; your own colleagues are system users.
- `company_name` on a person is a single text field. Organizations a person is linked to are the
  selectable `employments` field; `min_current_organizations=2` finds people under several
  organizations.

## Colleagues and Reference Lists

| Tool | Returns | Notes |
|---|---|---|
| `list_system_users` | Your firm's Backstop users: name, `user_name` login, email, phone, `disabled` | The login is what `search_opportunities` filters by and what a task is assigned to. A disabled login means a departed colleague |
| `list_contact_categories` | Category ids and names | For `category_ids`, `add_category_ids`, `replace_category_ids` on party writes |
| `list_contact_sources` | Contact-source ids and names | For `contact_source_id` on party writes |

All three accept `search` (substring) and `refresh`. On `list_system_users`, `refresh` does nothing
unless its catalog cache is enabled, and it is off by default. Categories and sources are standard Backstop
fields on parties, not custom fields.

## Writing

| Tool | Does | Rules |
|---|---|---|
| `create_person` | `POST /people`, then reads it back | `last_name` and `gender` required. `job_title` up to 140 characters. Addresses are added with `update_person` |
| `create_organization` | `POST /organizations`, then reads it back | `name` required, up to 50 characters. Addresses are added with `update_organization` |
| `update_person` | PATCH the person, then create, change, or delete addresses | Identify like `get_person`. At least one change. `last_name` cannot be cleared. `name` and legal name are derived from the name parts |
| `update_organization` | PATCH the organization, then address writes | Identify like `get_organization`. At least one change. `name` cannot be cleared, up to 50 characters |
| `create_employment` | `POST /entity-relationships` linking a person to an organization | Person identified like `get_person`, organization by `organization_id` or `organization_search`, and a required `start_date`. Backstop also creates the reverse (organization to person) row |
| `end_employment` | Writes `endDate` on the current employment | Fails if there is no current employment, or more than one. An end date that is not before today is stored, but the person reads as current until it passes, and the response warns |
| `delete_person`, `delete_organization` | Deletes the party's addresses, then the party | One trusted id. Permanent. Confirmation when the client supports it |

Details that matter when writing:

- **Addresses.** `locations` creates an address (no `location_id`) or changes one (with the
  `location_id` from `include=["locations"]`); `delete_location_ids` removes them. A new address needs
  a `location_title` unique on the party. One call cannot patch and delete the same id; deletes run
  before creates, so a title can be reused. The response lists the address ids written.
- **Emails.** Correct email addresses through `email`, `email2`, and `email3`, each up to 255
  characters. Backstop has no write endpoint for the `contact-emails` address book.
- **Phone numbers.** Backstop reformats numbers, so the response reports the number as stored.
- **Categories.** `category_ids` sets the initial list on create. Updates take `add_category_ids` or
  `replace_category_ids`, not both. `replace_category_ids=[]` clears the list; a single category
  cannot be removed on its own.
- **Key employee** is rejected on person and employment writes. Set it in the Backstop UI.
- **Custom fields** are written only through `update_custom_field_values`.
- **Employment type.** `create_employment` does not take a relationship type. It picks the single
  current-employment type from the instance's relationship types, using the configured ids first,
  then the name markers. If no type or more than one type matches, the call fails and lists the
  available types; set `BACKSTOP_EMPLOYMENT_RELATIONSHIP_TYPE_IDS` (empty by default) to resolve it.
- **Not writable here:** permission bucket, contact template, sync settings, group entities, and the
  denormalized `categoriesAsString`.

## Related

- [Features overview](./README.md)
- [Custom Fields](./custom-fields.md)
- [Tools: Contacts](../tools.md#Contacts)
