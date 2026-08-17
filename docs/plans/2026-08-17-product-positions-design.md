# Design: `get_product_positions` and `get_accounts_for_party`

**Ticket:** UN-23681

Backstop names on the wire (`product`, `account`, `owner`). Tenants call products funds, vehicles,
share classes, or other names — that mapping lives in tool descriptions and server instructions,
not in parameter aliases.

## Problem

An IR team member checking numbers before an investor meeting needs two answers:

1. **By product** — for a given Backstop product (what many firms call a fund): each account's
   current balance, lifetime invested, lifetime redeemed, and account status.
2. **By party** — which accounts a given organization or person owns, across products.

Today neither is reachable through the MCP server.

The correctness risk is higher than for record-shaped read tools. Monetary figures are **time
series, not fields on the account**. Picking the wrong series or the wrong point hands a
confidently wrong number into a meeting. Live responses on this instance make that concrete:

- Latest `values` points are often `valueStatus: "ESTIMATE"` (e.g. Jul/Aug 2026) on top of
  `ACTUAL` month-ends.
- `totalInvested`, `totalRedemptions`, and product `aums` usually have **no** `valueStatus`.
- Closed accounts keep a `values` series through today at `0.0` / `ACTUAL`. Treating missing as
  zero, or including closed by default, looks like a live empty position.
- Latest `returns` points often omit `value` entirely (the UI shows `-`). Out of scope here; the
  same "latest ≠ usable" trap.

"By product" has a real filter: `GET /accounts?filter[product.id][eq]=…` (also
`product.shortName`). That is Backstop's model, not a Capstone customisation: a **product** is the
investment product; an **account** is one party's position in that product; **owner** is the party
on that account.

"By party" does **not** have a filter. Organizations and contacts have no `/accounts`
subcollection (`404`). `filter[owner]` / `filter[owner.id]` return `400`. ACCOUNT `quick-search`
matches account **name**, not owner, so it misses a differently named vehicle and false-positives
on name collisions. The complete path is: resolve the party, walk `/accounts?include=owner,…`,
keep `owner.id == party.id`. Org owners use the polymorphic `contacts` view; the contact id
equals the organization id (`specificResource.resourceType: "organizations"`).

## Solution

### Overview

Two tools, one shared account-fetch module. The LLM does **not** pass dates. "Current" means the
latest point Backstop has; each figure is returned with that point's date (and `valueStatus` when
Backstop sends it).

**`get_product_positions`** resolves a product against a one-request index
(`GET /products?fields=name,configuration&page[limit]=200`), lists that product's accounts with
`GET /accounts?filter[product.id][eq]={id}&include=owner,investorType`, defaults to open
(`closedDate` key absent), then fans out three series per open account:

- current balance → `values`
- invested amount → `totalInvested` (lifetime cumulative)
- redemptions → `totalRedemptions` (lifetime cumulative)

Each series is `GET /accounts/{id}/{series}?filter[date][ge]={cutoff}&page[limit]=100`, taking
`max(date)` client-side. A fourth call, `GET /products/{id}/aums` with the same window, is the
product AUM; the sum of returned balances is compared against it and a flag is set on divergence.

Product matching is local: `product_id`, then `productShortName`, then name (exact before
substring). `/products` cannot filter on `shortName` (`400`). `/quick-search` of a product name as
`ORGANIZATION` returns a CRM organization whose id no account filter accepts. Duplicate
`productShortName`s (`BLUC`, `CPOL`, `PKAP` on this instance) go through `Ambiguous` →
`elicit_choice`.

**`get_accounts_for_party`** reuses `resolve_party` (same as `get_opportunities`). It walks
`GET /accounts?include=owner,investorType,product` with `paginate_all()`, keeps rows whose
`owner.id` equals the resolved party id, and defaults to open. **No series fan-out.** Each row is
the same account+status shape the product tool uses before attaching figures, plus the product
`{id, name, short_name}` from the include.

Typical calls:

```json
{ "name": "get_product_positions", "arguments": { "product": "CGUP" } }
{ "name": "get_product_positions", "arguments": { "product_id": "1292283" } }
{ "name": "get_accounts_for_party", "arguments": { "party_type": "organization", "search": "PSP Investments" } }
{ "name": "get_accounts_for_party", "arguments": { "party_type": "organization", "party_id": "341688185" } }
```

Portable: no hardcoded product ids or short names. Entry point is polymorphic `/accounts`, so a
tenant with private-equity accounts still appears there without a second code path.

### Architecture

