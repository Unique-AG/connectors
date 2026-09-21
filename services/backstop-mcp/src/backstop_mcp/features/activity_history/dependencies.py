from functools import lru_cache

from fastmcp.dependencies import Depends

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import (
    get_activity_history_config,
    get_backstop_client_for_current_caller,
)
from backstop_mcp.features.activity_history.queries import (
    GetActivityDetailQuery,
    GetActivityHistoryQuery,
    SearchActivitiesQuery,
)
from backstop_mcp.features.activity_history.settings import ActivityHistorySettings
from backstop_mcp.features.ui_links import (
    BuildEntityLinkUtil,
    get_build_entity_link_util_factory,
)


@lru_cache(maxsize=1)
def get_activity_history_settings() -> ActivityHistorySettings:
    config = get_activity_history_config()
    return ActivityHistorySettings(
        page_size=config.page_size,
        gist_max_chars=config.gist_chars,
    )


@lru_cache(maxsize=1)
def get_activity_detail_query_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    build_entity_link_util: BuildEntityLinkUtil = Depends(get_build_entity_link_util_factory),
) -> GetActivityDetailQuery:
    return GetActivityDetailQuery(client=client, build_entity_link_util=build_entity_link_util)


@lru_cache(maxsize=1)
def get_activity_history_query_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    build_entity_link_util: BuildEntityLinkUtil = Depends(get_build_entity_link_util_factory),
) -> GetActivityHistoryQuery:
    return GetActivityHistoryQuery(client=client, build_entity_link_util=build_entity_link_util)


@lru_cache(maxsize=1)
def get_search_activities_query_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
) -> SearchActivitiesQuery:
    return SearchActivitiesQuery(client=client)
