import os
from collections.abc import AsyncGenerator, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from fastmcp.tools.base import Tool
from mcp.server.auth.provider import AccessToken
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from backstop_mcp.backstop_client import BackstopClientFactory
from backstop_mcp.backstop_client.credential import BackstopCredentialSecret
from backstop_mcp.db.engine import transaction
from backstop_mcp.features.auth.context import BackstopAuthContext
from backstop_mcp.features.auth.credential_store import save_credential
from backstop_mcp.features.custom_fields import (
    CustomFieldsService,
    FieldOverride,
    create_custom_fields_service,
)
from backstop_mcp.features.custom_fields.store import save_snapshot
from backstop_mcp.features.custom_fields.types import CustomFieldDefinition
from backstop_mcp.server.middleware.custom_field_glossary import CustomFieldGlossaryMiddleware
from tests.helpers import client_factory, resource

type DatabaseFixture = tuple[AsyncEngine, async_sessionmaker[AsyncSession]]


@dataclass(frozen=True)
class Wired:
    """What one `wire()` call built. `service` is exposed for staleness assertions."""

    service: CustomFieldsService
    middleware: CustomFieldGlossaryMiddleware


type ServiceBuilder = Callable[..., Wired]

# The real registry's scope for `get_organization`. Stated literally rather than imported so these
# tests exercise the middleware's own behaviour, not the registry's —
# `TestGlossaryScopesComeFromTheToolRegistry` below is what pins the two together.
_ORG_SCOPES: Mapping[str, tuple[str, ...]] = {"get_organization": ("organizations",)}


async def _noop_revoke(_subject: str) -> None:
    return None


@pytest.fixture
async def wire(db: DatabaseFixture) -> AsyncGenerator[ServiceBuilder]:
    """Build a service + middleware pair the way `create_app` does, for one Backstop base URL.

    Collaborators are injected, so nothing process-wide is installed: the middleware under test
    is handed exactly the service and client provider built here.
    """
    _, session_factory = db
    built: list[BackstopClientFactory] = []

    def wire_up(
        base_url: str,
        *,
        overrides: dict[str, FieldOverride] | None = None,
        encryption_key: bytes | None = None,
        glossary_entities: Mapping[str, tuple[str, ...]] | None = None,
    ) -> Wired:
        factory = client_factory(
            base_url,
            auth=BackstopAuthContext(
                session_factory=session_factory,
                encryption_key=encryption_key if encryption_key is not None else os.urandom(32),
                revoke_tokens_for_subject=_noop_revoke,
            ),
        )
        built.append(factory)
        service = create_custom_fields_service(
            session_factory=session_factory,
            base_url=base_url,
            overrides=overrides or {},
            ttl_minutes=60,
        )
        middleware = CustomFieldGlossaryMiddleware(
            service,
            client_for_caller=factory.for_current_caller,
            glossary_entities=glossary_entities if glossary_entities is not None else _ORG_SCOPES,
        )
        return Wired(service=service, middleware=middleware)

    yield wire_up
    for factory in built:
        await factory.aclose()


async def _store_credential(
    session_factory: async_sessionmaker[AsyncSession], subject: str, key: bytes
) -> None:
    """Store a Backstop credential for `subject`.

    `backstop_username` is globally unique and the test Postgres persists across the whole
    session, so the username is derived from `subject` rather than shared.
    """
    async with session_factory() as session:
        await save_credential(
            session,
            subject,
            BackstopCredentialSecret(
                username=f"list-bob-{subject}", api_token=SecretStr("list-token")
            ),
            key,
        )
        await session.commit()


def _authenticate_as(monkeypatch: pytest.MonkeyPatch, subject: str) -> None:
    monkeypatch.setattr(
        "backstop_mcp.features.auth.context.get_access_token",
        lambda: AccessToken(token="access-token", client_id="client-1", scopes=[], subject=subject),
    )


def _lov_entries_route(base_url: str) -> respx.Route:
    return respx.get(f"{base_url}/lov-entries").mock(
        return_value=httpx.Response(200, json={"data": [], "links": {"next": None}})
    )


async def _one_org_tool(_context: object) -> list[Tool]:
    return [
        Tool.from_function(
            lambda: None,
            name="get_organization",
            description="Fetch an organization.",
        )
    ]


