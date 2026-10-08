from collections.abc import AsyncGenerator

import pytest

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.reports import ReportRunCache, RunReportQuery
from backstop_mcp.features.reports.queries import REPORT_RUN_CACHE_SIZE, REPORT_RUN_TTL_SECONDS
from backstop_mcp.features.reports.queries.run_report_query import REPORT_WAIT_SECONDS
from tests.helpers import client_factory, credential


@pytest.fixture
async def client() -> AsyncGenerator[BackstopClient]:
    factory = client_factory()
    yield factory.for_credential(credential())
    await factory.aclose()


def make_run_report_query(
    client: BackstopClient,
    *,
    wait_seconds: float = REPORT_WAIT_SECONDS,
    ttl_seconds: float = REPORT_RUN_TTL_SECONDS,
    cache_size: int = REPORT_RUN_CACHE_SIZE,
) -> RunReportQuery:
    """A query with its own empty run cache, so tests never share runs."""
    return RunReportQuery(
        client=client,
        run_cache=ReportRunCache(maxsize=cache_size, ttl_seconds=ttl_seconds),
        wait_seconds=wait_seconds,
    )
