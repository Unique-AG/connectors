from world_check_mcp.contexts.cases import get_case
from world_check_mcp.contexts.monitoring.models import OngoingScreening
from world_check_mcp.upstream import TOGGLE_ONGOING_SCREENING
from world_check_mcp.upstream import Upstream


async def enable_ongoing_screening(*, upstream: Upstream, case: str) -> OngoingScreening:
    """Turn on WATCHLIST monitoring. An HTTP 200 body lists the cases LSEG did not update."""
    found = await get_case(upstream=upstream, case=case)
    result = await upstream.call(
        TOGGLE_ONGOING_SCREENING,
        caseSystemIds=[found.case_system_id],
        caseScreeningState={"WATCHLIST": "ONGOING"},
    )
    if result is None:
        return OngoingScreening(
            case_system_id=found.case_system_id,
            enabled=True,
            provider_type="WATCHLIST",
            failures=[],
        )
    failures = [
        error.message or error.code or "LSEG did not enable monitoring."
        for failed in result.failed_cases
        if failed.case_system_id in {None, found.case_system_id}
        for error in failed.errors
    ]
    return OngoingScreening(
        case_system_id=found.case_system_id,
        enabled=False,
        provider_type="WATCHLIST",
        failures=failures or ["LSEG did not enable monitoring."],
    )
