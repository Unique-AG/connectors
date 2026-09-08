from functools import lru_cache

from fastmcp.dependencies import Depends

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client_for_current_caller
from backstop_mcp.features.accounts.queries import (
    GetAccountsForProductQuery,
    GetCapitalFlowsQuery,
    GetHoldingsQuery,
    GetProductQuery,
    GetTimeSeriesQuery,
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
def get_product_query_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
) -> GetProductQuery:
    return GetProductQuery(client=client)


@lru_cache(maxsize=1)
def get_time_series_query_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
) -> GetTimeSeriesQuery:
    return GetTimeSeriesQuery(client=client)
