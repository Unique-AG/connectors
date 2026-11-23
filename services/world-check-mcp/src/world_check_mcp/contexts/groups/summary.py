from world_check_mcp.contexts.groups.models import GroupEntry
from world_check_mcp.upstream import GroupSummary


def group_entry(*, summary: GroupSummary, parent_id: str | None = None) -> GroupEntry:
    """`parent_id` is the group this one was found under, for a response that does not repeat it."""
    return GroupEntry(
        id=summary.id,
        name=summary.name,
        parent_id=summary.parent_id or parent_id,
        child_group_count=len(summary.child_groups or []),
    )


def flattened(*, summaries: list[GroupSummary], parent_id: str | None = None) -> list[GroupEntry]:
    """Each group followed by the groups under it."""
    entries: list[GroupEntry] = []
    for summary in summaries:
        entries.append(group_entry(summary=summary, parent_id=parent_id))
        entries.extend(flattened(summaries=summary.child_groups or [], parent_id=summary.id))
    return entries
