"""One party's tasks: both `entityType` and `entityId` filters, always.

Either filter alone is accepted and ignored — the whole collection comes back. The pair
must use Backstop's Bean casing (`OrganizationBean`, not `organizations`). `status` is not
filterable; open vs completed is applied after the walk.
"""

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.tasks.api_responses import TaskAttributes
from backstop_mcp.features.tasks.internal_dto import TaskDto

_PATH = "/tasks"
_PAGE_SIZE = 200
_ENTITY_TYPE: dict[SearchType, str] = {
    "organizations": "OrganizationBean",
    "people": "PersonBean",
    "contacts": "ContactBean",
    "employees": "EmployeeBean",
}


async def fetch_tasks_for_party(
    client: BackstopClient, *, search_type: SearchType, entity_id: str
) -> tuple[TaskDto, ...]:
    """Walk `/tasks` for one party. Both entity filters are always sent."""
    page = await client.paginate(
        _PATH,
        schema=BackstopApiResource[TaskAttributes],
        params={
            "filter[entityType][eq]": _ENTITY_TYPE[search_type],
            "filter[entityId][eq]": entity_id,
        },
        max_records=None,
        page_size=_PAGE_SIZE,
    )
    return tuple(TaskDto.from_resource(resource) for resource in page.items)
