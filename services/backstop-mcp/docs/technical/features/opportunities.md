<!-- confluence-page-id: tobefilled -->
<!-- confluence-space-key: PUBDOC -->

## Overview

Opportunities are Backstop's sales pipeline: deals with an investor, an optional product, a stage, and
a stage history. This chapter covers reading the pipeline for one party or the whole firm, and
creating, changing, moving, and deleting deals.

Code: [`features/opportunities`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/opportunities),
[`features/opportunity_writes`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/opportunity_writes).

| Question | Tool |
|---|---|
| One party's deals and how each got to its stage | `get_opportunities` |
| The firm's pipeline: by colleague, stage, product, custom field, or stage-change window; counts | `search_opportunities` |
| Custom fields or stage history for deals found by a search | `get_opportunities_by_ids` |
| A colleague's login, to filter by representative | `list_system_users` |
| Deals with no recent activity | `search_opportunities`, then `get_last_activity_for_parties` |

## What a Deal Looks Like

Every read can return these deal fields; search rows carry only the selected `fields`:

| Field | Meaning |
|---|---|
| `id`, `name` | The deal |
| `stage`, `stage_id` | Where the deal is now. Stage names are the instance's own vocabulary |
| `previous_stage` | The stage the deal most recently **left**. Absent until the deal has moved |
| `date_entered_current_stage`, `days_in_current_stage`, `days_open` | Stage timing |
| `is_open`, `closed_date` | Whether the deal is still in the pipeline |
| `requested_amount`, `allocated_amount`, `currency` | Amounts |
| `probability` | Backstop's standard probability, a fraction (0.3 is 30%) |
| `weighted_value`, `weighted_allocated_value` | Backstop's own products of amount and probability |
| `expected_investment_date` | Expected close |
| `custom_field_values` | Deal custom fields (shape differs, see below) |

The rest depends on the tool:

| Field | `get_opportunities`, `get_opportunities_by_ids` | `search_opportunities` rows |
|---|---|---|
| `custom_field_values` | Joined to the catalog | Stored text |
| `stage_history` (each past move: stage, stage id, effective date) | Always on `get_opportunities`; on `get_opportunities_by_ids` with `include_stage_history=true` | Not available |
| `investor` (id, `search_type`, name, location), `product` (id, name, short name) | Not returned | Default fields |
| `representative`, `investor_representative` (logins) | Not returned | Selectable in `fields` |
| `url` (the deal in the Backstop UI) | By default | Only when selected in `fields` |

A stage the instance can no longer name keeps its id with the name omitted.

## One Party's Deals

`get_opportunities` takes a party (`search_type` plus `party_id` or `search`) and returns every deal
of that party, newest first by the day each entered its current stage, with stage history always
included.

- `status` is `open`, `closed`, or `all` (default). `total`, `open_count`, and `closed_count` cover
  the complete set either way. A deal whose open state Backstop does not publish appears only under
  `all`.
- There is no cursor. A party's pipeline is read whole, because paging would let an open deal on a
  later page look absent. Backstop also rejects an open/closed filter and ignores sorting on this
  collection, so both are applied by the server.
- `custom_field_names` and `custom_field_definition_ids` narrow the custom fields returned.

## Firm-Wide Search

