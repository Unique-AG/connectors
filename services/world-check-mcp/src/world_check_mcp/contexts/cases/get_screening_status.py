from world_check_mcp.contexts.cases.get_case import get_case
from world_check_mcp.contexts.cases.models import ProviderSummary
from world_check_mcp.contexts.cases.models import ScreeningStatus
from world_check_mcp.upstream import GET_SCREENING_STATUS
from world_check_mcp.upstream import Upstream


async def get_screening_status(*, upstream: Upstream, case: str) -> ScreeningStatus:
    """WATCHLIST and Passport Check progress, without screening the case again."""
    resolved = await get_case(upstream=upstream, case=case)
    found = await upstream.call(
        GET_SCREENING_STATUS,
        screeningStatusRequests=[{"caseSystemId": resolved.case_system_id}],
        providerTypes=["WATCHLIST", "PASSPORT_CHECK"],
    )
    status = next((item for item in found if item.case_system_id == resolved.case_system_id), None)
    if status is None:
        return ScreeningStatus(
            case_system_id=resolved.case_system_id, screening_status=None, providers=[]
        )
    return ScreeningStatus(
        case_system_id=status.case_system_id,
        screening_status=status.screening_status,
        providers=[
            ProviderSummary(
                provider_type=provider,
                total_matches=counts.total_matches,
                review_required=counts.review_required,
                unresolved=counts.unresolved,
            )
            for provider, counts in status.provider_summaries.items()
        ],
    )
