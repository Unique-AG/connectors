<!-- confluence-page-id: tobefilled -->
<!-- confluence-space-key: PUBDOC -->

## Overview

Backstop's fund side: **products** (funds, vehicles, share classes), **accounts** (one owner's
position in one product), dated **time series** on accounts and products, and **capital flows**
(subscriptions and redemptions). Everything in this area is read-only.

Code: [`features/accounts`](https://github.com/Unique-AG/connectors/tree/main/services/backstop-mcp/src/backstop_mcp/features/accounts).

| Question | Tool |
|---|---|
| Which products exist, and their type, onshore flag, or custom fields | `search_products` |
| What a person or organization holds, and for how long | `get_accounts_for_party` |
| Who holds a product, how much, and for how long | `get_product_investors` |
| A dated figure: a balance on a date, a NAV history, a fund's assets under management | `get_time_series` |
| Subscriptions, redemptions, or an investor's share class | `get_capital_flows` |

## Finding Products

`search_products` returns **every** product matching all the filters given, with its custom-field
values. With no filters it returns the whole catalog, sorted by name.

| Filter | Where it runs |
|---|---|
| `modified_since` | Sent to Backstop; applied by the server when `product_ids` is given |
| `product_ids` | Sent to Backstop (read by id instead of the catalog) |
| `name` (name or short name), `product_type`, `is_onshore`, `custom_fields` | Applied by the server, after reading the catalog. Backstop rejects these as filters |

Within one filter several values are OR; across filters everything must hold. An exact short name wins
over a longer name that contains it. `custom_field_names` only trims which custom-field values each
product returns; it does not filter products. Product custom fields are only available here; the
definitions are on `list_custom_fields`.

Other tools that take a product (`get_product_investors`) resolve it the same way: an id is read
directly, and a name is matched over the whole catalog, because Backstop's quick search does not find
short names. A partial name matches every vehicle containing it, up to 6; more than that asks the user
to choose. An exact name, short name, or id is one vehicle.

## A Party's Holdings

`get_accounts_for_party` returns the accounts a person or organization owns across products. Each row
has the account and product ids, tenure dates, and snapshot figures: `balance`, `commitment`,
`unfunded_commitment`, and share of product and of master.

Two Backstop sources can answer, and the response says which in `source` and `data_caveat`:

| Source | Used | Knows |
|---|---|---|
| Backstop's UI account table (`/bsg-account-table-data`) | First. One request with all figures | Balance with no as-of date and no actual/estimate label. Undocumented by Backstop |
| The documented `/accounts` walk plus two series requests per account | When the first fails (any error except authentication or rate limiting, including a timeout, an unreadable body, or inconsistent counts) | Dated figures, but not commitment, unfunded commitment, share of master, account term, or other id; those are listed in `omitted_fields` and never shown as zero |

- **Tenure** is `tenure_runs`: unbroken stretches of ownership merged across all of the party's
  accounts, closed ones included, longest first. A run without an end is still held. An account's
  start date is not tenure; investors who rotate accounts have no single old account.
- **Closed accounts** are hidden unless `include_closed=true`. An empty list with `closed_omitted > 0`
  means every account is closed, not that the party owns nothing.
- **An empty table for an id that was never confirmed** is checked: the UI table answers the same way
  for a party that owns nothing and for a wrong id, so the server verifies the party before reporting
  "owns nothing".
- A figure with `formatted: "-"` and amount `0.0` means nothing is recorded. `figure_errors` tells a
  failed request apart from "Backstop publishes no number".

## A Product's Investors

`get_product_investors` takes 1 to 25 products and returns two views of the same accounts:

- `products`: one listing per vehicle, with its accounts and owners.
- `investors`: one entry per owner across all the vehicles, with a holding per vehicle,
  `has_open_account`, and `tenure_runs`.

Plus `longest_tenure_runs` and `longest_held_today`, which rank investors by their longest unbroken
run.

- **No figures by default.** `include_latest_value=true` fetches each account's latest `values` point
  and totals per holding and per investor, summed per currency (currencies are never mixed). Each
  account is one request, so this is capped at `PRODUCT_INVESTORS_MAX_VALUED_ACCOUNTS` (100 in the
  app, 150 in the chart). Above the cap no values are fetched and `latest_value_hint` says how to
  narrow, for example with `investor_ids`. Ids in `investor_ids` with no account, open or closed, in
  these products are listed in `investor_ids_not_found`.
- Investors who have left are included with `has_open_account: false`. Their closed accounts need
  `include_closed=true`.
- An investor's `resource_type` can be `contacts` even when the owner is an organization; echo its id
  and type together into a later lookup.

## Dated Figures

`get_time_series` returns the points of one series on one account or one product, newest first, with
an optional inclusive date window (a start after the end is rejected). A product can be given by id,
short name, or name. It is the only source of a dated, status-labelled figure.

| Entity | Series |
|---|---|
| `accounts` | `values` (the balance), `startingValues`, `totalInvested`, `totalRedemptions`, `earnings`, `grossValues`, `returns`, `irrs`, `currentMonthIrrs`, `currentMonthNetAssests` (Backstop's spelling), `highwaterMarks`, `managementFees`, `incentiveFees`, `incentiveFeesCharged`, `performanceFeeAccrued`, `newIssueIncomes`, `percentageOfFundHistory` |
| `products` | `aums` (assets under management), `benchmarkAReturns` to `benchmarkHReturns`, `expenseDataPoints`, `incomeDataPoints` |

- A point with no value is "not in yet"; Backstop's UI shows `-`. A published `0.0` is a real zero.
- `valueStatus` on accounts and `source` on product `aums` are passed through when Backstop sends
  them.
- One series per call. Backstop has no bulk time-series endpoint.
- A fund-level total is the product's `aums`, not a sum over accounts.

## Subscriptions and Redemptions

`get_capital_flows` requires `start_date` and `end_date`; Backstop refuses an unfiltered read. It
walks the subscriptions and redemptions collections for the window and returns each flow with kind,
amount, transaction and notice dates, account, owner, `share_class`, `share_series`, and whether it
was liquidating.

- **Completed flows only.** `non_actual_count` reports how many other rows were excluded.
- **Redemptions are attributed through their original subscription**, because a redemption has no
  account of its own. When that link is missing the row is kept and marked `unattributed`, unless
  `account_ids` or `owner_id` is given; then it drops out.
- **`owner_id`** keeps flows whose `owner.id` matches. Take it from a prior capital-flows row; it is
  not necessarily the party id from `get_accounts_for_party`.
- **Rows carry no product.** To answer "which share class is X in for fund Y", take the party's
  account ids from `get_accounts_for_party` or `get_product_investors` and pass them as `account_ids`.
  The share class is on the original subscription, so the window must include its date.
- **Each walk stops at 10,000 rows**, reported as `scan_truncated`. `request_count` says how many
  requests the call made.
- There is no cursor; every match in the window is returned.

## Related

- [Features overview](./README.md)
- [Custom Fields](./custom-fields.md)
- [Reports and Links](./reports-and-links.md) (account and product links)
- [Tools: Products and Accounts](../tools.md#Products-and-Accounts)
