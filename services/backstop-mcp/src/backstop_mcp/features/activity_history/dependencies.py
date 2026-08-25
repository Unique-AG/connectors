from functools import lru_cache

from backstop_mcp.dependencies import get_activity_history_config
from backstop_mcp.features.activity_history.settings import ActivityHistorySettings


@lru_cache(maxsize=1)
def get_activity_history_settings() -> ActivityHistorySettings:
    config = get_activity_history_config()
    return ActivityHistorySettings(
        page_size=config.page_size,
        gist_max_chars=config.gist_chars,
    )
