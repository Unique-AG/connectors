import json

from mcp_observability import traced

from world_check_mcp.contexts.cases.models import CasePage
from world_check_mcp.contexts.cases.models import CaseSummary
from world_check_mcp.contexts.cases.models import SearchMode
from world_check_mcp.upstream import CaseSearchRequestInput
from world_check_mcp.upstream import next_page
from world_check_mcp.upstream import PaginationReferenceRequestInput
from world_check_mcp.upstream import SEARCH_CASES
from world_check_mcp.upstream import SearchCasesRequest
from world_check_mcp.upstream import SortCriterionInput
from world_check_mcp.upstream import Upstream


@traced(
    arguments=("group_id", "search_mode", "limit", "page_reference"),
    result=lambda r: {"cases": len(r.cases)},
)
async def search_cases(
    *,
    upstream: Upstream,
    group_id: str,
    query: str | None = None,
    expression: str | None = None,
    search_mode: SearchMode = "DEFAULT",
    limit: int = 25,
    page_reference: str | None = None,
) -> CasePage:
    """Cases in one group, newest first. The group filter is always applied."""
    found = await upstream.call(
        SEARCH_CASES,
        SearchCasesRequest(
            body=CaseSearchRequestInput(
                query=query,
                search_mode=search_mode,
                detail_level="CASE_AND_RESULTS",
                filter=_group_filter(group_id=group_id, expression=expression),
                sort=[SortCriterionInput(column_name="creationDate", order="DESCENDING")],
                pagination=PaginationReferenceRequestInput(
                    items_per_page=limit, page_reference=page_reference
                ),
            )
        ),
    )
    return CasePage(
        cases=[
            CaseSummary(
                case_id=hit.case_id,
                case_system_id=hit.case_system_id,
                name=hit.name,
                entity_type=hit.entity_type,
                group_id=hit.group_id,
                lifecycle_state=hit.lifecycle_state,
            )
            for hit in found.results or []
            if hit.case_system_id
        ],
        next_page=next_page(found.pagination),
    )


def _group_filter(*, group_id: str, expression: str | None) -> str:
    group = f"groupId=={json.dumps(group_id, ensure_ascii=False)}"
    if expression is None:
        return group
    return f"({expression});{group}"
