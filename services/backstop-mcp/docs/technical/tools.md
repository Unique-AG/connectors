<!-- confluence-page-id: tobefilled -->
<!-- confluence-space-key: PUBDOC -->

## Overview

The server registers 44 tools, listed in
[tool registry](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/server/tools/registry.py).
Each tool name links to its feature in [Features](./features.md), and `code` links to the file that implements it. The full contract (every argument, its
description, and the output schema) is published to MCP clients from the code, so this page only
says what each tool is for and what it returns. For behaviour and limits, see
[Features](./features.md).

**Kind:** *Read* tools are annotated `readOnlyHint: true`. *Write* tools create or change records.
*Delete* tools hard-delete; Backstop has no recycle bin. Every write and delete tool except
`log_activity` and `attach_file` is annotated `destructiveHint: true`, so MCP hosts that honour the
hint ask before running them. No tool is open-world.

**Delete confirmation:** when the client supports elicitation, a delete tool shows the record and
asks the user to confirm. A declined, cancelled, or timed-out prompt is a tool error and deletes
nothing. A client without elicitation support gets an immediate delete.

**Party-scoped tools** take `search` (a name or email) or a trusted `party_id` with its
`search_type`. When several records match, they ask the user to pick or return `candidates`; when
none match, they return `not_found`. Delete tools take only a trusted `party_id`. See
[Architecture: Party resolution](./architecture.md#Party-resolution).

## Contacts

| Tool | Kind | Returns |
|---|---|---|
| [`get_organization`](./features.md#Contacts) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/org_people/tools/get_organization.py) | Read | One organization: its fields, `as_of` provenance, custom-field values joined to the catalog, and optional side-loads (`locations`, `email_addresses`, `primary_contact`, `representative`) |
| [`get_person`](./features.md#Contacts) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/org_people/tools/get_person.py) | Read | One person: job title, department, email, `employments` (current and former organizations), custom-field values, optional side-loads (`locations`, `company`, …) |
| [`get_people_for_party`](./features.md#Contacts) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/org_people/tools/get_people_for_party.py) | Read | The people linked to an organization, each `current` or `former` there, with key-employee flag; former staff counted in `former_omitted` unless requested |
| [`search_organizations`](./features.md#Contacts) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/org_people/tools/search_organizations.py) | Read | One page of organizations matching name, email, domain, location, custom-field and other filters, with locations and custom-field values, plus a cursor |
| [`search_people`](./features.md#Contacts) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/org_people/tools/search_people.py) | Read | One page of people matching name, email, title, company, department, location, custom-field and other filters, plus a cursor |
| [`list_system_users`](./features.md#Contacts) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/system_users/tools/list_system_users.py) | Read | The firm's own Backstop users: name, `user_name` login, email, `disabled` |
| [`list_contact_categories`](./features.md#Contacts) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/contact_categories/tools/list_contact_categories.py) | Read | Contact-category ids and names, for the `category_ids` of party writes |
| [`list_contact_sources`](./features.md#Contacts) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/contact_sources/tools/list_contact_sources.py) | Read | Contact-source ids and names, for `contact_source_id` on party writes |
| [`create_person`](./features.md#Contacts) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/org_people_writes/tools/create_person.py) | Write | The new person's id, name, mobile phone as Backstop stored it, and CRM link |
| [`create_organization`](./features.md#Contacts) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/org_people_writes/tools/create_organization.py) | Write | The new organization's id, name, and CRM link |
| [`update_person`](./features.md#Contacts) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/org_people_writes/tools/update_person.py) | Write | The person read back after the change, mobile phone as Backstop stored it, and ids of created or changed addresses |
| [`update_organization`](./features.md#Contacts) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/org_people_writes/tools/update_organization.py) | Write | The organization read back after the change, and ids of created or changed addresses |
| [`create_employment`](./features.md#Contacts) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/org_people_writes/tools/create_employment.py) | Write | The new employment's id and start date. Backstop also creates the mirror row (organization to person) |
| [`end_employment`](./features.md#Contacts) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/org_people_writes/tools/end_employment.py) | Write | The employment's id and stored end date, with warnings (for example an end date that is not in the past) |
| [`delete_person`](./features.md#Contacts) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/org_people_writes/tools/delete_person.py) | Delete | The deleted id, `permanent: true`, and the location ids removed first. |
| [`delete_organization`](./features.md#Contacts) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/org_people_writes/tools/delete_organization.py) | Delete | The deleted id, `permanent: true`, and the location ids removed first. |

## Activities

| Tool | Kind | Returns |
|---|---|---|
| [`search_activities`](./features.md#Activities-and-Tasks) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/activity_history/tools/search_activities.py) | Read | Meetings, calls, notes, emails, and documents in a date window, firm-wide or for one party: one page of rows with a cursor, or counts grouped by type, tag, party, or period. Includes `coverage` and attachment counts |
| [`get_activity_detail`](./features.md#Activities-and-Tasks) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/activity_history/tools/get_activity_detail.py) | Read | One activity's full body as Markdown, its attachment list, and for meetings and calls the start, stop, location, time zone, and attendees |
| [`get_activity_history`](./features.md#Activities-and-Tasks) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/activity_history/tools/get_activity_history.py) | Read | One party's activity streams, one group per type, each a page of rows with a truncated `gist` and a `next` continuation. Fallback when `search_activities` is unavailable |
| [`get_last_activity_for_parties`](./features.md#Activities-and-Tasks) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/activity_history/tools/get_last_activity_for_parties.py) | Read | For up to 100 parties: the newest activity, the count in the window, and `days_since_last_activity`; `unknown` when a party could not be checked |
| [`get_tasks_for_party`](./features.md#Activities-and-Tasks) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/tasks/tools/get_tasks_for_party.py) | Read | One party's tasks, open, completed, or both |
| [`list_activity_tags`](./features.md#Activities-and-Tasks) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/activity_tags/tools/list_activity_tags.py) | Read | Activity-tag ids and names, how many activities carry each, and whether each is shown in the UI |
| [`log_activity`](./features.md#Activities-and-Tasks) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/activity_writes/tools/log_activity.py) | Write | The new record's id, kind, title, and CRM link; time zone and meeting type for meetings and calls; `send_notification` for tasks |
| [`attach_file`](./features.md#Activities-and-Tasks) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/activity_writes/tools/attach_file.py) | Write | The new document or email record's id, kind, and CRM link (no link for emails) |
| [`update_activity`](./features.md#Activities-and-Tasks) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/activity_writes/tools/update_activity.py) | Write | The changed record's id, collection, and CRM link |
| [`delete_activity`](./features.md#Activities-and-Tasks) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/activity_writes/tools/delete_activity.py) | Delete | The deleted record's id, collection, and `permanent: true`. |

## Opportunities

| Tool | Kind | Returns |
|---|---|---|
| [`get_opportunities`](./features.md#Opportunities) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/opportunities/tools/get_opportunities.py) | Read | Every deal of one party, filtered by open or closed: stage, previous stage, stage history, amounts, probability, custom fields, and open and closed counts |
| [`search_opportunities`](./features.md#Opportunities) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/opportunities/tools/search_opportunities.py) | Read | Firm-wide deals filtered by representative, stage, product, open state, stage-change window, or custom field: one page of rows with selectable fields and a cursor, or counts grouped by stage, product, period, or party |
| [`get_opportunities_by_ids`](./features.md#Opportunities) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/opportunities/tools/get_opportunities_by_ids.py) | Read | Up to 50 deals by id with resolved custom fields and, optionally, stage history; `not_found` and `errors` name the ids that failed |
| [`create_opportunity`](./features.md#Opportunities) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/opportunity_writes/tools/create_opportunity.py) | Write | The new deal's id, name, the stage Backstop stored, and CRM link, with warnings |
| [`update_opportunity`](./features.md#Opportunities) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/opportunity_writes/tools/update_opportunity.py) | Write | The deal's id, the stage Backstop landed on, CRM link, and warnings |
| [`backfill_opportunity_stage_history`](./features.md#Opportunities) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/opportunity_writes/tools/backfill_opportunity_stage_history.py) | Write | One outcome per history row (`applied`, or `failed` with the error), the applied count, and warnings |
| [`delete_opportunity`](./features.md#Opportunities) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/opportunity_writes/tools/delete_opportunity.py) | Delete | The deleted deal's id and `permanent: true`. |

## Products and Accounts

| Tool | Kind | Returns |
|---|---|---|
| [`search_products`](./features.md#Products-and-Accounts) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/accounts/tools/search_products.py) | Read | Every product matching name, id, type, onshore flag, modified date, or custom field, with its custom-field values |
| [`get_accounts_for_party`](./features.md#Products-and-Accounts) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/accounts/tools/get_accounts_for_party.py) | Read | A party's accounts across products with balance, commitment, unfunded commitment, shares, and `tenure_runs`; `source` and `data_caveat` say which endpoint answered |
| [`get_product_investors`](./features.md#Products-and-Accounts) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/accounts/tools/get_product_investors.py) | Read | The accounts in one or more products and their owners, with tenure rankings and, on request, each account's latest value and per-investor totals |
| [`get_time_series`](./features.md#Products-and-Accounts) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/accounts/tools/get_time_series.py) | Read | Dated points of one series (for example `values` or `aums`) on one account or product, newest first, with status where Backstop sends it |
| [`get_capital_flows`](./features.md#Products-and-Accounts) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/accounts/tools/get_capital_flows.py) | Read | Completed subscriptions and redemptions in a date window, with account, owner, amounts, share class and series |

## Custom Fields

| Tool | Kind | Returns |
|---|---|---|
| [`list_custom_fields`](./features.md#Custom-Fields) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/custom_fields/tools/list_custom_fields.py) | Read | Custom-field definitions for the requested entity types: id, name, type, layout, group, and picklist options |
| [`list_custom_field_groups`](./features.md#Custom-Fields) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/custom_fields/tools/list_custom_field_groups.py) | Read | The tabs and sections of the CRM layout, each with the fields in it |
| [`update_custom_field_values`](./features.md#Custom-Fields) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/custom_fields/tools/update_custom_field_values.py) | Write | One outcome per value (`applied`, or `failed` with the error), `applied_count` and `total_count`, and warnings |

## Reports and Links

| Tool | Kind | Returns |
|---|---|---|
| [`run_report`](./features.md#Saved-Reports) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/reports/tools/run_report.py) | Read | One page of a saved Report Center report as `columns` and `rows`, with `total` and `next_offset`; or `status: "running"` while Backstop builds it; `not_found` for an unknown report name |
| [`build_backstop_links`](./features.md#Backstop-Links) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/ui_links/tools/build_backstop_links.py) | Read | Labeled Backstop UI URLs for one record: the canonical page and its tabs or a layout; `not_configured` without a UI origin |
| [`parse_backstop_link`](./features.md#Backstop-Links) [code](https://github.com/Unique-AG/connectors/blob/main/services/backstop-mcp/src/backstop_mcp/features/ui_links/tools/parse_backstop_link.py) | Read | The page, record id, tab, and layout in a pasted Backstop URL, and which tool to call next |

## Related Documentation

- [Technical Reference](./README.md)
- [Overview](../README.md)
- [Features](./features.md)
- [Architecture](./architecture.md)