```
features/accounts/
  product.py      # one-request product index + match
  fetch.py        # account listing (by product, or full walk)
  latest.py       # latest point from a dated window
  project.py      # owner / investorType / product → small models
  types.py
  responses.py    # shared account row; figures only on the product tool
server/tools/get_product_positions.py
server/tools/get_accounts_for_party.py
```

**`get_product_positions`**

1. `GET /products?fields=name,configuration&page[limit]=200` — match `product_id` then
   `productShortName` then name. `Ambiguous` / `NotFound` via `resolution.py`.
2. `GET /accounts?filter[product.id][eq]={id}&include=owner,investorType` — `paginate_all()`.
   Open = `closedDate` key absent. `include_closed` (default false) keeps the rest.
3. Per open account, three calls: `GET /accounts/{id}/{values|totalInvested|totalRedemptions}`
   with `filter[date][ge]={cutoff}&page[limit]=100`, `max(date)` in `latest.py`. Default lookback
   90 days; widen once; then paginate. Existing per-user gate (`max_concurrent_requests_per_user:
   5`) queues the fan-out. This uses documented `filter[date]` rather than undocumented
   `sort=-date&page[limit]=1`.
4. `GET /products/{id}/aums` with the same window — latest AUM vs sum of returned balances.

**`get_accounts_for_party`**

1. `resolve_party` (trusted `party_id` or `search`, same as `get_opportunities`).
2. `GET /accounts?include=owner,investorType,product` — full walk.
3. Keep `owner.id == party.id`. Same open default. No series fan-out.

**Shared row.** Account id and name, owner `{id, name, resource_type}`, investor type, `currency`,
status bundle from UN-23681: `accountStartDate`, `closedDate`, `ownershipType`,
`investorQualification`, `isEmployeeAccount`, `isGpAccount`, `amlCheckComplete`,
`newIssueEligible`, `usDomiciled`. Product tool adds each figure as `{value, date, valueStatus?}`
(status omitted when Backstop omits it) and product AUM. Party tool adds product
`{id, name, short_name}`.

Each series carries **its own** date. Collapsing them into one as-of would fabricate a number.

Owner is projected like `features/includes/` (identity only), not the contact custom-field dump.
Unbounded series are never asked for via `include=`. Naming (product ≈ fund / vehicle / share
class) lives in tool descriptions and server instructions. `describe_data_model` may move into
those; do not depend on it. If it remains, a row is nice-to-have.

Reuse: `resolution.py` / `elicit_choice`, `paginate_all()`, `OmitNoneModel` /
`published_output_schema`, `party_resolver`, existing 429 retry.

### Error Handling

**Product resolve** reuses `resolution.py`: nothing matches → `NotFound` (query + scope
`products`); several matches → `Ambiguous` → `elicit_choice`. Client cannot elicit → same
structured ambiguous payload as party tools.

**Party resolve** is `resolve_party` unchanged: never invent a `party_id`.

**Three empty outcomes stay distinct** — a bare `[]` looks like "this product has no investors":

- product does not exist → `NotFound`
- product exists, zero accounts
- product exists, accounts exist, none open (this instance: DHFI, 46 closed). The response says
  so and points at `include_closed`.

Same split on the party tool: party not found vs party with no accounts vs only closed accounts.

**Missing figures are omitted, never zeroed.** No points in a series → absent field plus a
reason, not `0.0`. Closed accounts still publish `values` of `0.0` / `ACTUAL` through today;
that zero is real only when the account is in the result set.

**Estimates and absent status.** `valueStatus` is passed through when Backstop sends it and
omitted when it does not. We do not invent `ACTUAL`.

**Partial fan-out.** One account's series erroring must not drop the other rows. Per-account
error sits on that row. This API does return 500s on some bad filters (`filter[id][eq]` on
`/accounts`); we do not use those.

**Rate limits.** No new limiter. Backstop caps ~5 concurrent connections per token; the existing
gate plus `retry.py` on 429 / `Retry-After` already queues the fan-out. The party tool's walk is
sequential pagination, not a burst.

**Reconciliation.** AUM vs sum of returned balances: divergence is a flag, not a hard failure.
Closed-but-still-valued accounts excluded by the open default are the usual cause.

### Testing Strategy

Behavioural tests against recorded fixtures, same pattern as `tests/features/opportunities/` and
`tests/features/includes/`. No live Backstop in CI. `latest.py` is a pure function over a parsed
page, so it is unit-tested without the HTTP client.

- Latest-point selection with irregular dates (a mid-month point between month-ends) — `max(date)`,
  not "last of month."
