import asyncio
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient, BackstopClientFactory
from backstop_mcp.features.custom_fields.fetch import definition_from_resource
from backstop_mcp.features.custom_fields.resolve import resolve_field
from backstop_mcp.features.custom_fields.service import (
    CustomFieldsService,
    create_custom_fields_service,
)
from backstop_mcp.features.custom_fields.types import CustomFieldDefinitionAttributes
from backstop_mcp.features.resolution import Resolved
from tests.helpers import BASE_URL, client_factory, credential, resource

type ClientBuilder = Callable[[str], BackstopClient]

SUBJECT = "schema-bob"


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


class TestFetchAndResolve:
    @pytest.mark.asyncio
    @respx.mock
    async def test_refresh_indexes_definitions(self, clients: ClientBuilder) -> None:
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

        definitions = await service.refresh(clients(base_url), subject=SUBJECT)

        params = route.calls.last.request.url.params
        assert params["page[limit]"] == "1000"
        assert "include" not in params

        assert len(definitions) == 1
        assert definitions[0].name == "is1"
        assert definitions[0].entity_type == "OrganizationBean"
        assert definitions[0].select_options == [{"id": "1", "label": "Active"}]
        assert definitions[0].tab_name == "Overview"
        assert definitions[0].group_name == "Status"
        assert definitions[0].layout_name == "Organization"
        assert definitions[0].resource_type == "organizations"

        result = await resolve_field(
            service,
            clients(base_url),
            entity_type="organizations",
            query="is1",
            subject=SUBJECT,
        )
        assert isinstance(result, Resolved)
        assert result.value.name == "is1"

    @pytest.mark.asyncio
    @respx.mock
    async def test_second_resolve_does_not_refetch(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/tenant-a"
        service = _service()

        route = respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        resource(
                            "1",
                            "custom-field-definitions",
                            name="Grade",
                            entityType="OrganizationBean",
                            fieldType="text",
                            isTimeSeries=False,
                        )
                    ],
                    "links": {"next": None},
                },
            )
        )

        client = clients(base_url)
        await resolve_field(
            service, client, entity_type="organizations", query="Grade", subject=SUBJECT
        )
        await resolve_field(
            service, client, entity_type="organizations", query="Grade", subject=SUBJECT
        )

        assert route.call_count == 1


