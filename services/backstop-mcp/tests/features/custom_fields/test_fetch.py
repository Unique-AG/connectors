import asyncio
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient, BackstopClientFactory
from backstop_mcp.features.custom_fields.fetch import definition_from_resource
from backstop_mcp.features.custom_fields.service import (
    CustomFieldsService,
    create_custom_fields_service,
)
from backstop_mcp.features.custom_fields.types import CustomFieldDefinitionAttributes
from tests.helpers import BASE_URL, client_factory, credential, resource

type ClientBuilder = Callable[[str], BackstopClient]


@pytest.fixture
async def clients() -> AsyncGenerator[ClientBuilder]:
    """Build a client per Backstop base URL.

    Each test uses its own sub-path as a distinct "instance" so mocked routes cannot leak
    across cases. The factory owns the base URL, so one is created per URL and all of them
    are closed together.
    """
    built: list[BackstopClientFactory] = []

    def make(base_url: str) -> BackstopClient:
        factory = client_factory(base_url)
        built.append(factory)
        return factory.for_credential(credential("schema-bob"))

    yield make
    for factory in built:
        await factory.aclose()


def _service(*, ttl_minutes: int = 60) -> CustomFieldsService:
    return create_custom_fields_service(ttl_minutes=ttl_minutes)


def _definition_resource(
    resource_id: str,
    *,
    name: str | None = "Grade",
    entity_type: str | None = "OrganizationBean",
    **attrs: object,
) -> BackstopApiResource[CustomFieldDefinitionAttributes]:
    attributes: dict[str, object] = {**attrs}
    if name is not None:
        attributes["name"] = name
    if entity_type is not None:
        attributes["entityType"] = entity_type
    return BackstopApiResource[CustomFieldDefinitionAttributes].model_validate(
        {
            "id": resource_id,
            "type": "custom-field-definitions",
            "attributes": attributes,
        }
    )


class TestDefinitionFromResource:
    def test_skips_unknown_bean(self) -> None:
        row = _definition_resource("1", entity_type="ContactBean")
        assert definition_from_resource(row) is None

    def test_skips_missing_name(self) -> None:
        assert definition_from_resource(_definition_resource("1", name=None)) is None

    def test_skips_missing_entity_type(self) -> None:
        assert definition_from_resource(_definition_resource("1", entity_type=None)) is None

    def test_keeps_organization_bean_and_maps_layout_fields(self) -> None:
        definition = definition_from_resource(
            _definition_resource(
                "42",
                name="Grade",
                entity_type="OrganizationBean",
                fieldType="picklist",
                fieldTypeDisplay="Picklist",
                isTimeSeries=False,
                selectOptions=[{"id": "1", "label": "Active"}],
                tabName="Overview",
                groupName="Status",
                layoutName="Organization",
                resourceType="organizations",
                required=True,
                clientRequired=False,
                systemDefined=False,
                description="Investor grade",
            )
        )

        assert definition is not None
        assert definition.id == "42"
        assert definition.name == "Grade"
        assert definition.entity_type == "OrganizationBean"
        assert definition.field_type == "picklist"
        assert definition.field_type_display == "Picklist"
        assert definition.is_time_series is False
        assert definition.select_options == [{"id": "1", "label": "Active"}]
        assert definition.tab_name == "Overview"
        assert definition.group_name == "Status"
        assert definition.layout_name == "Organization"
        assert definition.resource_type == "organizations"
        assert definition.required is True
        assert definition.client_required is False
        assert definition.system_defined is False
        assert definition.description == "Investor grade"

    def test_missing_select_options_become_empty_list(self) -> None:
        definition = definition_from_resource(_definition_resource("1"))
        assert definition is not None
        assert definition.select_options == []

    def test_null_select_options_become_empty_list(self) -> None:
        definition = definition_from_resource(_definition_resource("1", selectOptions=None))
        assert definition is not None
        assert definition.select_options == []


class TestCatalogGet:
    @pytest.mark.asyncio
    @respx.mock
    async def test_first_get_paginates_and_caches(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/refresh-index"
        service = _service()

        route = respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        resource(
                            "99",
                            "custom-field-definitions",
                            name="is1",
                            entityType="OrganizationBean",
                            fieldType="picklist",
                            isTimeSeries=False,
                            selectOptions=[{"id": "1", "label": "Active"}],
                            tabName="Overview",
                            groupName="Status",
                            layoutName="Organization",
                            resourceType="organizations",
                        ),
                        resource(
                            "100",
                            "custom-field-definitions",
                            entityType="OrganizationBean",
                            fieldType="text",
                        ),
                        resource(
                            "101",
                            "custom-field-definitions",
                            name="Hidden",
                            entityType="ContactBean",
                            fieldType="text",
                        ),
                    ],
                    "links": {"next": None},
                },
            )
        )

        definitions, cache = await service.get(clients(base_url))

        params = route.calls.last.request.url.params
        assert params["page[limit]"] == "1000"
        assert "include" not in params

        assert cache == "ok"
        assert len(definitions) == 1
        assert definitions[0].name == "is1"
        assert definitions[0].entity_type == "OrganizationBean"
        assert definitions[0].select_options == [{"id": "1", "label": "Active"}]
        assert definitions[0].tab_name == "Overview"
        assert definitions[0].group_name == "Status"
        assert definitions[0].layout_name == "Organization"
        assert definitions[0].resource_type == "organizations"


