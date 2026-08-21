"""A party's CRM tasks, fetched with the paired entityType+entityId filter."""

from backstop_mcp.features.tasks.fetch_tasks_for_party import (
    MAX_TASK_SCAN_RECORDS,
    fetch_tasks_for_party,
)
from backstop_mcp.features.tasks.internal_dto import TaskDto, TasksListingDto

__all__ = [
    "MAX_TASK_SCAN_RECORDS",
    "TaskDto",
    "TasksListingDto",
    "fetch_tasks_for_party",
]
