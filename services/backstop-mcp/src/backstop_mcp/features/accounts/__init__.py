"""Product index, account listing, series latest-point, and holdings / time-series shapes.

`resolve_product` matches id, `productShortName`, and name against one `GET /products` page.
It does not use `resolve_party`: that path is `/quick-search`, which misses short names.
Account listing walks `/accounts` with `include=owner,investorType` (and `product` by party).
Figures are `sort=-date` (first 10 rows) then `max(date)` — not a `filter[date][ge]` window —
except `get_time_series`, which paginates the dated series.
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
from backstop_mcp.features.accounts.fetch_time_series import (
    fetch_time_series,
    require_series_for_entity,
)
from backstop_mcp.features.accounts.internal_dto import (
    ACCOUNT_SERIES,
    PRODUCT_SERIES,
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
    ProductResolution,
    ResolvedProductDto,
    ShareDto,
    TimeSeriesEntityType,
    TimeSeriesName,
)
from backstop_mcp.features.accounts.resolve_product import resolve_product, resolve_product_query
from backstop_mcp.features.accounts.responses import (
    AccountRowResponse,
    HoldingFigureErrorResponse,
    HoldingRowResponse,
    MoneyResponse,
    PartyAccountsResolvedResponse,
    ProductAmbiguousResponse,
    ProductInvestorsResolvedResponse,
    ShareResponse,
    TimeSeriesResolvedResponse,
)
from backstop_mcp.features.accounts.split_open import split_open

__all__ = [
    "ACCOUNT_SERIES",
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
    "MoneyDto",
    "MoneyResponse",
    "PRODUCT_SERIES",
    "PartyAccountsResolvedResponse",
    "ProductAmbiguousResponse",
    "ProductCandidate",
    "ProductInvestorsResolvedResponse",
    "ProductResolution",
    "ResolvedProductDto",
    "ShareDto",
    "ShareResponse",
    "TimeSeriesEntityType",
    "TimeSeriesName",
    "TimeSeriesResolvedResponse",
    "fetch_accounts_for_party",
    "fetch_accounts_for_product",
    "fetch_holdings",
    "fetch_holdings_table",
    "fetch_time_series",
    "require_series_for_entity",
    "resolve_product",
    "resolve_product_query",
    "split_open",
]
