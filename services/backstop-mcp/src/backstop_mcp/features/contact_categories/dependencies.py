from datetime import timedelta
from functools import lru_cache

from fastmcp.dependencies import Depends

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client_for_current_caller, get_backstop_config
from backstop_mcp.features.contact_categories.queries import ListContactCategoriesQuery


@lru_cache(maxsize=1)
def get_list_contact_categories_query_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
) -> ListContactCategoriesQuery:
    # CACHING CANDIDATE, off unless `BACKSTOP_CONTACT_CATEGORY_CACHE_ENABLED=true`: by default
    # every read walks `/contact-categories`. A few hundred rows on the instance this was
    # built against — decide from the two histograms in `caching/cached_value.py`
    # (`catalog="contact-category"`) whether a TTL is worth the staleness.
    config = get_backstop_config()
    return ListContactCategoriesQuery(
        client=client,
        ttl=timedelta(minutes=config.contact_category_ttl_minutes),
        caching_enabled=config.contact_category_cache_enabled,
    )
