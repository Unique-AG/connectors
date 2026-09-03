"""What is specific to the activity-tag catalog.

The TTL, single-flight and serve-stale protocol behind `get` is `CachedValue`, exercised in
`tests/test_cached_value.py`. Service-to-Backstop wiring is in
`tests/features/test_cached_catalog.py`.
"""

from collections.abc import AsyncGenerator, Callable

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient, BackstopClientFactory
from backstop_mcp.features.activity_tags import ActivityTagsService
from tests.helpers import BASE_URL, client_factory, credential, resource

type ClientBuilder = Callable[[str], BackstopClient]

_LIVE_TAG_ID = "474963"


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


class TestActivityTagsService:
    @pytest.mark.asyncio
    @respx.mock
    async def test_the_catalog_carries_the_tag_counts_and_visibility(
        self, clients: ClientBuilder
    ) -> None:
        """`quantityTagged` and `viewable` are what makes a tag usable as a filter value."""
        base_url = f"{BASE_URL}/activity-tags-projection"
        service = ActivityTagsService.with_ttl_minutes(client=clients(base_url), ttl_minutes=60)
        respx.get(f"{base_url}/activity-tags").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        resource(
                            _LIVE_TAG_ID,
                            "activity-tags",
                            name="Quarterly Review",
                            quantityTagged=12,
                            viewable=True,
                        )
                    ],
                    "links": {"next": None},
                },
            )
        )

        tags, cache = await service.get()

        assert cache == "ok"
        assert tags[_LIVE_TAG_ID].name == "Quarterly Review"
        assert tags[_LIVE_TAG_ID].quantity_tagged == 12
        assert tags[_LIVE_TAG_ID].viewable is True
