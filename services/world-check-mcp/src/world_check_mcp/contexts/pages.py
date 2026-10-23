from world_check_mcp.upstream import GET_RESULTS
from world_check_mcp.upstream import next_page
from world_check_mcp.upstream import ResultWire
from world_check_mcp.upstream import Upstream


class ResultPageError(Exception):
    """The result list stopped before the upstream offered a last page."""


async def all_case_results(*, upstream: Upstream, case_system_id: str) -> list[ResultWire]:
    """Every result on the case, following next-page references at most 100 times."""
    found: list[ResultWire] = []
    page_reference: str | None = None
    seen: set[str] = set()
    for _ in range(100):
        pagination: dict[str, object] = {"itemsPerPage": 1000}
        if page_reference is not None:
            pagination["pageReference"] = page_reference
        page = await upstream.call(GET_RESULTS, caseSystemId=case_system_id, pagination=pagination)
        found.extend(page.results)
        following = next_page(page.pagination)
        if following is None:
            return found
        if following in seen:
            break
        seen.add(following)
        page_reference = following
    raise ResultPageError("Could not retrieve every result within the pagination limit.")
