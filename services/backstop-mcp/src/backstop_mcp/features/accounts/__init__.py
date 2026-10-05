"""Product index, account listing, series latest-point, and holdings / time-series shapes.

`resolve_product` matches a trusted id, then a name with `filter[name][like]`, then a full
catalog walk — not one `GET /products` page.
It does not use `ResolvePartyQuery`: that path is `/quick-search`, which misses short names.
Account listing walks `/accounts` with `include=owner,investorType` (and `product` by party).
Figures are `sort=-date` (first 10 rows) then `max(date)` — not a `filter[date][ge]` window —
except `get_time_series`, which paginates the dated series.
"""

from backstop_mcp.features.accounts.api_responses import AccountApiResource
from backstop_mcp.features.accounts.dependencies import (
    get_accounts_for_product_query_factory,
    get_capital_flows_query_factory,
    get_holdings_query_factory,
    get_latest_account_values_query_factory,
    get_time_series_query_factory,
    search_products_query_factory,
)
from backstop_mcp.features.accounts.internal_dto import (
    AccountListingDto,
    AccountOwnerDto,
    AccountRecordDto,
    HoldingFigureErrorDto,
    HoldingListingDto,
    HoldingRowDto,
    InvestorTypeDto,
    MoneyDto,
    ProductCatalogFetchDto,
    ProductFetchDto,
    ProductResolution,
    ResolvedProductDto,
    ShareDto,
)
from backstop_mcp.features.accounts.queries import (
    ACCOUNT_SERIES,
    FALLBACK_OMITTED_FIELDS,
    PRODUCT_SERIES,
    GetAccountsForProductQuery,
    GetCapitalFlowsQuery,
    GetHoldingsQuery,
    GetLatestAccountValuesQuery,
    GetTimeSeriesQuery,
    HoldingsTableShapeError,
    SearchProductsQuery,
    TimeSeriesEntityType,
    TimeSeriesName,
)
from backstop_mcp.features.accounts.resolve_product import (
    resolve_product,
    resolve_product_family,
    resolve_product_query,
)
from backstop_mcp.features.accounts.responses import (
    MAX_CAPITAL_FLOW_SCAN_RECORDS,
    AccountRowResponse,
    CapitalFlowPartyResponse,
    CapitalFlowRowResponse,
    CapitalFlowsResolvedResponse,
    HoldingFigureErrorResponse,
    HoldingRowResponse,
    MoneyResponse,
    PartyAccountsResolvedResponse,
    ProductAmbiguousResponse,
    ProductDescriptionResponse,
    ProductInvestorsResolvedResponse,
    ProductRecordResponse,
    ProductResolvedResponse,
    ProductRiskFreeRateResponse,
    ShareResponse,
    TimeSeriesResolvedResponse,
)
from backstop_mcp.features.accounts.utils import raise_if_invalid_series

__all__ = [
    "ACCOUNT_SERIES",
    "AccountApiResource",
    "AccountListingDto",
    "AccountOwnerDto",
    "AccountRecordDto",
    "AccountRowResponse",
    "CapitalFlowPartyResponse",
    "CapitalFlowRowResponse",
    "CapitalFlowsResolvedResponse",
    "FALLBACK_OMITTED_FIELDS",
    "GetAccountsForProductQuery",
    "GetCapitalFlowsQuery",
    "GetHoldingsQuery",
    "GetLatestAccountValuesQuery",
    "SearchProductsQuery",
    "GetTimeSeriesQuery",
    "HoldingFigureErrorDto",
    "HoldingFigureErrorResponse",
    "HoldingListingDto",
    "HoldingRowDto",
    "HoldingRowResponse",
    "HoldingsTableShapeError",
    "InvestorTypeDto",
    "MAX_CAPITAL_FLOW_SCAN_RECORDS",
    "MoneyDto",
    "MoneyResponse",
    "PRODUCT_SERIES",
    "PartyAccountsResolvedResponse",
    "ProductAmbiguousResponse",
    "ProductCatalogFetchDto",
    "ProductFetchDto",
    "ProductInvestorsResolvedResponse",
    "ProductDescriptionResponse",
    "ProductRecordResponse",
    "ProductRiskFreeRateResponse",
    "ProductResolution",
    "ProductResolvedResponse",
    "ResolvedProductDto",
    "ShareDto",
    "ShareResponse",
    "TimeSeriesEntityType",
    "TimeSeriesName",
    "TimeSeriesResolvedResponse",
    "get_accounts_for_product_query_factory",
    "get_capital_flows_query_factory",
    "get_holdings_query_factory",
    "get_latest_account_values_query_factory",
    "search_products_query_factory",
    "get_time_series_query_factory",
    "raise_if_invalid_series",
    "resolve_product",
    "resolve_product_family",
    "resolve_product_query",
]
