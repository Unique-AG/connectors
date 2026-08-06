import asyncio
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from backstop_mcp.backstop_client import BackstopClient, BackstopClientFactory
from backstop_mcp.db.engine import read_session, transaction
from backstop_mcp.features.custom_fields import FieldOverride
from backstop_mcp.features.custom_fields.lov import inline_allowed_values
from backstop_mcp.features.custom_fields.resolve import resolve_field
from backstop_mcp.features.custom_fields.service import (
    CustomFieldsService,
    create_custom_fields_service,
)
from backstop_mcp.features.custom_fields.store import load_snapshot, save_snapshot
from backstop_mcp.features.custom_fields.types import CustomFieldDefinition
from backstop_mcp.features.resolution import Resolved
from tests.helpers import BASE_URL, client_factory, credential, resource

type DatabaseFixture = tuple[AsyncEngine, async_sessionmaker[AsyncSession]]


type ClientBuilder = Callable[[str], BackstopClient]


@pytest.fixture
async def clients() -> AsyncGenerator[ClientBuilder]:
    """Build a client per Backstop base URL.

    Each test uses its own sub-path as a distinct "instance" (snapshots are keyed by base URL,
    and the Postgres container is shared across the session). The factory owns the base URL, so
    one is created per URL and all of them are closed together.
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


class TestFetchStoreResolve:
    @pytest.mark.asyncio
    @respx.mock
    async def test_refresh_persists_snapshot_and_applies_overrides(
        self, db: DatabaseFixture, clients: ClientBuilder
    ) -> None:
        _, session_factory = db
        base_url = f"{BASE_URL}/overrides"
        overrides = {
            "organizations:is1": FieldOverride(
                display_name="Investor Status",
                aliases=("investor status",),
            )
        }
        service = create_custom_fields_service(
            session_factory=session_factory,
            base_url=base_url,
            overrides=overrides,
            ttl_minutes=60,
        )

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

        definitions = await service.refresh(clients(base_url))

        assert len(definitions) == 1
        assert definitions[0].display_name == "Investor Status"
        assert definitions[0].aliases == ("investor status",)
        assert definitions[0].allowed_values[0].label == "Active"

        async with read_session(session_factory) as session:
            loaded = await load_snapshot(session, base_url)
        assert loaded is not None
        assert loaded.definitions[0].definition_id == "99"

        # Resolving again hits the just-refreshed in-memory index, not Backstop — the route
        # mock above would have been called a second time otherwise.
        result = await resolve_field(
            service,
            clients(base_url),
            entity_type="organizations",
            query="Investor Status",
        )
        assert isinstance(result, Resolved)
        assert result.value.crm_name == "is1"

    @pytest.mark.asyncio
    @respx.mock
    async def test_second_resolve_does_not_refetch(
        self, db: DatabaseFixture, clients: ClientBuilder
    ) -> None:
        _, session_factory = db
        base_url = f"{BASE_URL}/tenant-a"
        service = create_custom_fields_service(
            session_factory=session_factory,
            base_url=base_url,
            overrides={},
            ttl_minutes=60,
        )

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
        await resolve_field(service, client, entity_type="organizations", query="Grade")
        await resolve_field(service, client, entity_type="organizations", query="Grade")

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
        self, db: DatabaseFixture, clients: ClientBuilder
    ) -> None:
        _, session_factory = db
        base_url = f"{BASE_URL}/lov-relationship"
        service = create_custom_fields_service(
            session_factory=session_factory, base_url=base_url, overrides={}, ttl_minutes=60
        )

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

        definitions = await service.refresh(clients(base_url))

        assert definitions[0].lov_set_id == "500"
        # Ordered by `position`, and the other set's entry is not mixed in.
        assert [v.label for v in definitions[0].allowed_values] == ["A", "B"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_hidden_entries_are_excluded(
        self, db: DatabaseFixture, clients: ClientBuilder
    ) -> None:
        """A value the client switched off would be refused by the Backstop UI on write."""
        _, session_factory = db
        base_url = f"{BASE_URL}/lov-hidden"
        service = create_custom_fields_service(
            session_factory=session_factory, base_url=base_url, overrides={}, ttl_minutes=60
        )

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

        definitions = await service.refresh(clients(base_url))

        assert [v.label for v in definitions[0].allowed_values] == ["Visible"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_definitions_still_load_when_lov_entries_fails(
        self, db: DatabaseFixture, clients: ClientBuilder
    ) -> None:
        """Allowed values are an enrichment; losing them must not fail the whole schema."""
        _, session_factory = db
        base_url = f"{BASE_URL}/lov-unavailable"
        service = create_custom_fields_service(
            session_factory=session_factory, base_url=base_url, overrides={}, ttl_minutes=60
        )

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

        definitions = await service.refresh(clients(base_url))

        assert [d.crm_name for d in definitions] == ["Status"]
        assert definitions[0].allowed_values == ()

    @pytest.mark.asyncio
    @respx.mock
    async def test_falls_back_to_a_side_loaded_set_carrying_its_own_entries(
        self, db: DatabaseFixture, clients: ClientBuilder
    ) -> None:
        _, session_factory = db
        base_url = f"{BASE_URL}/lov-included-entries"
        service = create_custom_fields_service(
            session_factory=session_factory, base_url=base_url, overrides={}, ttl_minutes=60
        )

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

        definitions = await service.refresh(clients(base_url))

        assert [v.label for v in definitions[0].allowed_values] == ["Warm", "Hot"]


class TestSnapshotStaleness:
    """A persisted snapshot is a cache with a TTL, not a permanent record."""

    @staticmethod
    async def _seed_snapshot(
        session_factory: async_sessionmaker[AsyncSession], base_url: str, age: timedelta
    ) -> None:
        async with transaction(session_factory) as session:
            await save_snapshot(
                session,
                base_url,
                [
                    CustomFieldDefinition(
                        definition_id="old-1",
                        entity_type="organizations",
                        crm_name="Stale Field",
                        display_name="Stale Field",
                    )
                ],
                datetime.now(UTC) - age,
            )
            await session.commit()

    @staticmethod
    def _fresh_definitions_route(base_url: str) -> respx.Route:
        lov_entries_route(base_url)
        return respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=httpx.Response(
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
            )
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_warm_read_does_not_queue_behind_an_in_flight_refresh(
        self, db: DatabaseFixture, clients: ClientBuilder
    ) -> None:
        """A fresh `load_cached()` must not block on the lock a cold refresh is holding.

        `load_cached` used to take `self._lock` merely to read `is_fresh`, and the same lock is
        held across `_refresh_unlocked`'s two full paginations — so every `tools/list` on a warm
        replica serialized behind whichever caller happened to be refreshing.
        """
        _, session_factory = db
        base_url = f"{BASE_URL}/ttl-warm-read-not-blocked"
        await self._seed_snapshot(session_factory, base_url, timedelta(minutes=5))
        service = create_custom_fields_service(
            session_factory=session_factory, base_url=base_url, overrides={}, ttl_minutes=60
        )
        await service.load_cached()
        assert service.is_fresh is True

        # Gate the refresh's upstream call so it is provably still in flight — and holding the
        # lock — while the warm read below runs.
        refresh_started = asyncio.Event()
        release_refresh = asyncio.Event()

        lov_entries_route(base_url)

        async def blocked_definitions(_request: httpx.Request) -> httpx.Response:
            refresh_started.set()
            await release_refresh.wait()
            return httpx.Response(200, json={"data": [], "links": {"next": None}})

        respx.get(f"{base_url}/custom-field-definitions").mock(side_effect=blocked_definitions)

        # `refresh()` ignores the TTL, so it takes the lock and holds it across the gated fetch.
        refresh_task = asyncio.create_task(service.refresh(clients(base_url)))
        await asyncio.wait_for(refresh_started.wait(), timeout=5)

        # The assertion: this returns rather than deadlocking on the held lock.
        await asyncio.wait_for(service.load_cached(), timeout=1)

        release_refresh.set()
        _ = await asyncio.wait_for(refresh_task, timeout=5)

    @pytest.mark.asyncio
    @respx.mock
    async def test_snapshot_within_ttl_is_not_refetched(
        self, db: DatabaseFixture, clients: ClientBuilder
    ) -> None:
        _, session_factory = db
        base_url = f"{BASE_URL}/ttl-fresh"
        await self._seed_snapshot(session_factory, base_url, timedelta(minutes=5))
        service = create_custom_fields_service(
            session_factory=session_factory, base_url=base_url, overrides={}, ttl_minutes=60
        )
        route = self._fresh_definitions_route(base_url)

        await service.ensure_fresh(clients(base_url))

        assert route.call_count == 0
        assert [d.display_name for d in service.definitions_for("organizations")] == ["Stale Field"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_snapshot_past_ttl_is_refetched(
        self, db: DatabaseFixture, clients: ClientBuilder
    ) -> None:
        _, session_factory = db
        base_url = f"{BASE_URL}/ttl-expired"
        await self._seed_snapshot(session_factory, base_url, timedelta(minutes=90))
        service = create_custom_fields_service(
            session_factory=session_factory, base_url=base_url, overrides={}, ttl_minutes=60
        )
        route = self._fresh_definitions_route(base_url)

        await service.ensure_fresh(clients(base_url))

        assert route.call_count == 1
        assert [d.display_name for d in service.definitions_for("organizations")] == ["Fresh Field"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_load_cached_reports_stale_without_fetching(self, db: DatabaseFixture) -> None:
        """The credential-free path still surfaces stale data, but flags it as not fresh."""
        _, session_factory = db
        base_url = f"{BASE_URL}/ttl-cached-only"
        await self._seed_snapshot(session_factory, base_url, timedelta(minutes=90))
        service = create_custom_fields_service(
            session_factory=session_factory, base_url=base_url, overrides={}, ttl_minutes=60
        )
        route = self._fresh_definitions_route(base_url)

        await service.load_cached()

        assert route.call_count == 0
        assert service.is_fresh is False
        assert [d.display_name for d in service.definitions_for("organizations")] == ["Stale Field"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_replica_picks_up_a_siblings_refresh_without_refetching(
        self, db: DatabaseFixture, clients: ClientBuilder
    ) -> None:
        """Freshness lives in the DB row, so one replica's fetch spares the others."""
        _, session_factory = db
        base_url = f"{BASE_URL}/ttl-two-replicas"
        await self._seed_snapshot(session_factory, base_url, timedelta(minutes=90))
        route = self._fresh_definitions_route(base_url)

        def replica() -> CustomFieldsService:
            return create_custom_fields_service(
                session_factory=session_factory,
                base_url=base_url,
                overrides={},
                ttl_minutes=60,
            )

        first, second = replica(), replica()
        # Both load the same expired snapshot into memory, as two pods would.
        await first.load_cached()
        await second.load_cached()
        assert first.is_fresh is False
        assert second.is_fresh is False

        client = clients(base_url)
        await first.ensure_fresh(client)
        await second.ensure_fresh(client)

        assert route.call_count == 1
        assert [d.display_name for d in second.definitions_for("organizations")] == ["Fresh Field"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_concurrent_first_writes_do_not_collide(
        self, db: DatabaseFixture, clients: ClientBuilder
    ) -> None:
        """Two replicas cold-starting together must not race each other onto the primary key."""
        _, session_factory = db
        base_url = f"{BASE_URL}/ttl-write-race"
        self._fresh_definitions_route(base_url)

        async def warm() -> None:
            service = create_custom_fields_service(
                session_factory=session_factory,
                base_url=base_url,
                overrides={},
                ttl_minutes=60,
            )
            await service.ensure_fresh(clients(base_url))

        await asyncio.gather(warm(), warm(), warm())

        async with read_session(session_factory) as session:
            stored = await load_snapshot(session, base_url)
        assert stored is not None
        assert [d.display_name for d in stored.definitions] == ["Fresh Field"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_stale_snapshot_survives_a_failed_refresh(
        self, db: DatabaseFixture, clients: ClientBuilder
    ) -> None:
        """Serving a stale glossary beats failing every field lookup (B7).

        `ensure_fresh` used to let the fetch error propagate, so one Backstop hiccup broke field
        resolution outright even though a week-old — and almost certainly still correct — schema
        sat in memory.
        """
        _, session_factory = db
        base_url = f"{BASE_URL}/ttl-refresh-fails"
        await self._seed_snapshot(session_factory, base_url, timedelta(minutes=90))
        service = create_custom_fields_service(
            session_factory=session_factory, base_url=base_url, overrides={}, ttl_minutes=60
        )
        lov_entries_route(base_url)
        respx.get(f"{base_url}/custom-field-definitions").mock(
            side_effect=httpx.ConnectError("backstop down")
        )

        await service.ensure_fresh(clients(base_url))

        assert [d.display_name for d in service.definitions_for("organizations")] == ["Stale Field"]
        assert service.is_fresh is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_failed_refresh_with_nothing_cached_still_raises(
        self, db: DatabaseFixture, clients: ClientBuilder
    ) -> None:
        """Tolerance only applies when there is something to fall back on."""
        _, session_factory = db
        base_url = f"{BASE_URL}/ttl-cold-failure"
        service = create_custom_fields_service(
            session_factory=session_factory, base_url=base_url, overrides={}, ttl_minutes=60
        )
        lov_entries_route(base_url)
        respx.get(f"{base_url}/custom-field-definitions").mock(
            side_effect=httpx.ConnectError("backstop down")
        )

        with pytest.raises(httpx.ConnectError):
            await service.ensure_fresh(clients(base_url))

    @pytest.mark.asyncio
    @respx.mock
    async def test_explicit_refresh_still_raises_loudly(
        self, db: DatabaseFixture, clients: ClientBuilder
    ) -> None:
        """`refresh()` is the caller asking for a fetch, so a failure must not be swallowed."""
        _, session_factory = db
        base_url = f"{BASE_URL}/ttl-explicit-refresh-fails"
        await self._seed_snapshot(session_factory, base_url, timedelta(minutes=1))
        service = create_custom_fields_service(
            session_factory=session_factory, base_url=base_url, overrides={}, ttl_minutes=60
        )
        lov_entries_route(base_url)
        respx.get(f"{base_url}/custom-field-definitions").mock(
            side_effect=httpx.ConnectError("backstop down")
        )

        with pytest.raises(httpx.ConnectError):
            await service.refresh(clients(base_url))


class TestSnapshotCodec:
    @pytest.mark.asyncio
    async def test_unreadable_payload_reads_as_a_cache_miss(self, db: DatabaseFixture) -> None:
        """A snapshot written by a different shape must not raise from inside a cache read."""
        from backstop_mcp.db.models import CustomFieldSchemaSnapshot

        _, session_factory = db
        base_url = f"{BASE_URL}/snapshot-garbage"
        async with transaction(session_factory) as session:
            session.add(
                CustomFieldSchemaSnapshot(
                    base_url=base_url,
                    payload={"version": 999, "definitions": []},
                    fetched_at=datetime.now(UTC),
                )
            )
            await session.commit()

        async with read_session(session_factory) as session:
            assert await load_snapshot(session, base_url) is None

    @pytest.mark.asyncio
    async def test_round_trips_allowed_values_and_lov_set_id(self, db: DatabaseFixture) -> None:
        from backstop_mcp.features.custom_fields.types import AllowedValue

        _, session_factory = db
        base_url = f"{BASE_URL}/snapshot-round-trip"
        definition = CustomFieldDefinition(
            definition_id="1",
            entity_type="organizations",
            crm_name="Grade",
            display_name="Investor Grade",
            aliases=("grade",),
            allowed_values=(AllowedValue(id="e1", label="A"),),
            lov_set_id="500",
        )
        async with transaction(session_factory) as session:
            await save_snapshot(session, base_url, [definition], datetime.now(UTC))

        async with read_session(session_factory) as session:
            loaded = await load_snapshot(session, base_url)

        assert loaded is not None
        assert loaded.definitions == [definition]


class TestRefreshFloor:
    """`list_custom_fields` hands the model a `refresh` flag, and one refresh is two uncapped
    paginations taken under the lock every other caller's cold path waits on."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_second_forced_refresh_inside_the_floor_does_not_hit_backstop(
        self, db: DatabaseFixture, clients: ClientBuilder
    ) -> None:
        _, factory = db
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
        service = create_custom_fields_service(
            session_factory=factory, base_url=base_url, overrides={}, ttl_minutes=60
        )

        first = await service.refresh(clients(base_url))
        second = await service.refresh(clients(base_url))

        assert route.call_count == 1
        # The floored call still answers coherently — with what is already indexed, not nothing.
        assert [d.display_name for d in second] == [d.display_name for d in first]

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_forced_refresh_past_the_floor_fetches_again(
        self, db: DatabaseFixture, clients: ClientBuilder
    ) -> None:
        _, factory = db
        base_url = f"{BASE_URL}/refresh-floor-elapsed"
        lov_entries_route(base_url)
        route = respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=httpx.Response(200, json={"data": [], "links": {"next": None}})
        )
        service = create_custom_fields_service(
            session_factory=factory, base_url=base_url, overrides={}, ttl_minutes=60
        )

        _ = await service.refresh(clients(base_url))
        # Reach in and age the attempt rather than sleeping out a real minute.
        service._refresh_attempted_at = (  # pyright: ignore[reportPrivateUsage]
            datetime.now(UTC) - service.MIN_REFRESH_INTERVAL - timedelta(seconds=1)
        )
        _ = await service.refresh(clients(base_url))

        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_a_failed_refresh_still_counts_against_the_floor(
        self, db: DatabaseFixture, clients: ClientBuilder
    ) -> None:
        """Otherwise an unreachable Backstop is re-dialled on every single request."""
        _, factory = db
        base_url = f"{BASE_URL}/refresh-floor-failure"
        lov_entries_route(base_url)
        route = respx.get(f"{base_url}/custom-field-definitions").mock(
            side_effect=httpx.ConnectError("backstop down")
        )
        service = create_custom_fields_service(
            session_factory=factory, base_url=base_url, overrides={}, ttl_minutes=60
        )

        with pytest.raises(httpx.ConnectError):
            _ = await service.refresh(clients(base_url))
        assert await service.refresh(clients(base_url)) == []

        assert route.call_count == 1
