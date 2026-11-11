from mcp_observability import traced

from world_check_mcp.contexts.cases import get_case
from world_check_mcp.contexts.monitoring.models import OngoingScreening
from world_check_mcp.upstream import CaseBulkOngoingScreeningRequestInput
from world_check_mcp.upstream import CaseSystemId
from world_check_mcp.upstream import TOGGLE_ONGOING_SCREENING
from world_check_mcp.upstream import ToggleOngoingScreeningByProviderTypesRequest
from world_check_mcp.upstream import Upstream


@traced(arguments=("case",), result=lambda r: {"enabled": r.enabled})
async def enable_ongoing_screening(*, upstream: Upstream, case: str) -> OngoingScreening:
    """Turn on WATCHLIST monitoring. An HTTP 200 body lists the cases LSEG did not update."""
    found = await get_case(upstream=upstream, case=case)
    result = await upstream.call(
        TOGGLE_ONGOING_SCREENING,
        ToggleOngoingScreeningByProviderTypesRequest(
            body=CaseBulkOngoingScreeningRequestInput(
                case_system_ids=[CaseSystemId(found.case_system_id)],
                case_screening_state={"WATCHLIST": "ONGOING"},
            )
        ),
    )
    failed_cases = [
        failed
        for failed in (result.failed_cases if result else None) or []
        if failed.case_system_id in {None, found.case_system_id}
    ]
    if not failed_cases:
        return OngoingScreening(
            case_system_id=found.case_system_id,
            enabled=True,
            provider_type="WATCHLIST",
            failures=[],
        )
    failures = [
        error.message or error.code or "LSEG did not enable monitoring."
        for failed in failed_cases
        for error in failed.errors or []
    ]
    return OngoingScreening(
        case_system_id=found.case_system_id,
        enabled=False,
        provider_type="WATCHLIST",
        failures=failures or ["LSEG did not enable monitoring."],
    )