class TestInMemoryTtl:
    """The in-memory per-subject index is a cache with a TTL, not a permanent record."""

    @staticmethod
    def _age_past_ttl(service: CustomFieldsService) -> None:
        past = datetime.now(UTC) - timedelta(minutes=90)
        entry = service._entry(SUBJECT)  # pyright: ignore[reportPrivateUsage]
        entry.freshness.mark(past)
        entry.refresh_floor.mark(past)

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
    async def test_a_warm_read_does_not_queue_behind_an_in_flight_refresh(
        self, clients: ClientBuilder
    ) -> None:
        """A fresh `ensure_fresh()` must not block on the lock a cold refresh is holding.

        Warm callers used to take `self._lock` merely to read `is_fresh`, and the same lock is
        held across `_refresh_unlocked`'s pagination — so every concurrent lookup serialized
        behind whichever caller happened to be refreshing.
        """
        base_url = f"{BASE_URL}/ttl-warm-read-not-blocked"
        service = _service()
        self._definitions_route(base_url, "Warm Field")
        await service.refresh(clients(base_url), subject=SUBJECT)
        assert service.is_fresh(SUBJECT) is True
        # The just-completed refresh stamped the floor; clear it so the next `refresh()`
        # actually fetches (and holds the lock) rather than returning immediately.
        service._entry(SUBJECT).refresh_floor.clear()  # pyright: ignore[reportPrivateUsage]

        refresh_started = asyncio.Event()
        release_refresh = asyncio.Event()

        async def blocked_definitions(_request: httpx.Request) -> httpx.Response:
            refresh_started.set()
            await release_refresh.wait()
            return httpx.Response(200, json={"data": [], "links": {"next": None}})

        respx.get(f"{base_url}/custom-field-definitions").mock(side_effect=blocked_definitions)

        refresh_task = asyncio.create_task(service.refresh(clients(base_url), subject=SUBJECT))
        await asyncio.wait_for(refresh_started.wait(), timeout=5)

        await asyncio.wait_for(service.ensure_fresh(clients(base_url), subject=SUBJECT), timeout=1)

        release_refresh.set()
        _ = await asyncio.wait_for(refresh_task, timeout=5)

    @pytest.mark.asyncio
    @respx.mock
    async def test_index_within_ttl_is_not_refetched(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ttl-fresh"
        service = _service()
        route = self._definitions_route(base_url, "Cached Field")

        await service.ensure_fresh(clients(base_url), subject=SUBJECT)
        await service.ensure_fresh(clients(base_url), subject=SUBJECT)

        assert route.call_count == 1
        assert [d.name for d in service.definitions_for("organizations", subject=SUBJECT)] == [
            "Cached Field"
        ]

    @pytest.mark.asyncio
    @respx.mock
    async def test_index_past_ttl_is_refetched(self, clients: ClientBuilder) -> None:
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

        await service.ensure_fresh(clients(base_url), subject=SUBJECT)
        self._age_past_ttl(service)
        await service.ensure_fresh(clients(base_url), subject=SUBJECT)

        assert route.call_count == 2
        assert [d.name for d in service.definitions_for("organizations", subject=SUBJECT)] == [
            "Fresh Field"
        ]

    @pytest.mark.asyncio
    @respx.mock
    async def test_concurrent_cold_refreshes_single_flight(self, clients: ClientBuilder) -> None:
        """Callers that miss the in-memory cache share one fetch via the service lock."""
        base_url = f"{BASE_URL}/ttl-single-flight"
        service = _service()
        route = self._definitions_route(base_url, "Fresh Field")
        client = clients(base_url)

        await asyncio.gather(
            service.ensure_fresh(client, subject=SUBJECT),
            service.ensure_fresh(client, subject=SUBJECT),
            service.ensure_fresh(client, subject=SUBJECT),
        )

        assert route.call_count == 1
        assert [d.name for d in service.definitions_for("organizations", subject=SUBJECT)] == [
            "Fresh Field"
        ]

    @pytest.mark.asyncio
    @respx.mock
    async def test_stale_index_survives_a_failed_refresh(self, clients: ClientBuilder) -> None:
        """Serving a stale glossary beats failing every field lookup (B7).

        `ensure_fresh` used to let the fetch error propagate, so one Backstop hiccup broke field
        resolution outright even though a week-old — and almost certainly still correct — schema
        sat in memory.
        """
        base_url = f"{BASE_URL}/ttl-refresh-fails"
        service = _service()
        self._definitions_route(base_url, "Stale Field", definition_id="old-1")
        await service.ensure_fresh(clients(base_url), subject=SUBJECT)
        self._age_past_ttl(service)

        respx.get(f"{base_url}/custom-field-definitions").mock(
            side_effect=httpx.ConnectError("backstop down")
        )

        await service.ensure_fresh(clients(base_url), subject=SUBJECT)

        assert [d.name for d in service.definitions_for("organizations", subject=SUBJECT)] == [
            "Stale Field"
        ]
        assert service.is_fresh(SUBJECT) is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_failed_refresh_with_nothing_cached_still_raises(
        self, clients: ClientBuilder
    ) -> None:
        """Tolerance only applies when there is something to fall back on."""
        base_url = f"{BASE_URL}/ttl-cold-failure"
        service = _service()
        respx.get(f"{base_url}/custom-field-definitions").mock(
            side_effect=httpx.ConnectError("backstop down")
        )

        with pytest.raises(httpx.ConnectError):
            await service.ensure_fresh(clients(base_url), subject=SUBJECT)

    @pytest.mark.asyncio
    @respx.mock
    async def test_explicit_refresh_still_raises_loudly(self, clients: ClientBuilder) -> None:
        """`refresh()` is the caller asking for a fetch, so a failure must not be swallowed."""
        base_url = f"{BASE_URL}/ttl-explicit-refresh-fails"
        service = _service()
        self._definitions_route(base_url, "Cached Field")
        await service.refresh(clients(base_url), subject=SUBJECT)
        service._entry(SUBJECT).refresh_floor.mark(  # pyright: ignore[reportPrivateUsage]
            datetime.now(UTC) - service.MIN_REFRESH_INTERVAL - timedelta(seconds=1)
        )

        respx.get(f"{base_url}/custom-field-definitions").mock(
            side_effect=httpx.ConnectError("backstop down")
        )

        with pytest.raises(httpx.ConnectError):
            await service.refresh(clients(base_url), subject=SUBJECT)
        assert [d.name for d in service.definitions_for("organizations", subject=SUBJECT)] == [
            "Cached Field"
        ]


class TestRefreshFloor:
    """`list_custom_fields` hands the model a `refresh` flag, and one refresh is an uncapped
    pagination taken under the lock every other caller's cold path waits on."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_second_forced_refresh_inside_the_floor_does_not_hit_backstop(
        self, clients: ClientBuilder
    ) -> None:
        base_url = f"{BASE_URL}/refresh-floor"
        route = respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        resource(
                            "900",
                            "custom-field-definitions",
                            name="Investor Status",
                            entityType="OrganizationBean",
                        )
                    ],
                    "links": {"next": None},
                },
            )
        )
        service = _service()

        first = await service.refresh(clients(base_url), subject=SUBJECT)
        second = await service.refresh(clients(base_url), subject=SUBJECT)

        assert route.call_count == 1
        # The floored call still answers coherently — with what is already indexed, not nothing.
        assert [d.name for d in second] == [d.name for d in first]

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_forced_refresh_past_the_floor_fetches_again(
        self, clients: ClientBuilder
    ) -> None:
        base_url = f"{BASE_URL}/refresh-floor-elapsed"
        route = respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=httpx.Response(200, json={"data": [], "links": {"next": None}})
        )
        service = _service()

        _ = await service.refresh(clients(base_url), subject=SUBJECT)
        # Reach in and age the attempt rather than sleeping out a real minute.
        service._entry(SUBJECT).refresh_floor.mark(  # pyright: ignore[reportPrivateUsage]
            datetime.now(UTC) - service.MIN_REFRESH_INTERVAL - timedelta(seconds=1)
        )
        _ = await service.refresh(clients(base_url), subject=SUBJECT)

        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_failed_refresh_still_counts_against_the_floor(
        self, clients: ClientBuilder
    ) -> None:
        """Otherwise an unreachable Backstop is re-dialled on every single request."""
        base_url = f"{BASE_URL}/refresh-floor-failure"
        route = respx.get(f"{base_url}/custom-field-definitions").mock(
            side_effect=httpx.ConnectError("backstop down")
        )
        service = _service()

        with pytest.raises(httpx.ConnectError):
            _ = await service.refresh(clients(base_url), subject=SUBJECT)
        assert await service.refresh(clients(base_url), subject=SUBJECT) == []

        assert route.call_count == 1
