from functools import lru_cache

from fastmcp.dependencies import Depends

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client_for_current_caller
from backstop_mcp.features.reports.queries import RunReportQuery


@lru_cache(maxsize=1)
def get_run_report_query_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
) -> RunReportQuery:
    return RunReportQuery(client=client)
