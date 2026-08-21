"""A party's CRM tasks, fetched with the paired entityType+entityId filter."""

from backstop_mcp.features.tasks.fetch_tasks_for_party import fetch_tasks_for_party
from backstop_mcp.features.tasks.internal_dto import TaskDto

__all__ = ["TaskDto", "fetch_tasks_for_party"]
