"""What is specific to the contact-source vocabulary.

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
from backstop_mcp.features.contact_sources import ListContactSourcesQuery
from tests.helpers import BASE_URL, client_factory, credential, resource

type ClientBuilder = Callable[[str], BackstopClient]

_LIVE_SOURCE_ID = "194859"


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


class TestListContactSourcesQuery:
    @pytest.mark.asyncio
    @respx.mock
    async def test_run_projects_name_and_description(self, clients: ClientBuilder) -> None:
        """`name` is what makes a source usable as a `contact_source_id` lookup."""
        base_url = f"{BASE_URL}/contact-sources-projection"
        query = ListContactSourcesQuery(
            client=clients(base_url), ttl=timedelta(minutes=60), caching_enabled=False
        )
        respx.get(f"{base_url}/contact-sources").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        resource(
                            _LIVE_SOURCE_ID,
                            "contact-sources",
                            name="Referral",
                            description="Referral",
                        )
                    ],
                    "links": {"next": None},
                },
            )
        )

        result = await query.run()

        assert result.cache == "ok"
        assert result.sources[0].id == _LIVE_SOURCE_ID
        assert result.sources[0].name == "Referral"
        assert result.sources[0].description == "Referral"
