from world_check_mcp.contexts.groups.models import Group
from world_check_mcp.upstream import GroupSummary


def group_from_summary(*, summary: GroupSummary) -> Group:
    children = summary.child_groups or []
    return Group(
        id=summary.id,
        name=summary.name,
        parent_id=summary.parent_id,
        child_groups=[group_from_summary(summary=child) for child in children],
    )
