import logging
from datetime import timedelta

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.caching import CachedValue, CacheFreshness
from backstop_mcp.features.contact_categories.api_responses import ContactCategoryAttributes
from backstop_mcp.features.contact_categories.internal_dto import ContactCategoryDto
from backstop_mcp.features.contact_categories.responses import (
    ContactCategoryResponse,
    ListContactCategoriesResponse,
)

logger = logging.getLogger(__name__)


class ListContactCategoriesQuery:
    """Walk `GET /contact-categories` and project the instance vocabulary.

    A few hundred rows on the instance this was built against. Caching is off unless the
    factory turns it on — the walk is small enough that a TTL is not the default.
    `CachedValue` still coalesces concurrent callers onto one fetch.
    """

    def __init__(
        self, *, client: BackstopClient, ttl: timedelta, caching_enabled: bool = False
    ) -> None:
        self._client: BackstopClient = client
        self._cache: CachedValue[dict[str, ContactCategoryDto]] = CachedValue(
            ttl=ttl,
            snapshot=dict,
            name="contact-category",
            log_prefix="contact_categories",
            caching_enabled=caching_enabled,
        )

    async def get(
        self, *, refresh: bool = False
    ) -> tuple[dict[str, ContactCategoryDto], CacheFreshness]:
        return await self._cache.get(self._fetch, refresh=refresh)

    async def run(
        self, *, search: str | None = None, refresh: bool = False
    ) -> ListContactCategoriesResponse:
        catalog, cache = await self.get(refresh=refresh)
        categories = [
            ContactCategoryResponse.from_category(category) for category in catalog.values()
        ]
        if search is not None:
            needle = search.casefold()
            categories = [category for category in categories if needle in category.name.casefold()]
        return ListContactCategoriesResponse(cache=cache, categories=categories)

    async def _fetch(self) -> dict[str, ContactCategoryDto]:
        """One paginated walk, keyed by id.

        `GET /contact-categories` accepts `filter[name][like]`, but the walk is the whole
        vocabulary so `search` can substring-filter in memory (case-insensitive) and a
        cached catalog can serve a different needle.
        """
        page = await self._client.paginate(
            "/contact-categories",
            schema=BackstopApiResource[ContactCategoryAttributes],
            max_records=None,
            page_size=100,
        )

        categories_by_id: dict[str, ContactCategoryDto] = {}
        for resource in page.items:
            category = ContactCategoryDto.from_resource(resource)
            if category is None:
                continue
            existing = categories_by_id.get(category.id)
            if existing is None:
                categories_by_id[category.id] = category
            elif existing != category:
                logger.warning(
                    "Conflicting contact categories for duplicate id %r; retaining first category",
                    category.id,
                )
        return categories_by_id
