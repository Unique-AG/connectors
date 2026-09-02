"""One party's tasks: both `entityType` and `entityId` filters, always.

Either filter alone is accepted and ignored — the whole collection comes back. The pair
must use Backstop's Bean casing (`OrganizationBean`, not `organizations`). `status` is not
filterable; open vs completed is applied after the walk.
"""

import logging
from typing import Literal

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.tasks.api_responses import TaskAttributes
from backstop_mcp.features.tasks.responses import PartyTasksResponse, TaskRowResponse

logger = logging.getLogger(__name__)

type TaskFilter = Literal["open", "completed", "all"]

# Scan ceiling. `status` is not filterable, so one party's whole task sub-collection is read;
# 540 tasks exist across the *whole* instance, so this is a wide margin for one party and still
# a stated limit rather than "however many there are".
MAX_TASK_SCAN_RECORDS = 5_000
_ENTITY_TYPE: dict[SearchType, str] = {
    "organizations": "OrganizationBean",
    "people": "PersonBean",
    "contacts": "ContactBean",
    "employees": "EmployeeBean",
}


class GetTasksForPartyQuery:
    """Walk `/tasks` for one party. Both entity filters are always sent."""

    def __init__(self, *, client: BackstopClient) -> None:
        self._client: BackstopClient = client

    async def run(
        self,
        *,
        search_type: SearchType,
        entity_id: str,
        status: TaskFilter = "all",
    ) -> PartyTasksResponse:
        page = await self._client.paginate(
            "/tasks",
            schema=BackstopApiResource[TaskAttributes],
            params={
                "filter[entityType][eq]": _ENTITY_TYPE[search_type],
                "filter[entityId][eq]": entity_id,
            },
            max_records=MAX_TASK_SCAN_RECORDS,
            page_size=200,
        )
        if page.truncated:
            logger.warning(
                "tasks.party.scan_ceiling_reached",
                extra={
                    "entity_id": entity_id,
                    "ceiling": MAX_TASK_SCAN_RECORDS,
                    "total_count": page.total_count,
                },
            )
        rows = tuple(TaskRowResponse.from_resource(resource) for resource in page.items)
        selected = tuple(
            row for row in rows if status == "all" or (row.is_open is (status == "open"))
        )
        result = PartyTasksResponse(
            tasks=selected,
            total=len(rows),
            open_count=sum(1 for row in rows if row.is_open),
            completed_count=sum(1 for row in rows if not row.is_open),
            scan_truncated=page.truncated,
        )
        logger.info(
            "tasks.fetched",
            extra={
                "entity_id": entity_id,
                "status": status,
                "total": result.total,
                "returned": len(result.tasks),
            },
        )
        return result
