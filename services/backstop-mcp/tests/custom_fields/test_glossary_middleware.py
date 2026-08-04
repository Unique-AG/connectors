import os
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from fastmcp.tools.base import Tool
from mcp.server.auth.provider import AccessToken
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from backstop_mcp.auth import context as auth_context
from backstop_mcp.auth.credential_store import save_credential
from backstop_mcp.auth.crypto import BackstopCredentialSecret
from backstop_mcp.config import CustomFieldOverrideConfig
from backstop_mcp.custom_fields import (
    configure_custom_fields_service,
    create_custom_fields_service,
)
from backstop_mcp.custom_fields.middleware import CustomFieldGlossaryMiddleware
from backstop_mcp.custom_fields.store import save_snapshot
from backstop_mcp.custom_fields.types import CustomFieldDefinition
from backstop_mcp.db.engine import get_session
from tests.party_resolver.helpers import resource

type DatabaseFixture = tuple[AsyncEngine, async_sessionmaker[AsyncSession]]


async def _connect_user(db: DatabaseFixture, subject: str) -> None:
    """Store a Backstop credential for `subject` and point auth.context at this test's DB.

    `backstop_username` is globally unique and the test Postgres persists across the whole
    session, so the username is derived from `subject` rather than shared.
    """
    _, factory = db
    key = os.urandom(32)

    async def _noop_revoke(_subject: str) -> None:
        return None

    auth_context.configure(
        auth_context.BackstopAuthContext(
            session_factory=factory,
            encryption_key=key,
            revoke_tokens_for_subject=_noop_revoke,
        )
    )
    async with factory() as session:
        await save_credential(
            session,
            subject,
            BackstopCredentialSecret(
                username=f"list-bob-{subject}", api_token=SecretStr("list-token")
            ),
            key,
        )
        await session.commit()


async def _one_org_tool(_context: object) -> list[Tool]:
    return [
        Tool.from_function(
            lambda: None,
            name="get_organization",
            description="Fetch an organization.",
        )
    ]


