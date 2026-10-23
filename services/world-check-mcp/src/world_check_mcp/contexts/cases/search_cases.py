import json

from world_check_mcp.contexts.cases.models import CasePage
from world_check_mcp.contexts.cases.models import CaseSummary
from world_check_mcp.contexts.cases.models import SearchMode
from world_check_mcp.upstream import next_page
from world_check_mcp.upstream import SEARCH_CASES
from world_check_mcp.upstream import Upstream


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
    arguments: dict[str, object] = {
        "searchMode": search_mode,
        "detailLevel": "CASE_AND_RESULTS",
        "sort": [{"columnName": "creationDate", "order": "DESCENDING"}],
        "pagination": _page(limit=limit, page_reference=page_reference),
        "filter": _group_filter(group_id=group_id, expression=expression),
    }
    if query is not None:
        arguments["query"] = query
    found = await upstream.call(SEARCH_CASES, **arguments)
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
            for hit in found.results
            if hit.case_system_id
        ],
        next_page=next_page(found.pagination),
    )


def _page(*, limit: int, page_reference: str | None) -> dict[str, object]:
    pagination: dict[str, object] = {"itemsPerPage": limit}
    if page_reference is not None:
        pagination["pageReference"] = page_reference
    return pagination


def _group_filter(*, group_id: str, expression: str | None) -> str:
    group = f"groupId=={json.dumps(group_id, ensure_ascii=False)}"
    if expression is None:
        return group
    return f"({expression});{group}"