def _definition(
    definition_id: str, display_name: str, entity_type: str = "organizations"
) -> CustomFieldDefinition:
    return CustomFieldDefinition(
        definition_id=definition_id,
        entity_type=entity_type,
        crm_name="is1",
        display_name=display_name,
    )


class TestGlossaryMiddleware:
    @pytest.mark.asyncio
    async def test_appends_org_glossary_only_to_registered_tools(
        self, db: DatabaseFixture, wire: ServiceBuilder
    ) -> None:
        _, session_factory = db
        base_url = "https://example.backstopsolutions.com/glossary"
        async with transaction(session_factory) as session:
            await save_snapshot(
                session,
                base_url,
                [
                    CustomFieldDefinition(
                        definition_id="1",
                        entity_type="organizations",
                        crm_name="is1",
                        display_name="Investor Status",
                        aliases=("status",),
                    ),
                    CustomFieldDefinition(
                        definition_id="2",
                        entity_type="people",
                        crm_name="Title",
                        display_name="Title",
                    ),
                ],
                datetime.now(UTC),
            )

        wired = wire(
            base_url,
            overrides={
                "organizations:1:is1": FieldOverride(
                    display_name="Investor Status",
                    aliases=("status",),
                )
            },
        )

        async def call_next(_context: object) -> list[Tool]:
            return [
                Tool.from_function(
                    lambda: None,
                    name="get_organization",
                    description="Fetch an organization.",
                ),
                Tool.from_function(
                    lambda: None,
                    name="get_system_info",
                    description="System info.",
                ),
            ]

        tools = await wired.middleware.on_list_tools(None, call_next)  # pyright: ignore[reportArgumentType]

        org_tool = next(t for t in tools if t.name == "get_organization")
        sys_tool = next(t for t in tools if t.name == "get_system_info")

        assert org_tool.description is not None
        assert "Investor Status" in org_tool.description
        assert "Title" not in org_tool.description
        assert sys_tool.description == "System info."

    @pytest.mark.asyncio
    @respx.mock
    async def test_cold_cache_warms_from_the_listing_caller(
        self, db: DatabaseFixture, wire: ServiceBuilder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With no snapshot, the first authenticated tools/list fetches the schema itself."""
        _, session_factory = db
        base_url = "https://example.backstopsolutions.com/list-warm"
        key = os.urandom(32)
        await _store_credential(session_factory, "user-list-1", key)
        _authenticate_as(monkeypatch, "user-list-1")
        wired = wire(base_url, encryption_key=key)

        _lov_entries_route(base_url)
        route = respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        resource(
                            "801",
                            "custom-field-definitions",
                            name="Investor Status",
                            entityType="Organization",
                            fieldType="text",
                            isTimeSeries=False,
                        )
                    ],
                    "links": {"next": None},
                },
            )
        )

        tools = await wired.middleware.on_list_tools(None, _one_org_tool)  # pyright: ignore[reportArgumentType]

        assert route.call_count == 1
        org_tool = next(t for t in tools if t.name == "get_organization")
        assert org_tool.description is not None
        assert "Investor Status" in org_tool.description

    @pytest.mark.asyncio
    @respx.mock
    async def test_warm_failure_degrades_instead_of_failing_the_listing(
        self, db: DatabaseFixture, wire: ServiceBuilder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With nothing cached and Backstop down, descriptions stay bare rather than guessing."""
        _, session_factory = db
        base_url = "https://example.backstopsolutions.com/list-outage"
        key = os.urandom(32)
        await _store_credential(session_factory, "user-list-2", key)
        _authenticate_as(monkeypatch, "user-list-2")
        wired = wire(base_url, encryption_key=key)

        _lov_entries_route(base_url)
        respx.get(f"{base_url}/custom-field-definitions").mock(
            side_effect=httpx.ConnectError("backstop down")
        )

        tools = await wired.middleware.on_list_tools(None, _one_org_tool)  # pyright: ignore[reportArgumentType]

        org_tool = next(t for t in tools if t.name == "get_organization")
        assert org_tool.description == "Fetch an organization."

    @pytest.mark.asyncio
    @respx.mock
    async def test_backstop_outage_falls_back_to_the_stale_db_snapshot(
        self, db: DatabaseFixture, wire: ServiceBuilder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An expired snapshot still beats no glossary when the refresh can't reach Backstop."""
        _, session_factory = db
        base_url = "https://example.backstopsolutions.com/list-outage-stale"
        async with transaction(session_factory) as session:
            await save_snapshot(
                session,
                base_url,
                [_definition("950", "Investor Status")],
                datetime.now(UTC) - timedelta(days=30),
            )
            await session.commit()

        key = os.urandom(32)
        await _store_credential(session_factory, "user-list-4", key)
        _authenticate_as(monkeypatch, "user-list-4")
        wired = wire(base_url, encryption_key=key)
        service = wired.service

        _lov_entries_route(base_url)
        route = respx.get(f"{base_url}/custom-field-definitions").mock(
            side_effect=httpx.ConnectError("backstop down")
        )

        tools = await wired.middleware.on_list_tools(None, _one_org_tool)  # pyright: ignore[reportArgumentType]

        # It genuinely tried to refresh the expired snapshot, failed, and served it anyway.
        assert route.called
        assert service.is_fresh is False
        org_tool = next(t for t in tools if t.name == "get_organization")
        assert org_tool.description is not None
        assert "Investor Status" in org_tool.description

    @pytest.mark.asyncio
    @respx.mock
    async def test_unauthenticated_listing_degrades(
        self, wire: ServiceBuilder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No resolvable caller credential is still not a reason to fail the listing."""
        monkeypatch.setattr("backstop_mcp.features.auth.context.get_access_token", lambda: None)
        wired = wire("https://example.backstopsolutions.com/list-noauth")

        tools = await wired.middleware.on_list_tools(None, _one_org_tool)  # pyright: ignore[reportArgumentType]

        org_tool = next(t for t in tools if t.name == "get_organization")
        assert org_tool.description == "Fetch an organization."

    @pytest.mark.asyncio
    @respx.mock
    async def test_overrides_alone_never_produce_a_glossary(
        self, db: DatabaseFixture, wire: ServiceBuilder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Backstop returning zero definitions must not fall back to env overrides."""
        _, session_factory = db
        base_url = "https://example.backstopsolutions.com/list-empty"
        key = os.urandom(32)
        await _store_credential(session_factory, "user-list-3", key)
        _authenticate_as(monkeypatch, "user-list-3")
        wired = wire(
            base_url,
            encryption_key=key,
            overrides={
                "organizations:is1": FieldOverride(
                    display_name="Investor Status",
                    aliases=("status",),
                )
            },
        )

        _lov_entries_route(base_url)
        respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=httpx.Response(200, json={"data": [], "links": {"next": None}})
        )

        tools = await wired.middleware.on_list_tools(None, _one_org_tool)  # pyright: ignore[reportArgumentType]

        org_tool = next(t for t in tools if t.name == "get_organization")
        assert org_tool.description == "Fetch an organization."

    @pytest.mark.asyncio
    @respx.mock
    async def test_existing_snapshot_needs_no_credential(
        self, db: DatabaseFixture, wire: ServiceBuilder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A warm cache must not pay for a credential decrypt on every listing."""
        _, session_factory = db
        base_url = "https://example.backstopsolutions.com/list-warm-cache"
        async with transaction(session_factory) as session:
            await save_snapshot(
                session, base_url, [_definition("900", "Investor Status")], datetime.now(UTC)
            )

        def _explode() -> AccessToken:
            raise AssertionError("tools/list must not resolve a credential when already warm")

        monkeypatch.setattr("backstop_mcp.features.auth.context.get_access_token", _explode)
        wired = wire(base_url)

        tools = await wired.middleware.on_list_tools(None, _one_org_tool)  # pyright: ignore[reportArgumentType]

        org_tool = next(t for t in tools if t.name == "get_organization")
        assert org_tool.description is not None
        assert "Investor Status" in org_tool.description


class TestGlossaryScopesComeFromTheToolRegistry:
    def test_registry_derives_names_from_the_functions_it_references(self) -> None:
        """A renamed tool can't silently lose its glossary: the name is derived, not restated."""
        from backstop_mcp.server.tools.get_organization import get_organization
        from backstop_mcp.server.tools.registry import TOOL_SPECS, glossary_entities_by_tool_name

        scopes = glossary_entities_by_tool_name()
        assert scopes["get_organization"] == ("organizations",)
        assert "get_system_info" not in scopes
        assert any(spec.fn is get_organization for spec in TOOL_SPECS)
