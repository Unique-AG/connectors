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
) -> GetActivityDetailQuery:
    return GetActivityDetailQuery(client=client)


@lru_cache(maxsize=1)
def get_activity_history_query_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
) -> GetActivityHistoryQuery:
    return GetActivityHistoryQuery(client=client)


@lru_cache(maxsize=1)
def get_search_activities_query_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
) -> SearchActivitiesQuery:
    return SearchActivitiesQuery(client=client)
