import asyncio
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from backstop_mcp.backstop_client import BackstopClient, BackstopClientFactory
from backstop_mcp.features.custom_fields.lov import inline_allowed_values
from backstop_mcp.features.custom_fields.resolve import resolve_field
from backstop_mcp.features.custom_fields.service import (
    CustomFieldsService,
    create_custom_fields_service,
)
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


def lov_entries_route(base_url: str, *entries: dict[str, object]) -> respx.Route:
    """Every schema refresh also pages `/lov-entries`; mock it explicitly so a missing route
    can't be silently swallowed by `fetch_lov_entry_index`'s failure tolerance."""
    return respx.get(f"{base_url}/lov-entries").mock(
        return_value=httpx.Response(200, json={"data": list(entries), "links": {"next": None}})
    )


def lov_entry(entry_id: str, set_id: str, display: str, position: int = 0) -> dict[str, object]:
    return resource(
        entry_id,
        "lov-entries",
        display=display,
        setId=set_id,
        position=position,
        viewable=True,
    )


def _service(*, ttl_minutes: int = 60) -> CustomFieldsService:
    return create_custom_fields_service(ttl_minutes=ttl_minutes)


class TestInlineAllowedValues:
    """Backstop returns inlined LOV options as either objects or bare strings, so both parse."""

    def test_string_select_options(self) -> None:
        values = inline_allowed_values(None, ["Active", " Closed ", ""])
        assert [(v.id, v.label) for v in values] == [(None, "Active"), (None, "Closed")]

    def test_string_lov_set_entries(self) -> None:
        values = inline_allowed_values(["Yes", "No"], None)
        assert [(v.id, v.label) for v in values] == [(None, "Yes"), (None, "No")]

    def test_deduplicates_across_sources(self) -> None:
        values = inline_allowed_values(["Active"], [{"id": "1", "label": "Active"}])
        assert [(v.id, v.label) for v in values] == [("1", "Active")]

    def test_prefers_display_over_generic_label_keys(self) -> None:
        """`display` is the field `lov-entries` actually uses (per the swagger)."""
        values = inline_allowed_values(None, [{"id": "1", "display": "Grade A", "name": "ga"}])
        assert [v.label for v in values] == ["Grade A"]

    def test_skips_empty_earlier_collection_for_later_nonempty(self) -> None:
        values = inline_allowed_values(
            {"entries": [], "viewableEntries": [{"id": "9", "display": "Open"}]},
            None,
        )
        assert [(v.id, v.label) for v in values] == [("9", "Open")]

    def test_json_api_option_keeps_envelope_id(self) -> None:
        values = inline_allowed_values(
            None,
            [{"id": "42", "attributes": {"display": "Active"}}],
        )
        assert [(v.id, v.label) for v in values] == [("42", "Active")]

    def test_skips_blank_earlier_label_for_later_usable(self) -> None:
        values = inline_allowed_values(
            None,
            [{"id": "1", "label": "", "defaultDisplay": "Fallback"}],
        )
        assert [(v.id, v.label) for v in values] == [("1", "Fallback")]


class TestDefinitionFromResource:
    def test_skips_unknown_entity_type(self) -> None:
        from backstop_mcp.backstop_client import BackstopApiResource
        from backstop_mcp.features.custom_fields.fetch import definition_from_resource
        from backstop_mcp.features.custom_fields.lov import EMPTY_LOV_INDEX
        from backstop_mcp.features.custom_fields.types import CustomFieldDefinitionAttributes

        resource = BackstopApiResource[CustomFieldDefinitionAttributes].model_validate(
            {
                "id": "1",
                "type": "custom-field-definitions",
                "attributes": {"name": "Grade", "entityType": "spaceship"},
            }
        )
        assert definition_from_resource(resource, lov_index=EMPTY_LOV_INDEX, included=[]) is None


