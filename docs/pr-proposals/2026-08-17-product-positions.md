# PR Proposal

## Ticket
UN-23681

## Title
feat(backstop-mcp,main): add `get_product_positions` and `get_accounts_for_party`

## Description
- Add `get_product_positions` answering current balances, lifetime invested, and account status
  for a Backstop **product** (tenants may call this a fund, vehicle, or share class — that mapping
  is in the tool description, not a `fund` parameter). Lists `/accounts` with
  `filter[product.id][eq]`, defaults to open (`closedDate` key absent), and fans out `values` /
  `totalInvested` / `totalRedemptions` taking `max(date)` in a documented `filter[date][ge]`
  window — not `sort=-date` (silently ignored; default order is oldest first).
- Resolve products against a `/products?fields=name,configuration` index walked to the end 200
  rows at a page, matching on id, `productShortName`, or name, and reusing `resolution.py`.
  `/products` cannot filter on `shortName` (400) or on id, and `/quick-search` of a product name
  returns an organization whose id no account filter accepts — so the whole catalog is the
  lookup, and walking it whole is what lets `not_found` mean *absent* rather than *not on page
  one*. This instance returns 72 products, all with a `productShortName`, three duplicated
  (`PKAP`, `BLUC`, `CPOL`). Past 400 the per-call re-read stops paying for itself and a TTL cache
  becomes the answer, so that case logs `accounts.products.index_large` rather than passing
  silently.
- Return each figure as `{value, date, valueStatus?}` with the account `currency`, taking the
  latest point that carries a **value** rather than blindly the latest point: Backstop publishes
  a dated row before the number lands (its UI shows `-`), and reporting that row would turn a
  live position into "no data". When the newest row is one of those it comes back as
  `newer_point_without_value`, so a stale figure reads as stale. `valueStatus` is passed through
  when Backstop sends it (`values` is often `ESTIMATE` on the latest months) and omitted when it
  does not. Missing figures are omitted, never `0.0` — closed accounts still publish `0.0` /
  `ACTUAL` through today.
- Add `get_accounts_for_party`: `resolve_party` then a full `/accounts?include=owner,product`
  walk filtered by `owner.id` (org owners share the organization id). Listing + status + product
  only — no series fan-out. ACCOUNT quick-search is not used (name match, not ownership).
- Include product assets under management (AUM — the product's total reported value, not one
  investor's balance) from `/products/{id}/aums`, and publish `balance_total` and
  `aum_difference` next to it. `aum_diverges` is a 0.5%-of-AUM tolerance verdict, not an
  equality test: the two are as-of different dates, the open default excludes
  closed-but-still-valued accounts, and balances are summed across currencies without
  conversion, so a cent-exact comparison would flag every real product and carry no information.
- Cap the series fan-out at 500 accounts per call and publish `accounts_omitted`. The per-user
  concurrency gate queues a large fan-out but does not bound it — 500 accounts is already ~1500
  queued requests.
- Take the owner id from `specificResource.resourceId` whenever the type comes from the same
  reference. An organization owner arrives as a `contacts` resource; keeping the envelope id
  while reporting `resourceType: organizations` would echo back an id that does not exist in the
  collection named — and every description tells the model to reuse that id as `party_id`. The
  by-party filter matches the `owner` linkage id first, then the projected owner id.

## Also in this PR (beyond UN-23681)

- **Breaking:** `get_opportunities` and `get_activity_history` take `search_type` instead of
  `party_type` + optional `search_type`. Two overlapping party-kind parameters meant the model
  had to keep them consistent and a validator had to reject the combinations that were not; one
  parameter, worded identically across all four party tools, removes both. `search_type_for`,
  `segment_for`, and the cross-field validator are gone. We are pre-1.0 and experimental, so
  this lands as a change rather than a deprecation.
- `IncludedResource` / `included_resource` added to `backstop_client.json_api`: the parsed shape
  of one `included` entry, keeping the resource id and tolerating the `"relationships": null`
  Backstop sends on some side-loads. `follow_included` handed back raw dicts and every caller
  re-parsed them.
- `unresolved_response` is now generic over the ambiguous model, so a subsystem that subclasses
  `AmbiguousResponse` to reword its schema gets that subclass back rather than the base.
