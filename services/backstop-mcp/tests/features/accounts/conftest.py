from collections.abc import AsyncGenerator

import pytest

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.accounts import (
    GetAccountsForProductQuery,
    GetCapitalFlowsQuery,
    GetHoldingsQuery,
    GetProductQuery,
    GetTimeSeriesQuery,
)
from tests.helpers import client_factory, credential


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def make_get_holdings_query(client: BackstopClient) -> GetHoldingsQuery:
    return GetHoldingsQuery(client=client)


def make_get_accounts_for_product_query(client: BackstopClient) -> GetAccountsForProductQuery:
    return GetAccountsForProductQuery(client=client)


def make_get_capital_flows_query(client: BackstopClient) -> GetCapitalFlowsQuery:
    return GetCapitalFlowsQuery(client=client)


def make_get_product_query(client: BackstopClient) -> GetProductQuery:
    return GetProductQuery(client=client)


def make_get_time_series_query(client: BackstopClient) -> GetTimeSeriesQuery:
    return GetTimeSeriesQuery(client=client)
