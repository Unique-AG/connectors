from collections.abc import AsyncGenerator

import pytest

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.reports import RunReportQuery
from tests.helpers import client_factory, credential


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def make_run_report_query(client: BackstopClient) -> RunReportQuery:
    return RunReportQuery(client=client)
