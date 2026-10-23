from world_check_mcp.contexts.cases.get_case import get_case
from world_check_mcp.contexts.cases.models import CaseResults
from world_check_mcp.contexts.cases.models import Match
from world_check_mcp.upstream import GET_RESULTS
from world_check_mcp.upstream import next_page
from world_check_mcp.upstream import Upstream


async def get_case_results(
    *,
    upstream: Upstream,
    case: str,
    limit: int = 50,
    page_reference: str | None = None,
    expression: str | None = None,
) -> CaseResults:
    """Match facts for an internal caseSystemId, or an external caseId when that misses."""
    resolved = await get_case(upstream=upstream, case=case)
    pagination: dict[str, object] = {"itemsPerPage": limit}
    if page_reference is not None:
        pagination["pageReference"] = page_reference
    arguments: dict[str, object] = {
        "caseSystemId": resolved.case_system_id,
        "pagination": pagination,
    }
    if expression is not None:
        arguments["filter"] = expression
    found = await upstream.call(GET_RESULTS, **arguments)
    return CaseResults(
        case_system_id=resolved.case_system_id,
        matches=[
            Match(
                result_id=result.result_id,
                reference_id=result.reference_id,
                provider_type=result.provider_type,
                match_strength=result.match_strength,
                submitted_term=result.submitted_term,
            )
            for result in found.results
        ],
        next_page=next_page(found.pagination),
    )
