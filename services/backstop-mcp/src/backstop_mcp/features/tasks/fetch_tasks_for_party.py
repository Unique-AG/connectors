"""One party's tasks: both `entityType` and `entityId` filters, always.

Either filter alone is accepted and ignored — the whole collection comes back. The pair
must use Backstop's Bean casing (`OrganizationBean`, not `organizations`). `status` is not
filterable; open vs completed is applied after the walk.
"""

import logging

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.tasks.api_responses import TaskAttributes
from backstop_mcp.features.tasks.internal_dto import TaskDto, TasksListingDto

logger = logging.getLogger(__name__)

_PATH = "/tasks"
_PAGE_SIZE = 200

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


async def fetch_tasks_for_party(
    client: BackstopClient, *, search_type: SearchType, entity_id: str
) -> TasksListingDto:
    """Walk `/tasks` for one party. Both entity filters are always sent."""
    page = await client.paginate(
        _PATH,
        schema=BackstopApiResource[TaskAttributes],
        params={
            "filter[entityType][eq]": _ENTITY_TYPE[search_type],
            "filter[entityId][eq]": entity_id,
        },
        max_records=MAX_TASK_SCAN_RECORDS,
        page_size=_PAGE_SIZE,
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
    return TasksListingDto(
        rows=tuple(TaskDto.from_resource(resource) for resource in page.items),
        scan_truncated=page.truncated,
    )
