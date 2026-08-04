from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from backstop_mcp.auth.crypto import BackstopCredentialSecret
from backstop_mcp.backstop_client import create_backstop_client
from backstop_mcp.config import CustomFieldOverrideConfig
from backstop_mcp.custom_fields import (
    configure_custom_fields_service,
    create_custom_fields_service,
)
from backstop_mcp.custom_fields.fetch import extract_allowed_values
from backstop_mcp.custom_fields.store import load_snapshot, save_snapshot
from backstop_mcp.custom_fields.types import CustomFieldDefinition, FieldResolved
from backstop_mcp.db.engine import get_session
from tests.party_resolver.helpers import BASE_URL, resource

type DatabaseFixture = tuple[AsyncEngine, async_sessionmaker[AsyncSession]]


def _credential() -> BackstopCredentialSecret:
    return BackstopCredentialSecret(username="schema-bob", api_token=SecretStr("token"))


class TestExtractAllowedValues:
    """Backstop returns LOV entries as either objects or bare strings, so both parse."""

    def test_string_select_options(self) -> None:
        values = extract_allowed_values(None, ["Active", " Closed ", ""])
        assert [(v.id, v.label) for v in values] == [(None, "Active"), (None, "Closed")]

    def test_string_lov_set_entries(self) -> None:
        values = extract_allowed_values(["Yes", "No"], None)
        assert [(v.id, v.label) for v in values] == [(None, "Yes"), (None, "No")]

    def test_deduplicates_across_sources(self) -> None:
        values = extract_allowed_values(["Active"], [{"id": "1", "label": "Active"}])
        assert [(v.id, v.label) for v in values] == [("1", "Active")]


class TestFetchStoreResolve:
    @pytest.mark.asyncio
    @respx.mock
    async def test_refresh_persists_snapshot_and_applies_overrides(
        self, db: DatabaseFixture
    ) -> None:
        _, factory = db
        overrides = {
            "organizations:is1": CustomFieldOverrideConfig(
                display_name="Investor Status",
                aliases=["investor status"],
            )
        }
        service = create_custom_fields_service(
            session_factory=factory,
            base_url=BASE_URL,
            overrides=overrides,
            ttl_minutes=60,
        )
        configure_custom_fields_service(service)

        respx.get(f"{BASE_URL}/custom-field-definitions").mock(
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

        async with create_backstop_client(BASE_URL, _credential()) as client:
            definitions = await service.refresh(client)

        assert len(definitions) == 1
        assert definitions[0].display_name == "Investor Status"
        assert definitions[0].aliases == ("investor status",)
        assert definitions[0].allowed_values[0].label == "Active"

        async with get_session(factory) as session:
            loaded = await load_snapshot(session, BASE_URL.rstrip("/"))
        assert loaded is not None
        assert loaded.definitions[0].definition_id == "99"

        # Resolving again hits the just-refreshed in-memory index, not Backstop — the route
        # mock above would have been called a second time otherwise.
        async with create_backstop_client(BASE_URL, _credential()) as client:
            result = await service.resolve(
                entity_type="organizations", query="Investor Status", client=client
            )
        assert isinstance(result, FieldResolved)
        assert result.definition.crm_name == "is1"

    @pytest.mark.asyncio
    @respx.mock
    async def test_second_resolve_does_not_refetch(self, db: DatabaseFixture) -> None:
        _, factory = db
        service = create_custom_fields_service(
            session_factory=factory,
            base_url=f"{BASE_URL}/tenant-a",
            overrides={},
            ttl_minutes=60,
        )
        configure_custom_fields_service(service)

        route = respx.get(f"{BASE_URL}/tenant-a/custom-field-definitions").mock(
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

        async with create_backstop_client(f"{BASE_URL}/tenant-a", _credential()) as client:
            await service.resolve(entity_type="organizations", query="Grade", client=client)
            await service.resolve(entity_type="organizations", query="Grade", client=client)

        assert route.call_count == 1


class TestSnapshotStaleness:
    """A persisted snapshot is a cache with a TTL, not a permanent record."""

    @staticmethod
    async def _seed_snapshot(
        factory: async_sessionmaker[AsyncSession], base_url: str, age: timedelta
    ) -> None:
        async with get_session(factory) as session:
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
    async def test_snapshot_within_ttl_is_not_refetched(self, db: DatabaseFixture) -> None:
        _, factory = db
        base_url = f"{BASE_URL}/ttl-fresh"
        await self._seed_snapshot(factory, base_url, timedelta(minutes=5))
        service = create_custom_fields_service(
            session_factory=factory, base_url=base_url, overrides={}, ttl_minutes=60
        )
        route = self._fresh_definitions_route(base_url)

        async with create_backstop_client(base_url, _credential()) as client:
            await service.ensure_fresh(client)

        assert route.call_count == 0
        assert [d.display_name for d in service.definitions_for("organizations")] == ["Stale Field"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_snapshot_past_ttl_is_refetched(self, db: DatabaseFixture) -> None:
        _, factory = db
        base_url = f"{BASE_URL}/ttl-expired"
        await self._seed_snapshot(factory, base_url, timedelta(minutes=90))
        service = create_custom_fields_service(
            session_factory=factory, base_url=base_url, overrides={}, ttl_minutes=60
        )
        route = self._fresh_definitions_route(base_url)

        async with create_backstop_client(base_url, _credential()) as client:
            await service.ensure_fresh(client)

        assert route.call_count == 1
        assert [d.display_name for d in service.definitions_for("organizations")] == ["Fresh Field"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_load_cached_reports_stale_without_fetching(self, db: DatabaseFixture) -> None:
        """The credential-free path still surfaces stale data, but flags it as not fresh."""
        _, factory = db
        base_url = f"{BASE_URL}/ttl-cached-only"
        await self._seed_snapshot(factory, base_url, timedelta(minutes=90))
        service = create_custom_fields_service(
            session_factory=factory, base_url=base_url, overrides={}, ttl_minutes=60
        )
        route = self._fresh_definitions_route(base_url)

        await service.load_cached()

        assert route.call_count == 0
        assert service.is_fresh is False
        assert [d.display_name for d in service.definitions_for("organizations")] == ["Stale Field"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_stale_snapshot_survives_a_failed_refresh(self, db: DatabaseFixture) -> None:
        """Serving a stale glossary beats serving none when Backstop is unreachable."""
        _, factory = db
        base_url = f"{BASE_URL}/ttl-refresh-fails"
        await self._seed_snapshot(factory, base_url, timedelta(minutes=90))
        service = create_custom_fields_service(
            session_factory=factory, base_url=base_url, overrides={}, ttl_minutes=60
        )
        respx.get(f"{base_url}/custom-field-definitions").mock(
            side_effect=httpx.ConnectError("backstop down")
        )

        with pytest.raises(httpx.ConnectError):
            async with create_backstop_client(base_url, _credential()) as client:
                await service.ensure_fresh(client)

        assert [d.display_name for d in service.definitions_for("organizations")] == ["Stale Field"]
