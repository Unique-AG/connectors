"""Product index, `resolve_product`, and shared account listing for positions.

`resolve_product` matches id, `productShortName`, and name against one `GET /products` page.
It does not use `resolve_party`: that path is `/quick-search`, which misses short names.
Account listing walks `/accounts` with `include=owner,investorType` (and `product` by party).
"""

from backstop_mcp.features.accounts.fetch import (
    fetch_accounts_for_party,
    fetch_accounts_for_product,
)
from backstop_mcp.features.accounts.product import resolve_product
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
    "InvestorType",
    "ProductCandidate",
    "ProductResolution",
    "ResolvedProduct",
    "fetch_accounts_for_party",
    "fetch_accounts_for_product",
    "resolve_product",
]
