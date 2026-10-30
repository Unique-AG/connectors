from world_check_mcp.contexts.cases.errors import CaseNotFoundError
from world_check_mcp.contexts.cases.get_case_reference import get_case_reference
from world_check_mcp.contexts.cases.models import CaseDetails
from world_check_mcp.upstream import CaseWire
from world_check_mcp.upstream import GET_CASE
from world_check_mcp.upstream import Upstream
from world_check_mcp.upstream import UpstreamError


async def get_case(*, upstream: Upstream, case: str) -> CaseDetails:
    """Case details for an internal caseSystemId, or an external caseId when that misses."""
    try:
        found = await upstream.call(GET_CASE, caseSystemId=case)
    except UpstreamError as error:
        if error.status_code != 404:
            raise
        try:
            reference = await get_case_reference(upstream=upstream, case_id=case)
        except CaseNotFoundError:
            raise CaseNotFoundError(case=case) from error
        found = await upstream.call(GET_CASE, caseSystemId=reference.case_system_id)
    return _details(case=found, fallback_system_id=case)


def _details(*, case: CaseWire, fallback_system_id: str) -> CaseDetails:
    return CaseDetails(
        case_id=case.case_id,
        case_system_id=case.case_system_id or fallback_system_id,
        name=case.name,
        entity_type=case.entity_type,
        group_id=case.group_id,
        provider_types=case.provider_types,
        lifecycle_state=case.lifecycle_state,
    )
