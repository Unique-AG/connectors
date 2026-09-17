"""What is specific to the contact-category vocabulary.

The TTL, single-flight and serve-stale protocol behind `get` is `CachedValue`, exercised in
`tests/test_cached_value.py`. Query-to-Backstop wiring is in
`tests/features/test_cached_catalog.py`.
"""

from collections.abc import AsyncGenerator, Callable
from datetime import timedelta

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient, BackstopClientFactory
from backstop_mcp.features.contact_categories import ListContactCategoriesQuery
from tests.helpers import BASE_URL, client_factory, credential, resource

type ClientBuilder = Callable[[str], BackstopClient]

_PROSPECT_ID = "1001"


@pytest.fixture
async def clients() -> AsyncGenerator[ClientBuilder]:
    """Build a client per Backstop base URL, closing every factory at the end."""
    built: list[BackstopClientFactory] = []

    def make(base_url: str) -> BackstopClient:
        factory = client_factory(base_url)
        built.append(factory)
        return factory.for_credential(credential("schema-bob"))

    yield make
    for factory in built:
        await factory.aclose()


class TestListContactCategoriesQuery:
    @pytest.mark.asyncio
    @respx.mock
    async def test_run_projects_name(self, clients: ClientBuilder) -> None:
        """`name` is what makes a category usable as a category-id lookup."""
        base_url = f"{BASE_URL}/contact-categories-projection"
        query = ListContactCategoriesQuery(
            client=clients(base_url), ttl=timedelta(minutes=60), caching_enabled=False
        )
        respx.get(f"{base_url}/contact-categories").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        resource(
                            _PROSPECT_ID,
                            "contact-categories",
                            name="Prospect",
                        )
                    ],
                    "links": {"next": None},
                },
            )
        )

        result = await query.run()

        assert result.cache == "ok"
        assert result.categories[0].id == _PROSPECT_ID
        assert result.categories[0].name == "Prospect"
