from world_check_mcp.contexts.groups.models import Group
from world_check_mcp.contexts.groups.summary import group_from_summary
from world_check_mcp.upstream import GET_GROUPS
from world_check_mcp.upstream import GetGroupsQuery
from world_check_mcp.upstream import GetGroupsRequest
from world_check_mcp.upstream import Upstream


async def list_groups(*, upstream: Upstream) -> list[Group]:
    """Every group the service account can use, including descendant groups."""
    groups = await upstream.call(
        GET_GROUPS, GetGroupsRequest(query=GetGroupsQuery(show_all_child_groups=True))
    )
    return [group_from_summary(summary=group) for group in groups]