class TestInMemoryTtl:
    """The in-memory catalog is a cache with a TTL, not a permanent record."""

    @staticmethod
    def _age_past_ttl(service: CustomFieldsService) -> None:
        past = datetime.now(UTC) - timedelta(minutes=90)
        service._freshness.mark(past)  # pyright: ignore[reportPrivateUsage]

    @staticmethod
    def _definitions_route(base_url: str, name: str, definition_id: str = "1") -> respx.Route:
        return respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        resource(
                            definition_id,
                            "custom-field-definitions",
                            name=name,
                            entityType="OrganizationBean",
                            fieldType="text",
                            isTimeSeries=False,
                        )
                    ],
                    "links": {"next": None},
                },
            )
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_second_get_within_ttl_does_not_call_backstop(
        self, clients: ClientBuilder
    ) -> None:
        base_url = f"{BASE_URL}/ttl-fresh"
        service = _service()
        route = self._definitions_route(base_url, "Cached Field")

        first, first_cache = await service.get(clients(base_url))
        second, second_cache = await service.get(clients(base_url))

        assert route.call_count == 1
        assert first_cache == "ok"
        assert second_cache == "ok"
        assert [d.name for d in first] == ["Cached Field"]
        assert [d.name for d in second] == ["Cached Field"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_past_ttl_fetches_again(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ttl-expired"
        service = _service()
        route = respx.get(f"{base_url}/custom-field-definitions").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "data": [
                            resource(
                                "old-1",
                                "custom-field-definitions",
                                name="Stale Field",
                                entityType="OrganizationBean",
                                fieldType="text",
                                isTimeSeries=False,
                            )
                        ],
                        "links": {"next": None},
                    },
                ),
                httpx.Response(
                    200,
                    json={
                        "data": [
                            resource(
                                "new-1",
                                "custom-field-definitions",
                                name="Fresh Field",
                                entityType="OrganizationBean",
                                fieldType="text",
                                isTimeSeries=False,
                            )
                        ],
                        "links": {"next": None},
                    },
                ),
            ]
        )

        await service.get(clients(base_url))
        self._age_past_ttl(service)
        definitions, cache = await service.get(clients(base_url))

        assert route.call_count == 2
        assert cache == "ok"
        assert [d.name for d in definitions] == ["Fresh Field"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_refresh_fetches_even_when_fresh(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ttl-refresh"
        service = _service()
        route = respx.get(f"{base_url}/custom-field-definitions").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "data": [
                            resource(
                                "old-1",
                                "custom-field-definitions",
                                name="Cached Field",
                                entityType="OrganizationBean",
                                fieldType="text",
                                isTimeSeries=False,
                            )
                        ],
                        "links": {"next": None},
                    },
                ),
                httpx.Response(
                    200,
                    json={
                        "data": [
                            resource(
                                "new-1",
                                "custom-field-definitions",
                                name="Refreshed Field",
                                entityType="OrganizationBean",
                                fieldType="text",
                                isTimeSeries=False,
                            )
                        ],
                        "links": {"next": None},
                    },
                ),
            ]
        )

        await service.get(clients(base_url))
        definitions, cache = await service.get(clients(base_url), refresh=True)

        assert route.call_count == 2
        assert cache == "ok"
        assert [d.name for d in definitions] == ["Refreshed Field"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_warm_read_does_not_queue_behind_an_in_flight_refresh(
        self, clients: ClientBuilder
    ) -> None:
        """A fresh `get()` must not block on the lock a refresh is holding."""
        base_url = f"{BASE_URL}/ttl-warm-read-not-blocked"
        service = _service()
        self._definitions_route(base_url, "Warm Field")
        await service.get(clients(base_url))

        refresh_started = asyncio.Event()
        release_refresh = asyncio.Event()

        async def blocked_definitions(_request: httpx.Request) -> httpx.Response:
            refresh_started.set()
            await release_refresh.wait()
            return httpx.Response(200, json={"data": [], "links": {"next": None}})

        respx.get(f"{base_url}/custom-field-definitions").mock(side_effect=blocked_definitions)

        refresh_task = asyncio.create_task(service.get(clients(base_url), refresh=True))
        await asyncio.wait_for(refresh_started.wait(), timeout=5)

        definitions, cache = await asyncio.wait_for(service.get(clients(base_url)), timeout=1)
        assert cache == "ok"
        assert [d.name for d in definitions] == ["Warm Field"]

        release_refresh.set()
        _ = await asyncio.wait_for(refresh_task, timeout=5)

    @pytest.mark.asyncio
    @respx.mock
    async def test_concurrent_cold_gets_produce_one_walk(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ttl-single-flight"
        service = _service()
        route = self._definitions_route(base_url, "Fresh Field")
        client = clients(base_url)

        results = await asyncio.gather(
            service.get(client),
            service.get(client),
            service.get(client),
        )

        assert route.call_count == 1
        for definitions, cache in results:
            assert cache == "ok"
            assert [d.name for d in definitions] == ["Fresh Field"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_failed_fetch_with_a_cache_keeps_stale(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ttl-refresh-fails"
        service = _service()
        self._definitions_route(base_url, "Stale Field", definition_id="old-1")
        await service.get(clients(base_url))
        self._age_past_ttl(service)

        respx.get(f"{base_url}/custom-field-definitions").mock(
            side_effect=httpx.ConnectError("backstop down")
        )

        definitions, cache = await service.get(clients(base_url))

        assert cache == "stale"
        assert [d.name for d in definitions] == ["Stale Field"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_failed_fetch_with_no_cache_raises(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ttl-cold-failure"
        service = _service()
        respx.get(f"{base_url}/custom-field-definitions").mock(
            side_effect=httpx.ConnectError("backstop down")
        )

        with pytest.raises(httpx.ConnectError):
            await service.get(clients(base_url))
