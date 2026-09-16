from datetime import timedelta
from functools import lru_cache

from fastmcp.dependencies import Depends

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client_for_current_caller, get_backstop_config
from backstop_mcp.features.contact_sources.queries import ListContactSourcesQuery


@lru_cache(maxsize=1)
def get_list_contact_sources_query_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
) -> ListContactSourcesQuery:
    # CACHING CANDIDATE, off unless `BACKSTOP_CONTACT_SOURCE_CACHE_ENABLED=true`: by default
    # every read walks `/contact-sources`. Thirteen rows on the instance this was built
    # against — decide from the two histograms in `caching/cached_value.py`
    # (`catalog="contact-source"`) whether a TTL is worth the staleness.
    config = get_backstop_config()
    return ListContactSourcesQuery(
        client=client,
        ttl=timedelta(minutes=config.contact_source_ttl_minutes),
        caching_enabled=config.contact_source_cache_enabled,
    )
