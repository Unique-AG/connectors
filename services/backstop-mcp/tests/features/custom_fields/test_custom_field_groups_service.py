"""What is specific to the custom-field group catalog.

The TTL, single-flight and serve-stale protocol behind `get` is `CachedCatalog`, exercised for
this service among the others in `tests/features/test_cached_catalog.py`.
"""

from collections.abc import AsyncGenerator, Callable

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient, BackstopClientFactory
from backstop_mcp.features.custom_fields import CustomFieldGroupsService
from tests.helpers import BASE_URL, client_factory, credential, resource

type ClientBuilder = Callable[[str], BackstopClient]


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


class TestCustomFieldGroupsService:
    @pytest.mark.asyncio
    @respx.mock
    async def test_the_catalog_carries_the_full_path_and_the_parent(
        self, clients: ClientBuilder
    ) -> None:
        """A group is only readable in context: the path it sits on and its parent group."""
        base_url = f"{BASE_URL}/custom-field-groups-projection"
        service = CustomFieldGroupsService.with_ttl_minutes(ttl_minutes=60)
        respx.get(f"{base_url}/custom-field-groups").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        resource(
                            "9",
                            "custom-field-groups",
                            name="Status",
                            fullPathName=["Overview", "Status"],
                            parent={"id": "4", "name": "Overview"},
                        )
                    ],
                    "links": {"next": None},
                },
            )
        )

        groups, cache = await service.get(clients(base_url))

        assert cache == "ok"
        assert groups["9"].name == "Status"
        assert groups["9"].full_path_name == ["Overview", "Status"]
        assert groups["9"].parent is not None
        assert groups["9"].parent.name == "Overview"
