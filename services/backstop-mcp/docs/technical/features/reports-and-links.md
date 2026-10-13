<!-- confluence-page-id: tobefilled -->
<!-- confluence-space-key: PUBDOC -->

## Overview

Two read-only helpers: running saved Report Center reports, and working with links to the Backstop
web UI.

Code: [`features/reports`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/reports),
[`features/ui_links`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/ui_links).

## Saved Reports

`run_report` runs a report saved in Backstop's Report Center, by its exact name, and returns one page
of it as a table.

| Input | Behaviour |
|---|---|
| `report_name` | The exact Report Center name. Backstop has no endpoint that lists reports, so the user has to name it. An unknown name returns `not_found` |
| `as_of_date` | Defaults to today on the server. Follow-up pages must repeat the same date |
| `limit` | Rows per page, default 100, at most 500 (Backstop's recommended report page size) |
| `offset` | Row to start from; pass `next_offset` from the previous page |

The response has `columns` (the header), `rows` (cell *i* under `columns[i]`), `total` (all rows),
and `next_offset` when more rows remain.

- **Reports cannot be filtered by product or date** through the API. Filter on the report's own
  columns after reading the pages you need.
- **Slow builds.** A report Backstop has not built recently can take minutes. Each call waits up to
  50 seconds; if the build is still going, it returns `status: "running"` with no rows, and the build
  continues in the background. Calling again with the same name, date, limit, and offset collects the
  result instead of starting another build.
- The running build is held in the memory of the pod that started it, keyed by user, report, date,
  and page, for up to 1 hour. With several replicas, a follow-up call that reaches a different pod
  starts the build again. A build that fails is dropped, so the next call starts fresh. At most 1,000
  builds are held; past that the oldest is dropped and its request cancelled.
- Requests to `/reports` use `BACKSTOP_REPORTS_TIMEOUT_SECONDS` (600) instead of the ordinary timeout.

## CRM UI Links

### Links on records

Reads publish a `url` to the record's page in the Backstop UI: people, organizations, opportunities,
accounts, products, tasks, and activities whose type has a UI page. On the four paged searches
(`search_organizations`, `search_people`, `search_opportunities`, `search_activities`), `url` is a
selectable field rather than a default, because one URL per row across thousands of rows adds up. A
row with no page of its own (for example a generic `meeting_call` search row) has no `url` rather
than a guessed one.

The UI origin comes from `BACKSTOP_UI_BASE_URL` (unset by default), or from `BACKSTOP_BASE_URL`
(default `https://api.backstopsolutions.com`) when its host is not `api.backstopsolutions.com`. With
neither, records carry no `url`. See
[Configuration: CRM links](../../operator/configuration.md#CRM-links).

### `build_backstop_links`

Builds labeled links for one record that a previous tool already returned. `target` names the kind
and its id: `organization`, `person`, `account`, `product`, `opportunity`, `task`, `email`, `call`,
`meeting`, `note`, or `document`.

- Without `tabs`, it returns the canonical page plus every tab allowed for that page. `tabs=[]`
  returns only the canonical page. A requested tab the page does not have comes back in
  `unrecognized_tabs`. Email and task pages have no tabs, and a product's summary is its canonical
  page.
- `layout_name` and `view_entity_type` (both from `list_custom_fields`) together build a layout link,
  for organizations, people, accounts, products, and opportunities only. One without the other is
  ignored.
- Activity links take the bare `id` of a `search_activities` row.
- Without a UI origin the answer is `status: "not_configured"`; the server never guesses a host.

### `parse_backstop_link`

Reads a Backstop UI URL a user pasted and returns the page, record id, tab, and layout, plus
`suggested_tool` and a note on what to call next.

- An account id is not a party id, and a task URL cannot be loaded with `get_tasks_for_party`; the
  note says so.
- An Activity Search URL yields the related party's id, not an activity id. Without a related
  party it is unrecognised.
- A URL the parser does not recognise returns `status: "unrecognized"`.
- When the pasted host differs from the configured UI host, `host_mismatch` is true and the URL is
  still parsed. Parsing works without a configured UI host; `host_mismatch` is then false.

No tool loads the account record behind an account URL. Its id works with `get_time_series`
(`entity_type: accounts`) and `get_capital_flows` (`account_ids`).

## Related

- [Features overview](./README.md)
- [Products and Accounts](./products-and-accounts.md)
- [Tools: Reports and Links](../tools.md#Reports-and-Links)
