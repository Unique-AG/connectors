<!-- confluence-page-id: tobefilled -->
<!-- confluence-space-key: PUBDOC -->

## Overview

This section describes what Backstop MCP can read from Backstop and what it can write, area by
area. Each chapter says which tools cover the area, what they return, and the limits and Backstop
quirks that shape the answers. For one line per tool, see [Tools](../tools.md).

| Area | Reads | Writes | Chapter |
|---|---|---|---|
| Organizations, people, employment | Look up one record; search firm-wide; roster of an organization; colleagues; categories and sources | Create, update, delete people and organizations; addresses; start and end employment | [Contacts](./contacts.md) |
| Activities and tasks | Search firm-wide or per party; full body and attachments; last activity per party; party streams; tasks; tags | Log notes, meetings, calls, tasks; attach documents and emails; update; delete | [Activities](./activities.md) |
| Opportunities | A party's deals with stage history; firm-wide search and counts; deals by id | Create, update and move stage, delete, backfill stage history | [Opportunities](./opportunities.md) |
| Products and investor accounts | Product catalog; a party's holdings; a product's investors; dated series; subscriptions and redemptions | None | [Products and Accounts](./products-and-accounts.md) |
| Custom fields | Definitions, layout tabs and groups, values on records | Values on people, organizations, opportunities | [Custom Fields](./custom-fields.md) |
| Reports and links | Saved Report Center reports; CRM UI links | None | [Reports and Links](./reports-and-links.md) |

## Behaviour Shared by Every Area

### Every call runs as the user

Each request to Backstop carries the connected user's own credential. Backstop applies that user's
permissions, so two users can get different answers to the same question. Counts such as
`coverage.visible_count` mean "visible to this user", not firm-wide totals. Records a user creates are
authored by them in Backstop. See [Authentication](../../operator/authentication.md).

### Parties and ids

Backstop keeps parties in four collections with separate id spaces: `organizations`, `people`,
`contacts`, and `employees`. Party-scoped tools take a name or email in `search`, or a `party_id` plus
the `search_type` it belongs to. A `contacts` or `employees` id is not a `people` id. Account,
product, opportunity, and activity ids are never party ids.

A `party_id` is trusted as given: the server does not look it up first. A name is resolved through
Backstop's quick search, and several matches either prompt the user or come back as `candidates`. See
[Architecture: Party resolution](../architecture.md#Party-resolution).

### Text matches literally

Backstop does not match abbreviations, synonyms, or alternative spellings. The server instructions
tell the model to try variants (full name and abbreviation, singular and plural) and say which ones it
tried. An empty first search is not proof that nothing exists.

### Where filters run

Backstop rejects many filters, so the chapters say where each one runs:

- **Sent to Backstop**: Backstop applies the filter and returns only matching rows.
- **Applied by the server**: the server reads rows from Backstop and filters them itself. A search
  with only such filters may read far more rows than it returns.

### Missing is not zero

Response models drop fields that have no value instead of sending `null` or `0`. A `0.0` that is
present is a real zero Backstop published. Flags say when a check could not be made:

| Flag | Meaning |
|---|---|
| `custom_fields_unavailable` (opportunity reads) | The custom-field catalog could not be loaded; an empty `custom_field_values` does not mean the deal has none. `get_person`, `get_organization`, and `search_products` have no such flag: a failed catalog gives an empty list |
| `status: "unknown"` (last activity) | That party could not be checked |
| `status: "unavailable"` (activity search) | Backstop's activity search did not answer; this is not "no activity" |
| `scan_truncated` (capital flows, tasks) | There were more rows than the server reads; results are partial |
| `coverage.ceiling_hit`, `coverage.truncated` (activity search) | The match set reached Backstop's 10,000-row ceiling, or a page failed; results are partial |

### Paging

Four searches return one page per call: `search_organizations`, `search_people`,
`search_opportunities` (rows), and `search_activities` (rows). A page has up to
`SEARCH_RESULT_SIZE` (100) rows. A `continuation.cursor` means more may match; the next call passes it
back unchanged with the same arguments. No `continuation` means the set is complete. Counting questions use
`mode="aggregate"`, which reads every match in one call. See
[Architecture: Paged searches](../architecture.md#Paged-Searches).

### CRM links

Most records carry a `url` to their Backstop UI page when the deployment has a UI origin configured.
On the four paged searches `url` is a selectable field rather than a default one. See
[Reports and Links](./reports-and-links.md#CRM-UI-Links).

### Writing safely

| Rule | Why |
|---|---|
| **Creates are not idempotent** | Repeating `create_person`, `log_activity`, and so on makes a second record |
| **Deletes are permanent** | Backstop has no recycle bin. `delete_person`, `delete_organization`, `delete_activity`, and `delete_opportunity` take one trusted id. When the client supports elicitation, they show the record and ask the user to confirm first; when it does not, they delete immediately |
| **Bulk deletes are refused** | The server instructions tell the model to refuse bulk wipes and search-then-delete sweeps |
| **Destructive hint** | All write tools except `log_activity` and `attach_file` are annotated `destructiveHint: true`, so hosts that honour it ask before running them |
| **One writer per concern** | Custom-field values only through `update_custom_field_values`; a deal's stage only through `update_opportunity` |
| **Omit to leave unchanged** | Update tools only send the fields given. To clear a custom field, send `value: null` explicitly. List fields (activity tags, attendees, `replace_category_ids`) replace the whole list; an empty list clears it |
| **Bulk writes report per row** | Backstop answers a bulk write with `201` even when rows fail. `update_custom_field_values` and `backfill_opportunity_stage_history` report each row as `applied` or `failed` |

## Not Supported

- Listing saved reports. `run_report` needs the exact report name.
- Writing funds, accounts, flows, time series, activity tags, contact categories, contact sources, or
  system users.
- Setting *Key employee* on a person or employment. It is read-only here; set it in the Backstop UI.
- Creating an email record without the message file. Backstop requires the file.
- Creating activity tags. Tag ids must already exist.
- Moving several deals' stages in one call.
- Reading the account record behind an account URL. Its id works with `get_time_series` and
  `get_capital_flows`.
- Editing a person's or organization's email address book (`contact-emails`). Use the `email`,
  `email2`, and `email3` fields instead.
- Changing permission buckets.

## Related

- [Technical Reference](../README.md)
- [Tools](../tools.md)