class TestGlossaryMiddleware:
    @pytest.mark.asyncio
    async def test_appends_org_glossary_only_to_registered_tools(self, db: DatabaseFixture) -> None:
        _, factory = db
        base_url = "https://example.backstopsolutions.com/glossary"
        async with get_session(factory) as session:
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

        service = create_custom_fields_service(
            session_factory=factory,
            base_url=base_url,
            ttl_minutes=60,
            overrides={
                "organizations:1:is1": CustomFieldOverrideConfig(
                    display_name="Investor Status",
                    aliases=["status"],
                )
            },
        )
        configure_custom_fields_service(service)
        await service.load_cached()

        middleware = CustomFieldGlossaryMiddleware()

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

        tools = await middleware.on_list_tools(None, call_next)  # pyright: ignore[reportArgumentType]

        org_tool = next(t for t in tools if t.name == "get_organization")
        sys_tool = next(t for t in tools if t.name == "get_system_info")

        assert org_tool.description is not None
        assert "Investor Status" in org_tool.description
        assert "Title" not in org_tool.description
        assert sys_tool.description == "System info."

    @pytest.mark.asyncio
    @respx.mock
    async def test_cold_cache_warms_from_the_listing_caller(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With no snapshot, the first authenticated tools/list fetches the schema itself."""
        _, factory = db
        base_url = "https://example.backstopsolutions.com/list-warm"
        await _connect_user(db, "user-list-1")
        monkeypatch.setattr(
            "backstop_mcp.auth.context.get_access_token",
            lambda: AccessToken(
                token="access-token", client_id="client-1", scopes=[], subject="user-list-1"
            ),
        )
        monkeypatch.setenv("BACKSTOP_BASE_URL", base_url)
        service = create_custom_fields_service(
            session_factory=factory, base_url=base_url, overrides={}, ttl_minutes=60
        )
        configure_custom_fields_service(service)

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

        tools = await CustomFieldGlossaryMiddleware().on_list_tools(None, _one_org_tool)  # pyright: ignore[reportArgumentType]

        assert route.call_count == 1
        org_tool = next(t for t in tools if t.name == "get_organization")
        assert org_tool.description is not None
        assert "Investor Status" in org_tool.description

    @pytest.mark.asyncio
    @respx.mock
    async def test_warm_failure_degrades_instead_of_failing_the_listing(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With nothing cached and Backstop down, descriptions stay bare rather than guessing."""
        _, factory = db
        base_url = "https://example.backstopsolutions.com/list-outage"
        await _connect_user(db, "user-list-2")
        monkeypatch.setattr(
            "backstop_mcp.auth.context.get_access_token",
            lambda: AccessToken(
                token="access-token", client_id="client-1", scopes=[], subject="user-list-2"
            ),
        )
        monkeypatch.setenv("BACKSTOP_BASE_URL", base_url)
        service = create_custom_fields_service(
            session_factory=factory, base_url=base_url, overrides={}, ttl_minutes=60
        )
        configure_custom_fields_service(service)

        respx.get(f"{base_url}/custom-field-definitions").mock(
            side_effect=httpx.ConnectError("backstop down")
        )

        tools = await CustomFieldGlossaryMiddleware().on_list_tools(None, _one_org_tool)  # pyright: ignore[reportArgumentType]

        org_tool = next(t for t in tools if t.name == "get_organization")
        assert org_tool.description == "Fetch an organization."

    @pytest.mark.asyncio
    @respx.mock
    async def test_backstop_outage_falls_back_to_the_stale_db_snapshot(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An expired snapshot still beats no glossary when the refresh can't reach Backstop."""
        _, factory = db
        base_url = "https://example.backstopsolutions.com/list-outage-stale"
        async with get_session(factory) as session:
            await save_snapshot(
                session,
                base_url,
                [
                    CustomFieldDefinition(
                        definition_id="950",
                        entity_type="organizations",
                        crm_name="is1",
                        display_name="Investor Status",
                    )
                ],
                datetime.now(UTC) - timedelta(days=30),
            )
            await session.commit()

        await _connect_user(db, "user-list-4")
        monkeypatch.setattr(
            "backstop_mcp.auth.context.get_access_token",
            lambda: AccessToken(
                token="access-token", client_id="client-1", scopes=[], subject="user-list-4"
            ),
        )
        monkeypatch.setenv("BACKSTOP_BASE_URL", base_url)
        service = create_custom_fields_service(
            session_factory=factory, base_url=base_url, overrides={}, ttl_minutes=60
        )
        configure_custom_fields_service(service)

        route = respx.get(f"{base_url}/custom-field-definitions").mock(
            side_effect=httpx.ConnectError("backstop down")
        )

        tools = await CustomFieldGlossaryMiddleware().on_list_tools(None, _one_org_tool)  # pyright: ignore[reportArgumentType]

        # It genuinely tried to refresh the expired snapshot, failed, and served it anyway.
        assert route.called
        assert service.is_fresh is False
        org_tool = next(t for t in tools if t.name == "get_organization")
        assert org_tool.description is not None
        assert "Investor Status" in org_tool.description

    @pytest.mark.asyncio
    @respx.mock
    async def test_unauthenticated_listing_degrades(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No resolvable caller credential is still not a reason to fail the listing."""
        _, factory = db
        base_url = "https://example.backstopsolutions.com/list-noauth"
        monkeypatch.setattr("backstop_mcp.auth.context.get_access_token", lambda: None)
        service = create_custom_fields_service(
            session_factory=factory, base_url=base_url, overrides={}, ttl_minutes=60
        )
        configure_custom_fields_service(service)

        tools = await CustomFieldGlossaryMiddleware().on_list_tools(None, _one_org_tool)  # pyright: ignore[reportArgumentType]

        org_tool = next(t for t in tools if t.name == "get_organization")
        assert org_tool.description == "Fetch an organization."

    @pytest.mark.asyncio
    @respx.mock
    async def test_overrides_alone_never_produce_a_glossary(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Backstop returning zero definitions must not fall back to env overrides."""
        _, factory = db
        base_url = "https://example.backstopsolutions.com/list-empty"
        await _connect_user(db, "user-list-3")
        monkeypatch.setattr(
            "backstop_mcp.auth.context.get_access_token",
            lambda: AccessToken(
                token="access-token", client_id="client-1", scopes=[], subject="user-list-3"
            ),
        )
        monkeypatch.setenv("BACKSTOP_BASE_URL", base_url)
        service = create_custom_fields_service(
            session_factory=factory,
            base_url=base_url,
            ttl_minutes=60,
            overrides={
                "organizations:is1": CustomFieldOverrideConfig(
                    display_name="Investor Status",
                    aliases=["status"],
                )
            },
        )
        configure_custom_fields_service(service)

        respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=httpx.Response(200, json={"data": [], "links": {"next": None}})
        )

        tools = await CustomFieldGlossaryMiddleware().on_list_tools(None, _one_org_tool)  # pyright: ignore[reportArgumentType]

        org_tool = next(t for t in tools if t.name == "get_organization")
        assert org_tool.description == "Fetch an organization."

    @pytest.mark.asyncio
    @respx.mock
    async def test_existing_snapshot_needs_no_credential(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A warm cache must not pay for a credential decrypt on every listing."""
        _, factory = db
        base_url = "https://example.backstopsolutions.com/list-warm-cache"
        async with get_session(factory) as session:
            await save_snapshot(
                session,
                base_url,
                [
                    CustomFieldDefinition(
                        definition_id="900",
                        entity_type="organizations",
                        crm_name="is1",
                        display_name="Investor Status",
                    )
                ],
                datetime.now(UTC),
            )

        def _explode() -> AccessToken:
            raise AssertionError("tools/list must not resolve a credential when already warm")

        monkeypatch.setattr("backstop_mcp.auth.context.get_access_token", _explode)
        service = create_custom_fields_service(
            session_factory=factory, base_url=base_url, overrides={}, ttl_minutes=60
        )
        configure_custom_fields_service(service)

        tools = await CustomFieldGlossaryMiddleware().on_list_tools(None, _one_org_tool)  # pyright: ignore[reportArgumentType]

        org_tool = next(t for t in tools if t.name == "get_organization")
        assert org_tool.description is not None
        assert "Investor Status" in org_tool.description
