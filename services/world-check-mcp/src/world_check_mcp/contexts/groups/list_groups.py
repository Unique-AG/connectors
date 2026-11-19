from mcp_observability import traced
from pydantic import TypeAdapter

from world_check_mcp.contexts.groups.errors import GroupPageError
from world_check_mcp.contexts.groups.models import GroupEntry
from world_check_mcp.contexts.groups.models import GroupPage
from world_check_mcp.contexts.groups.search import find_groups
from world_check_mcp.contexts.groups.summary import flattened
from world_check_mcp.persistence import Cache
from world_check_mcp.upstream import GET_GROUPS
from world_check_mcp.upstream import GetGroupsQuery
from world_check_mcp.upstream import GetGroupsRequest
from world_check_mcp.upstream import Upstream

_CACHE_SECONDS = 300
_ENTRIES = TypeAdapter(list[GroupEntry])


@traced(
    arguments=("parent_id", "limit", "page_reference"),
    result=lambda r: {"groups": len(r.groups), "total": r.total},
)
async def list_groups(
    *,
    upstream: Upstream,
    cache: Cache,
    query: str | None = None,
    parent_id: str | None = None,
    limit: int = 25,
    page_reference: str | None = None,
) -> GroupPage:
    """The groups the service account can use, descendants included, a page at a time."""

    async def load() -> list[GroupEntry]:
        groups = await upstream.call(
            GET_GROUPS, GetGroupsRequest(query=GetGroupsQuery(show_all_child_groups=True))
        )
        return flattened(summaries=groups)

    entries = await cache.read_through(
        key="groups", adapter=_ENTRIES, ttl_seconds=_CACHE_SECONDS, load=load
    )
    matching = find_groups(entries, query=query, parent_id=parent_id)
    start = _offset(page_reference=page_reference)
    following = start + limit
    return GroupPage(
        groups=matching[start:following],
        total=len(matching),
        next_page=str(following) if following < len(matching) else None,
    )


def _offset(*, page_reference: str | None) -> int:
    if page_reference is None:
        return 0
    if not page_reference.isdecimal():
        raise GroupPageError(
            "Use the next_page of the previous list_groups call as page_reference."
        )
    return int(page_reference)