class TestFetchAndResolve:
    @pytest.mark.asyncio
    @respx.mock
    async def test_refresh_indexes_definitions(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/refresh-index"
        service = _service()

        lov_entries_route(base_url)
        respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        resource(
                            "99",
                            "custom-field-definitions",
                            name="is1",
                            entityType="Organization",
                            fieldType="picklist",
                            isTimeSeries=False,
                            selectOptions=[{"id": "1", "label": "Active"}],
                        )
                    ],
                    "links": {"next": None},
                },
            )
        )

        definitions = await service.refresh(clients(base_url), subject=SUBJECT)

        assert len(definitions) == 1
        assert definitions[0].display_name == "is1"
        assert definitions[0].aliases == ()
        assert definitions[0].allowed_values[0].label == "Active"

        # Resolving again hits the just-refreshed in-memory index, not Backstop — the route
        # mock above would have been called a second time otherwise.
        result = await resolve_field(
            service,
            clients(base_url),
            entity_type="organizations",
            query="is1",
            subject=SUBJECT,
        )
        assert isinstance(result, Resolved)
        assert result.value.crm_name == "is1"

    @pytest.mark.asyncio
    @respx.mock
    async def test_second_resolve_does_not_refetch(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/tenant-a"
        service = _service()

        lov_entries_route(base_url)
        route = respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        resource(
                            "1",
                            "custom-field-definitions",
                            name="Grade",
                            entityType="organizations",
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


class TestLovSetRelationship:
    """UN-23677: picklist fields must expose their allowed values.

    `?include=lovSet` side-loads the *set* into the document's top-level `included` array, and
    the values themselves live in `lov-entries` keyed by `setId` — two hops, neither of which is
    `attributes.lovSet`. Reading only the attribute yielded no options for exactly the fields
    write-validation needs.
    """

    @pytest.mark.asyncio
    @respx.mock
    async def test_allowed_values_come_from_lov_entries_joined_by_set_id(
        self, clients: ClientBuilder
    ) -> None:
        base_url = f"{BASE_URL}/lov-relationship"
        service = _service()

        lov_entries_route(
            base_url,
            lov_entry("e2", "500", "B", position=2),
            lov_entry("e1", "500", "A", position=1),
            lov_entry("e9", "999", "Unrelated", position=1),
        )
        respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            **resource(
                                "42",
                                "custom-field-definitions",
                                name="Grade",
                                entityType="organizations",
                                fieldType="picklist",
                                isTimeSeries=False,
                            ),
                            "relationships": {
                                "lovSet": {"data": {"type": "lov-system-sets", "id": "500"}}
                            },
                        }
                    ],
                    # The set arrives here, one hop short of the entries.
                    "included": [resource("500", "lov-system-sets", lovName="Grades")],
                    "links": {"next": None},
                },
            )
        )

        definitions = await service.refresh(clients(base_url), subject=SUBJECT)

        assert definitions[0].lov_set_id == "500"
        # Ordered by `position`, and the other set's entry is not mixed in.
        assert [v.label for v in definitions[0].allowed_values] == ["A", "B"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_hidden_entries_are_excluded(self, clients: ClientBuilder) -> None:
        """A value the client switched off would be refused by the Backstop UI on write."""
        base_url = f"{BASE_URL}/lov-hidden"
        service = _service()

        respx.get(f"{base_url}/lov-entries").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        lov_entry("e1", "7", "Visible", position=1),
                        resource(
                            "e2",
                            "lov-entries",
                            display="Hidden",
                            setId="7",
                            position=2,
                            viewable=False,
                        ),
                    ],
                    "links": {"next": None},
                },
            )
        )
        respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            **resource(
                                "8",
                                "custom-field-definitions",
                                name="Status",
                                entityType="organizations",
                            ),
                            "relationships": {"lovSet": {"data": {"id": "7"}}},
                        }
                    ],
                    "links": {"next": None},
                },
            )
        )

        definitions = await service.refresh(clients(base_url), subject=SUBJECT)

        assert [v.label for v in definitions[0].allowed_values] == ["Visible"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_definitions_still_load_when_lov_entries_fails(
        self, clients: ClientBuilder
    ) -> None:
        """Allowed values are an enrichment; losing them must not fail the whole schema."""
        base_url = f"{BASE_URL}/lov-unavailable"
        service = _service()

        respx.get(f"{base_url}/lov-entries").mock(side_effect=httpx.ConnectError("lov down"))
        respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        resource(
                            "8",
                            "custom-field-definitions",
                            name="Status",
                            entityType="organizations",
                        )
                    ],
                    "links": {"next": None},
                },
            )
        )

        definitions = await service.refresh(clients(base_url), subject=SUBJECT)

        assert [d.crm_name for d in definitions] == ["Status"]
        assert definitions[0].allowed_values == ()

    @pytest.mark.asyncio
    @respx.mock
    async def test_falls_back_to_a_side_loaded_set_carrying_its_own_entries(
        self, clients: ClientBuilder
    ) -> None:
        base_url = f"{BASE_URL}/lov-included-entries"
        service = _service()

        lov_entries_route(base_url)
        respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            **resource(
                                "8",
                                "custom-field-definitions",
                                name="Status",
                                entityType="organizations",
                            ),
                            "relationships": {"lovSet": {"data": {"id": "31"}}},
                        }
                    ],
                    "included": [
                        resource(
                            "31",
                            "lov-system-sets",
                            entries=[{"id": "a", "display": "Warm"}, {"id": "b", "display": "Hot"}],
                        )
                    ],
                    "links": {"next": None},
                },
            )
        )

        definitions = await service.refresh(clients(base_url), subject=SUBJECT)

        assert [v.label for v in definitions[0].allowed_values] == ["Warm", "Hot"]


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
        lov_entries_route(base_url)
        return respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        resource(
                            definition_id,
                            "custom-field-definitions",
                            name=name,
                            entityType="organizations",
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
        held across `_refresh_unlocked`'s two full paginations — so every concurrent lookup
        serialized behind whichever caller happened to be refreshing.
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
        assert [
            d.display_name for d in service.definitions_for("organizations", subject=SUBJECT)
        ] == ["Cached Field"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_index_past_ttl_is_refetched(self, clients: ClientBuilder) -> None:
        base_url = f"{BASE_URL}/ttl-expired"
        service = _service()
        lov_entries_route(base_url)
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
                                entityType="organizations",
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
                                entityType="organizations",
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
        assert [
            d.display_name for d in service.definitions_for("organizations", subject=SUBJECT)
        ] == ["Fresh Field"]

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
        assert [
            d.display_name for d in service.definitions_for("organizations", subject=SUBJECT)
        ] == ["Fresh Field"]

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

        lov_entries_route(base_url)
        respx.get(f"{base_url}/custom-field-definitions").mock(
            side_effect=httpx.ConnectError("backstop down")
        )

        await service.ensure_fresh(clients(base_url), subject=SUBJECT)

        assert [
            d.display_name for d in service.definitions_for("organizations", subject=SUBJECT)
        ] == ["Stale Field"]
        assert service.is_fresh(SUBJECT) is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_failed_refresh_with_nothing_cached_still_raises(
        self, clients: ClientBuilder
    ) -> None:
        """Tolerance only applies when there is something to fall back on."""
        base_url = f"{BASE_URL}/ttl-cold-failure"
        service = _service()
        lov_entries_route(base_url)
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

        lov_entries_route(base_url)
        respx.get(f"{base_url}/custom-field-definitions").mock(
            side_effect=httpx.ConnectError("backstop down")
        )

        with pytest.raises(httpx.ConnectError):
            await service.refresh(clients(base_url), subject=SUBJECT)
        assert [
            d.display_name for d in service.definitions_for("organizations", subject=SUBJECT)
        ] == ["Cached Field"]


class TestRefreshFloor:
    """`list_custom_fields` hands the model a `refresh` flag, and one refresh is two uncapped
    paginations taken under the lock every other caller's cold path waits on."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_second_forced_refresh_inside_the_floor_does_not_hit_backstop(
        self, clients: ClientBuilder
    ) -> None:
        base_url = f"{BASE_URL}/refresh-floor"
        lov_entries_route(base_url)
        route = respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        resource(
                            "900",
                            "custom-field-definitions",
                            name="Investor Status",
                            entityType="Organization",
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
        assert [d.display_name for d in second] == [d.display_name for d in first]

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_forced_refresh_past_the_floor_fetches_again(
        self, clients: ClientBuilder
    ) -> None:
        base_url = f"{BASE_URL}/refresh-floor-elapsed"
        lov_entries_route(base_url)
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
        lov_entries_route(base_url)
        route = respx.get(f"{base_url}/custom-field-definitions").mock(
            side_effect=httpx.ConnectError("backstop down")
        )
        service = _service()

        with pytest.raises(httpx.ConnectError):
            _ = await service.refresh(clients(base_url), subject=SUBJECT)
        assert await service.refresh(clients(base_url), subject=SUBJECT) == []

        assert route.call_count == 1
