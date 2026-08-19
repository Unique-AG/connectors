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
from backstop_mcp.features.accounts.internal_dto import (
    AccountListingDto,
    AccountOwnerDto,
    AccountRecordDto,
    InvestorTypeDto,
    ProductCandidate,
    ProductResolution,
    ResolvedProductDto,
)
from backstop_mcp.features.accounts.positions import fetch_product_positions
from backstop_mcp.features.accounts.product import resolve_product
from backstop_mcp.features.accounts.responses import (
    AccountRowResponse,
    PartyAccountsResolvedResponse,
    ProductAmbiguousResponse,
    ProductPositionsResolvedResponse,
)

__all__ = [
    "AccountListingDto",
    "AccountOwnerDto",
    "AccountRecordDto",
    "AccountRowResponse",
    "InvestorTypeDto",
    "PartyAccountsResolvedResponse",
    "ProductAmbiguousResponse",
    "ProductCandidate",
    "ProductPositionsResolvedResponse",
    "ProductResolution",
    "ResolvedProductDto",
    "fetch_accounts_for_party",
    "fetch_accounts_for_product",
    "fetch_product_positions",
    "resolve_product",
]
