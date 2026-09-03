"""A party's CRM tasks, fetched with the paired entityType+entityId filter."""

from backstop_mcp.features.tasks.api_responses import TaskAttributes
from backstop_mcp.features.tasks.dependencies import get_tasks_for_party_query_factory
from backstop_mcp.features.tasks.queries import (
    MAX_TASK_SCAN_RECORDS,
    GetTasksForPartyQuery,
    TaskFilter,
)
from backstop_mcp.features.tasks.responses import (
    PartyTasksResponse,
    TaskRowResponse,
    TasksResolvedResponse,
)

__all__ = [
    "MAX_TASK_SCAN_RECORDS",
    "GetTasksForPartyQuery",
    "PartyTasksResponse",
    "TaskAttributes",
    "TaskFilter",
    "TaskRowResponse",
    "TasksResolvedResponse",
    "get_tasks_for_party_query_factory",
]
