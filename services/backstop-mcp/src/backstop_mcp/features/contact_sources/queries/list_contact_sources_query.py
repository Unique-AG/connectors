import logging
from datetime import timedelta

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.caching import CachedValue, CacheFreshness
from backstop_mcp.features.contact_sources.api_responses import ContactSourceAttributes
from backstop_mcp.features.contact_sources.internal_dto import ContactSourceDto
from backstop_mcp.features.contact_sources.responses import (
    ContactSourceResponse,
    ListContactSourcesResponse,
)

logger = logging.getLogger(__name__)


class ListContactSourcesQuery:
    """Walk `GET /contact-sources` and project the instance vocabulary.

    Thirteen rows on the instance this was built against. Caching is off unless the factory
    turns it on — the walk is small enough that a TTL is not the default. `CachedValue`
    still coalesces concurrent callers onto one fetch.
    """

    def __init__(
        self, *, client: BackstopClient, ttl: timedelta, caching_enabled: bool = False
    ) -> None:
        self._client: BackstopClient = client
        self._cache: CachedValue[dict[str, ContactSourceDto]] = CachedValue(
            ttl=ttl,
            snapshot=dict,
            name="contact-source",
            log_prefix="contact_sources",
            caching_enabled=caching_enabled,
        )

    async def get(
        self, *, refresh: bool = False
    ) -> tuple[dict[str, ContactSourceDto], CacheFreshness]:
        return await self._cache.get(self._fetch, refresh=refresh)

    async def run(
        self, *, search: str | None = None, refresh: bool = False
    ) -> ListContactSourcesResponse:
        catalog, cache = await self.get(refresh=refresh)
        sources = [ContactSourceResponse.from_source(source) for source in catalog.values()]
        if search is not None:
            needle = search.casefold()
            sources = [source for source in sources if needle in source.name.casefold()]
        return ListContactSourcesResponse(cache=cache, sources=sources)

    async def _fetch(self) -> dict[str, ContactSourceDto]:
        """One paginated walk, keyed by id.

        `GET /contact-sources` rejects `filter[name][eq]` and `filter[name][like]`
        (`Invalid filter field name`). The walk is the whole vocabulary so `search`
        can substring-filter in memory.
        """
        page = await self._client.paginate(
            "/contact-sources",
            schema=BackstopApiResource[ContactSourceAttributes],
            max_records=None,
            page_size=100,
        )

        sources_by_id: dict[str, ContactSourceDto] = {}
        for resource in page.items:
            source = ContactSourceDto.from_resource(resource)
            if source is None:
                continue
            existing = sources_by_id.get(source.id)
            if existing is None:
                sources_by_id[source.id] = source
            elif existing != source:
                logger.warning(
                    "Conflicting contact sources for duplicate id %r; retaining first source",
                    source.id,
                )
        return sources_by_id
