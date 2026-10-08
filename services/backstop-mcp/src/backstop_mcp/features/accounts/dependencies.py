from functools import lru_cache

from fastmcp.dependencies import Depends

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import (
    get_backstop_client_for_current_caller,
    get_product_investors_config,
)
from backstop_mcp.features.accounts.queries import (
    GetAccountsForProductQuery,
    GetCapitalFlowsQuery,
    GetHoldingsQuery,
    GetLatestAccountValuesQuery,
    GetProductInvestorsQuery,
    GetTimeSeriesQuery,
    SearchProductsQuery,
)


@lru_cache(maxsize=1)
def get_holdings_query_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
) -> GetHoldingsQuery:
    return GetHoldingsQuery(client=client)


@lru_cache(maxsize=1)
def get_accounts_for_product_query_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
) -> GetAccountsForProductQuery:
    return GetAccountsForProductQuery(client=client)


@lru_cache(maxsize=1)
def get_capital_flows_query_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
) -> GetCapitalFlowsQuery:
    return GetCapitalFlowsQuery(client=client)


@lru_cache(maxsize=1)
def search_products_query_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
) -> SearchProductsQuery:
    return SearchProductsQuery(client=client)


@lru_cache(maxsize=1)
def get_time_series_query_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
) -> GetTimeSeriesQuery:
    return GetTimeSeriesQuery(client=client)


@lru_cache(maxsize=1)
def get_latest_account_values_query_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
) -> GetLatestAccountValuesQuery:
    return GetLatestAccountValuesQuery(client=client)


@lru_cache(maxsize=1)
def get_product_investors_query_factory(
    get_accounts_for_product_query: GetAccountsForProductQuery = Depends(
        get_accounts_for_product_query_factory
    ),
    get_latest_account_values_query: GetLatestAccountValuesQuery = Depends(
        get_latest_account_values_query_factory
    ),
) -> GetProductInvestorsQuery:
    # Config is read here rather than taken as a `Depends`: settings are unhashable, and this
    # factory is `lru_cache`d.
    return GetProductInvestorsQuery(
        get_accounts_for_product_query=get_accounts_for_product_query,
        get_latest_account_values_query=get_latest_account_values_query,
        max_valued_accounts=get_product_investors_config().max_valued_accounts,
    )
