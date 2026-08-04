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
from backstop_mcp.custom_fields.store import load_snapshot
from backstop_mcp.custom_fields.types import FieldResolved
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
        assert loaded[0].definition_id == "99"

        result = await service.resolve(
            entity_type="organizations", query="Investor Status", client=None
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
