"""Product index, account listing, series latest-point, and the two positions tools' shapes.

`resolve_product` matches id, `productShortName`, and name against one `GET /products` page.
It does not use `resolve_party`: that path is `/quick-search`, which misses short names.
Account listing walks `/accounts` with `include=owner,investorType` (and `product` by party).
Figures are `sort=-date` (first 10 rows) then `max(date)` — not a `filter[date][ge]` window.
"""

from backstop_mcp.features.accounts.api_responses import AccountApiResponse
from backstop_mcp.features.accounts.fetch_accounts_for_party import fetch_accounts_for_party
from backstop_mcp.features.accounts.fetch_accounts_for_product import fetch_accounts_for_product
from backstop_mcp.features.accounts.fetch_holdings import (
    FALLBACK_OMITTED_FIELDS,
    fetch_holdings,
)
from backstop_mcp.features.accounts.fetch_holdings_table import (
    HoldingsTableShapeError,
    fetch_holdings_table,
)
from backstop_mcp.features.accounts.fetch_product_positions import (
    MAX_POSITION_ACCOUNTS,
    fetch_product_positions,
)
from backstop_mcp.features.accounts.internal_dto import (
    AccountListingDto,
    AccountOwnerDto,
    AccountRecordDto,
    HoldingFigureErrorDto,
    HoldingListingDto,
    HoldingRowDto,
    HoldingsSource,
    InvestorTypeDto,
    MoneyDto,
    ProductCandidate,
    ProductPositionsDto,
    ProductResolution,
    ResolvedProductDto,
    ShareDto,
)
from backstop_mcp.features.accounts.resolve_product import resolve_product
from backstop_mcp.features.accounts.responses import (
    AccountRowResponse,
    HoldingFigureErrorResponse,
    HoldingRowResponse,
    MoneyResponse,
    PartyAccountsResolvedResponse,
    ProductAmbiguousResponse,
    ProductPositionsResolvedResponse,
    ShareResponse,
)
from backstop_mcp.features.accounts.split_open import split_open

__all__ = [
    "AccountApiResponse",
    "AccountListingDto",
    "AccountOwnerDto",
    "AccountRecordDto",
    "AccountRowResponse",
    "FALLBACK_OMITTED_FIELDS",
    "HoldingFigureErrorDto",
    "HoldingFigureErrorResponse",
    "HoldingListingDto",
    "HoldingRowDto",
    "HoldingRowResponse",
    "HoldingsSource",
    "HoldingsTableShapeError",
    "InvestorTypeDto",
    "MAX_POSITION_ACCOUNTS",
    "MoneyDto",
    "MoneyResponse",
    "PartyAccountsResolvedResponse",
    "ProductAmbiguousResponse",
    "ProductCandidate",
    "ProductPositionsDto",
    "ProductPositionsResolvedResponse",
    "ProductResolution",
    "ResolvedProductDto",
    "ShareDto",
    "ShareResponse",
    "fetch_accounts_for_party",
    "fetch_accounts_for_product",
    "fetch_holdings",
    "fetch_holdings_table",
    "fetch_product_positions",
    "resolve_product",
    "split_open",
]