- Empty 90-day window → widen once → then paginate.
- `values` with `valueStatus: "ESTIMATE"` on the newest row; older rows `ACTUAL`.
- `totalInvested` / `aums` with no `valueStatus` — field omitted, not defaulted to `ACTUAL`.
- Missing series → field absent, never `0.0`.
- `closedDate` **absent** → open; present → closed (including a closed account whose latest
  `values` is `0.0` / `ACTUAL`).
- All-closed product → distinguishable payload, `include_closed` mentioned, not `[]`.
- Product with zero accounts vs `NotFound` vs all-closed.
- Exact id, exact `productShortName`, exact name, then substring; ambiguous name and duplicate
  short name → `Ambiguous`; no match → `NotFound`.
- Party accounts: `owner.id` equals resolved org id; account name ≠ owner name still matches on
  owner id, not name; a name that would false-positive ACCOUNT quick-search must not appear unless
  owner matches.
- One series 500 → that row carries the error; siblings succeed.
- Reconciliation flag when summed balances ≠ latest AUM.
- Owner projection is `{id, name, resource_type}`, not the contact custom-field dump.

## Out of Scope

- **Any write** (subscriptions, redemptions, transfers).
- **Date range / `as_of`.** "Current" is the latest point. Historical "balance on date D" is a
  later parameter.
- **Performance (`returns` / `irrs` / `analytics`).** Latest `returns` points often omit `value`.
- **`subscriptionAmounts` / `redemptionAmounts`.** Per-period flows, not lifetime totals, and
  only on `/hedge-fund-accounts/{id}/` (19-name series vs the polymorphic 17). The ticket's
  invested amount is `totalInvested`. Not enough information to add these now.
- **Asset-class-specific families** as the entry point (`/hedge-fund-accounts`,
  `/private-equity-accounts`, `/managed-accounts`, `/legacy-private-equity-accounts`). The
  account **rows** are already on `/accounts` (same id; `specificResource` names the typed view).
  Typed URLs add extras (period flows, transaction collections, side pockets) we are not taking.
  This instance is all hedge-fund; another tenant's PE accounts still appear on `/accounts`.
- **`/funds`, `/investment-vehicles`.** Empty on this instance; products are the catalog.
- **`percentageOfFundHistory`.** Cheap, not requested.
- **Side-loading time series via `include=`.** Accepted but untrimmable; cannot restrict to open
  accounts (`closedDate` does not filter). Fan-out is smaller and faster.
- **`/reports`.** Needs a Report Builder report per instance; not portable.
- **ACCOUNT `quick-search` as ownership.** Name match, not `owner.id`.
- **Account/product custom-field values on these tools.** `list_custom_fields` already covers the
  catalog.
- **`fund` parameter alias.** Backstop name is `product`.
- **Series fan-out on `get_accounts_for_party`.** Listing + status + product only.
- **Hardcoded product ids, short names, or tenant-only branches.**
- **Depending on `describe_data_model`.** Naming lives in tool descriptions and server
  instructions.

## Tasks

1. **Add the product index and resolver** — Fetch all products in one request with
   `fields=name,configuration`, match caller input against id / `productShortName` / name, and
   return `Resolved` / `Ambiguous` / `NotFound` via `resolution.py`.

2. **Add shared account listing and projections** — `paginate_all()` on `/accounts` with
   `include=owner,investorType` (and `product` when listing by party), split open from closed on
   `closedDate` key absence, and project owner / investor type / product onto small models.

3. **Add latest-point selection over a date window** — Fetch a series with `filter[date][ge]`,
   select `max(date)` client-side, and widen then paginate when the window is empty. Pure
   function over a parsed response.

4. **Fan out the three series per open account** — Compose listing with latest-point selection
   for `values`, `totalInvested`, and `totalRedemptions`. Let the existing per-user concurrency
   gate queue the requests, and collect per-account failures instead of aborting the call.

5. **Add product AUM and the reconciliation check** — Fetch `/products/{id}/aums`, take its
   latest point, compare against the sum of returned balances, and set a flag on divergence.

6. **Register `get_product_positions`** — Product resolve + filtered listing + series fan-out +
   AUM. Distinguish the three empty outcomes. Document Backstop `product` naming and tenant
   synonyms (fund, vehicle, share class) in the tool description. Document the series mapping
   (`values` / `totalInvested` / `totalRedemptions`) there too, per UN-23681.

7. **Register `get_accounts_for_party`** — `resolve_party`, full `/accounts` walk, filter by
   `owner.id`, same open default, no series fan-out. Same description convention for product
   naming.

8. **Add behavioural tests** — Cover the cases listed under Testing Strategy against recorded
   fixtures.
