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
  `totalInvested` / `totalRedemptions` taking `max(date)` in a documented date window.
- Resolve products against a single-request index (`/products?fields=name,configuration`), matching
  on id, `productShortName`, or name, and reusing `resolution.py`. `/products` cannot filter on
  `shortName`; `/quick-search` of a product name returns an organization whose id no account
  filter accepts.
- Return each figure as `{value, date, valueStatus?}` with the account `currency`. `valueStatus`
  is passed through when Backstop sends it (`values` is often `ESTIMATE` on the latest months)
  and omitted when it does not. Missing figures are omitted, never `0.0` — closed accounts still
  publish `0.0` / `ACTUAL` through today.
- Add `get_accounts_for_party`: `resolve_party` then a full `/accounts?include=owner,product`
  walk filtered by `owner.id` (org owners share the organization id). Listing + status + product
  only — no series fan-out. ACCOUNT quick-search is not used (name match, not ownership).
- Include product AUM from `/products/{id}/aums` on the product tool and flag divergence from
  the sum of returned balances. Distinguish "no accounts" from "all closed" instead of returning
  a bare empty list.
