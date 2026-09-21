from functools import lru_cache

from fastmcp.dependencies import Depends

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client_for_current_caller
from backstop_mcp.features.tasks.queries import GetTasksForPartyQuery
from backstop_mcp.features.ui_links import (
    BuildEntityLinkUtil,
    get_build_entity_link_util_factory,
)


@lru_cache(maxsize=1)
def get_tasks_for_party_query_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    build_entity_link_util: BuildEntityLinkUtil = Depends(get_build_entity_link_util_factory),
) -> GetTasksForPartyQuery:
    return GetTasksForPartyQuery(client=client, build_entity_link_util=build_entity_link_util)
