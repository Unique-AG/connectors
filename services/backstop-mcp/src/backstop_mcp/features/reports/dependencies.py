from functools import lru_cache

from fastmcp.dependencies import Depends

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client_for_current_caller
from backstop_mcp.features.reports.queries import (
    REPORT_RUN_CACHE_SIZE,
    REPORT_RUN_TTL_SECONDS,
    ReportRunCache,
    RunReportQuery,
)


@lru_cache(maxsize=1)
def get_report_run_cache() -> ReportRunCache:
    return ReportRunCache(maxsize=REPORT_RUN_CACHE_SIZE, ttl_seconds=REPORT_RUN_TTL_SECONDS)


@lru_cache(maxsize=1)
def get_run_report_query_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    run_cache: ReportRunCache = Depends(get_report_run_cache),
) -> RunReportQuery:
    return RunReportQuery(client=client, run_cache=run_cache)
