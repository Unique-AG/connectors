"""Product index, account listing, series latest-point, and the two positions tools' shapes.

`resolve_product` matches id, `productShortName`, and name against one `GET /products` page.
It does not use `resolve_party`: that path is `/quick-search`, which misses short names.
Account listing walks `/accounts` with `include=owner,investorType` (and `product` by party).
Figures are `sort=-date` (first 10 rows) then `max(date)` — not a `filter[date][ge]` window.
"""

from backstop_mcp.features.accounts.fetch import (
    fetch_accounts_for_party,
    fetch_accounts_for_product,
)
from backstop_mcp.features.accounts.positions import fetch_product_positions
from backstop_mcp.features.accounts.product import resolve_product
from backstop_mcp.features.accounts.responses import (
    AccountRowResponse,
    PartyAccountsResolvedResponse,
    ProductAmbiguousResponse,
    ProductPositionsResolvedResponse,
    account_row_response,
    party_accounts_response,
    product_positions_response,
    unresolved_product_response,
)
from backstop_mcp.features.accounts.types import (
    AccountListing,
    AccountOwner,
    AccountRecord,
    InvestorType,
    ProductCandidate,
    ProductResolution,
    ResolvedProduct,
)

__all__ = [
    "AccountListing",
    "AccountOwner",
    "AccountRecord",
    "AccountRowResponse",
    "InvestorType",
    "PartyAccountsResolvedResponse",
    "ProductAmbiguousResponse",
    "ProductCandidate",
    "ProductPositionsResolvedResponse",
    "ProductResolution",
    "ResolvedProduct",
    "account_row_response",
    "fetch_accounts_for_party",
    "fetch_accounts_for_product",
    "fetch_product_positions",
    "party_accounts_response",
    "product_positions_response",
    "resolve_product",
    "unresolved_product_response",
]
