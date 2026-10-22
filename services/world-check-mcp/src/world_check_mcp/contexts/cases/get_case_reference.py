from world_check_mcp.contexts.cases.errors import CaseNotFoundError
from world_check_mcp.contexts.cases.models import CaseReferenceDetails
from world_check_mcp.upstream import GET_CASE_REFERENCE
from world_check_mcp.upstream import Upstream
from world_check_mcp.upstream import UpstreamError


async def get_case_reference(*, upstream: Upstream, case_id: str) -> CaseReferenceDetails:
    """The internal caseSystemId for an external caseId."""
    try:
        reference = await upstream.call(GET_CASE_REFERENCE, caseId=case_id)
    except UpstreamError as error:
        if error.status_code == 404:
            raise CaseNotFoundError(case=case_id) from error
        raise
    return CaseReferenceDetails(case_id=reference.caseId, case_system_id=reference.caseSystemId)