`search_opportunities` reads Backstop's `/opportunities` collection: in rows mode until a page fills,
in aggregate mode in full. Filters are either sent to Backstop or applied by the server (see
[Where filters run](./README.md#Where-filters-run)).

| Filter | How it is applied |
|---|---|
| `representative` | A colleague's **login** from `list_system_users`. With the `deal` scope it is sent to Backstop as an exact match on the deal's representative. A display name returns nothing |
| `representative_scope` | `deal` (default): the deal's own representative. `investor`: the colleague who covers the investor organization. `either`: both. The last two are applied by the server, because Backstop cannot filter on the investor's representative |
| `is_open`, `stage` | Applied by the server |
| `product` | The linked product. A short name matches exactly, a name fragment matches every product containing it; several values are OR |
| `entered_stage_from`, `entered_stage_to` | Deals whose current stage was entered in the window. Applied by the server; Backstop rejects this filter |
| `custom_fields` | Definition id plus allowed values, from `list_custom_fields` |

- **Rows mode** returns one page with a cursor. By default each row has `id`, `name`, `stage`,
  `is_open`, `expected_investment_date`, `investor`, and `product`; `fields` selects others, such as
  amounts, `previous_stage`, `date_entered_current_stage`, `representative`,
  `investor_representative`, and `url`. `id` is always included.
- **Aggregate mode** counts every match, grouped by `stage`, `product`, `period`, or `party` (the
  investor). `period` is the `YYYY-MM` of `expected_investment_date`, else of
  `date_entered_current_stage`. A missing stage counts as `(unknown)`, a deal with no product or
  investor as `(unattributed)`, and a period with no date as `(undated)`.
- Pages are in id order, so the first pages are the oldest deals. A "what moved since" question must
  use `entered_stage_from` rather than reading the first pages. `previous_stage` and
  `date_entered_current_stage` describe only the latest move.
- `coverage.visible_count` is Backstop's count for the filters sent to Backstop, before the filters
  applied by the server. With the `investor` or `either` scope it is also before the representative
  filter.
- `exclude_custom_fields=true` skips reading stored custom-field values, to diagnose a timeout.

## Deals by Id

`get_opportunities_by_ids` fetches up to 50 deals with custom fields resolved against the catalog,
and stage history when `include_stage_history=true`. A missing id is listed in `not_found` and a
failed one in `errors`; the rest of the batch is still returned. It is the follow-up when a search row
lacks a field.

## Writing

| Tool | Does | Rules |
|---|---|---|
| `create_opportunity` | `POST /opportunities`, then reads it back | `name`, `currency_code`, `is_erisa`, and an investor are required. The investor is a party: `party_id` or `search`, with `search_type` `people`, `contacts` (default), or `employees`; it is always written as a `contacts` link |
| `update_opportunity` | PATCH one deal | The only way to move a deal's stage. At least one change |
| `backfill_opportunity_stage_history` | `POST /bulk-opportunity-stage-history` | Appends past moves. Does not move the current stage |
| `delete_opportunity` | DELETE one deal | Permanent. Confirmation when the client supports it |

Details that matter when writing:

- **Stages are names**, not ids, resolved against the instance's stage list. A `closed` stage closes
  the deal.
- **Probability does not follow the stage.** Setting a stage leaves `probability` unchanged; pass it
  explicitly.
- **One deal per call.** There is no bulk stage move.
- **Optional fields** on create and update include description, aliases, other id, classification,
  requested and allocated amount, probability, expected investment date, stage, product, primary
  contact, referral source, owner login, investor type, and waitlist id. `update_opportunity` also
  takes a new investor id, the stage effective date, and the users to notify (`add_users_to_notify`
  or `replace_users_to_notify`, not both).
- **Stage effective date** requires `stage`. A date earlier than the deal's
  `date_entered_current_stage` is rejected, because Backstop would record a history row without
  moving the deal.
- **The write is read back.** A requested stage that did not land is reported in `warnings`.
- **Not writable:** weighted values, open state, previous stage, day counts, date entered current
  stage, closed date. Backstop computes them.
- **Backfill** takes up to 15 rows of opportunity id, stage name, and effective date. A stage name
  that does not validate blocks the whole batch; a missing or unreadable opportunity fails only its
  own row. Backstop answers `201` even when rows fail, so the response reports
  each row as `applied` or `failed`. As a side effect Backstop sets the deal's `previous_stage` to the
  backfilled stage, even though the current stage does not change.
- **Custom fields** on deals are written with `update_custom_field_values`.
- **Creates are not idempotent.** Repeating `create_opportunity` makes a second deal.

## Related

- [Features overview](./README.md)
- [Activities: Who has gone quiet](./activities.md#Who-Has-Gone-Quiet)
- [Custom Fields](./custom-fields.md)
- [Tools: Opportunities](../tools.md#Opportunities)
