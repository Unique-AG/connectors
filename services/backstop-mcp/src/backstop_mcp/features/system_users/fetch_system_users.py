import logging

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.features.system_users.api_responses import SystemUserAttributes
from backstop_mcp.features.system_users.internal_dto import SystemUserDto

logger = logging.getLogger(__name__)

_USERS_PATH = "/system-users"
_USERS_PAGE_SIZE = 200
_DUPLICATE_WARNING = "Conflicting system users for duplicate id %r; retaining first user"


async def fetch_system_users(client: BackstopClient) -> dict[str, SystemUserDto]:
    """Fetch Backstop's system-user catalog in one paginated walk, keyed by user id."""
    page = await client.paginate(
        _USERS_PATH,
        schema=BackstopApiResource[SystemUserAttributes],
        max_records=None,
        page_size=_USERS_PAGE_SIZE,
    )

    users_by_id: dict[str, SystemUserDto] = {}
    for resource in page.items:
        user = SystemUserDto.from_resource(resource)
        if user is None:
            continue
        existing = users_by_id.get(user.id)
        if existing is None:
            users_by_id[user.id] = user
        elif existing != user:
            logger.warning(_DUPLICATE_WARNING, user.id)
    return users_by_id
