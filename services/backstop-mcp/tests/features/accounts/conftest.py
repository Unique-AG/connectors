from collections.abc import AsyncGenerator
from datetime import date

import pytest

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.accounts import (
    GetAccountsForProductQuery,
    GetCapitalFlowsQuery,
    GetHoldingsQuery,
    GetLatestAccountValuesQuery,
    GetProductInvestorsQuery,
    GetTimeSeriesQuery,
    SearchProductsQuery,
)
from tests.helpers import client_factory, credential

# Tenure `years` are measured up to today, so the factories pin it.
TODAY = date(2026, 10, 8)


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def make_get_holdings_query(client: BackstopClient) -> GetHoldingsQuery:
    return GetHoldingsQuery(client=client, clock=lambda: TODAY)


def make_get_accounts_for_product_query(client: BackstopClient) -> GetAccountsForProductQuery:
    return GetAccountsForProductQuery(client=client)


def make_get_latest_account_values_query(client: BackstopClient) -> GetLatestAccountValuesQuery:
    return GetLatestAccountValuesQuery(client=client)


def make_get_product_investors_query(
    client: BackstopClient, *, max_valued_accounts: int = 50
) -> GetProductInvestorsQuery:
    return GetProductInvestorsQuery(
        get_accounts_for_product_query=make_get_accounts_for_product_query(client),
        get_latest_account_values_query=make_get_latest_account_values_query(client),
        max_valued_accounts=max_valued_accounts,
        clock=lambda: TODAY,
    )


def make_get_capital_flows_query(client: BackstopClient) -> GetCapitalFlowsQuery:
    return GetCapitalFlowsQuery(client=client)


def make_search_products_query(client: BackstopClient) -> SearchProductsQuery:
    return SearchProductsQuery(client=client)


def make_get_time_series_query(client: BackstopClient) -> GetTimeSeriesQuery:
    return GetTimeSeriesQuery(client=client)
