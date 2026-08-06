import os
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

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
    glossary_meta,
    parse_glossary_entities,
)
from backstop_mcp.features.custom_fields.store import save_snapshot
from backstop_mcp.features.custom_fields.types import CustomFieldDefinition
from backstop_mcp.features.entity_types import EntityType
from backstop_mcp.server.middleware.custom_field_glossary import CustomFieldGlossaryMiddleware
from tests.helpers import client_factory, resource

type DatabaseFixture = tuple[AsyncEngine, async_sessionmaker[AsyncSession]]


@dataclass(frozen=True)
class Wired:
    """What one `wire()` call built. `service` is exposed for staleness assertions."""

    service: CustomFieldsService
    middleware: CustomFieldGlossaryMiddleware


type ServiceBuilder = Callable[..., Wired]


async def _noop_revoke(_subject: str) -> None:
    return None


@pytest.fixture
async def wire(db: DatabaseFixture) -> AsyncGenerator[ServiceBuilder]:
    """Build a service + middleware pair the way `create_app` does, for one Backstop base URL."""
    _, session_factory = db
    built: list[BackstopClientFactory] = []

    def wire_up(
        base_url: str,
        *,
        overrides: dict[str, FieldOverride] | None = None,
        encryption_key: bytes | None = None,
        tools_list_description_budget_chars: int | None = None,
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
        kwargs: dict[str, object] = {}
        if tools_list_description_budget_chars is not None:
            kwargs["tools_list_description_budget_chars"] = tools_list_description_budget_chars
        middleware = CustomFieldGlossaryMiddleware(
            service,
            client_for_caller=factory.for_current_caller,
            **kwargs,  # pyright: ignore[reportArgumentType]
        )
        return Wired(service=service, middleware=middleware)

    yield wire_up
    for factory in built:
        await factory.aclose()


async def _store_credential(
    session_factory: async_sessionmaker[AsyncSession], subject: str, key: bytes
) -> None:
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


def _tool(
    name: str,
    description: str,
    *,
    entities: tuple[EntityType, ...] = (),
) -> Tool:
    return Tool.from_function(
        lambda: None,
        name=name,
        description=description,
        meta=glossary_meta(*entities) if entities else None,
    )


async def _one_org_tool(_context: object) -> list[Tool]:
    return [
        _tool("get_organization", "Fetch an organization.", entities=(EntityType.ORGANIZATIONS,))
    ]


class TestGlossaryMiddleware:
    @pytest.mark.asyncio
    async def test_appends_org_glossary_only_to_tools_with_meta(
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
                _tool(
                    "get_organization",
                    "Fetch an organization.",
                    entities=(EntityType.ORGANIZATIONS,),
                ),
                _tool("get_system_info", "System info."),
            ]

        tools = await wired.middleware.on_list_tools(None, call_next)  # pyright: ignore[reportArgumentType]

        org_tool = next(t for t in tools if t.name == "get_organization")
        sys_tool = next(t for t in tools if t.name == "get_system_info")

        assert org_tool.description is not None
        assert "Investor Status" in org_tool.description
        assert "Title" not in org_tool.description
        assert sys_tool.description == "System info."

    @pytest.mark.asyncio
    async def test_caps_total_description_budget_across_tools(
        self, db: DatabaseFixture, wire: ServiceBuilder
    ) -> None:
        _, session_factory = db
        base_url = "https://example.backstopsolutions.com/glossary-budget"
        definitions = [
            CustomFieldDefinition(
                definition_id=str(i),
                entity_type="organizations",
                crm_name=f"f{i}",
                display_name=f"Field {i} " + ("x" * 40),
            )
            for i in range(40)
        ]
        async with transaction(session_factory) as session:
            await save_snapshot(session, base_url, definitions, datetime.now(UTC))

        wired = wire(base_url, tools_list_description_budget_chars=200)

        async def call_next(_context: object) -> list[Tool]:
            return [
                _tool("a", "AAAA", entities=(EntityType.ORGANIZATIONS,)),
                _tool("b", "BBBB", entities=(EntityType.ORGANIZATIONS,)),
            ]

        tools = await wired.middleware.on_list_tools(None, call_next)  # pyright: ignore[reportArgumentType]
        total = sum(len(t.description or "") for t in tools)
        assert total <= 200

    @pytest.mark.asyncio
    @respx.mock
    async def test_cold_cache_warms_from_the_listing_caller(
        self, db: DatabaseFixture, wire: ServiceBuilder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With no snapshot, the first authenticated tools/list fetches the schema itself."""
        _, session_factory = db
        base_url = "https://example.backstopsolutions.com/glossary-warm"
        key = os.urandom(32)
        await _store_credential(session_factory, "user-list-1", key)
        _authenticate_as(monkeypatch, "user-list-1")
        _lov_entries_route(base_url)
        respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        resource(
                            "1",
                            "custom-field-definitions",
                            name="is1",
                            entityType="Organization",
                        )
                    ],
                    "links": {"next": None},
                },
            )
        )
        wired = wire(base_url, encryption_key=key)

        tools = await wired.middleware.on_list_tools(None, _one_org_tool)  # pyright: ignore[reportArgumentType]

        org_tool = next(t for t in tools if t.name == "get_organization")
        assert org_tool.description is not None
        assert "is1" in org_tool.description or "Custom field glossary" in org_tool.description

    @pytest.mark.asyncio
    @respx.mock
    async def test_warm_failure_enters_cooldown(
        self, db: DatabaseFixture, wire: ServiceBuilder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, session_factory = db
        base_url = "https://example.backstopsolutions.com/glossary-fail"
        key = os.urandom(32)
        await _store_credential(session_factory, "user-list-2", key)
        _authenticate_as(monkeypatch, "user-list-2")
        definitions_route = respx.get(f"{base_url}/custom-field-definitions").mock(
            return_value=httpx.Response(500)
        )
        respx.get(f"{base_url}/lov-entries").mock(return_value=httpx.Response(500))
        wired = wire(base_url, encryption_key=key)

        first = await wired.middleware.on_list_tools(None, _one_org_tool)  # pyright: ignore[reportArgumentType]
        assert first[0].description == "Fetch an organization."
        assert definitions_route.call_count == 1

        # Still inside the cooldown window: no second attempt against Backstop.
        second = await wired.middleware.on_list_tools(None, _one_org_tool)  # pyright: ignore[reportArgumentType]
        assert second[0].description == "Fetch an organization."
        assert definitions_route.call_count == 1

    @pytest.mark.asyncio
    async def test_fresh_schema_skips_credential_resolution(
        self, db: DatabaseFixture, wire: ServiceBuilder, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, session_factory = db
        base_url = "https://example.backstopsolutions.com/glossary-fresh"
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
                    )
                ],
                datetime.now(UTC),
            )

        def _explode() -> AccessToken:
            raise AssertionError("tools/list must not resolve a credential when already warm")

        monkeypatch.setattr("backstop_mcp.features.auth.context.get_access_token", _explode)
        wired = wire(base_url)

        tools = await wired.middleware.on_list_tools(None, _one_org_tool)  # pyright: ignore[reportArgumentType]

        org_tool = next(t for t in tools if t.name == "get_organization")
        assert org_tool.description is not None
        assert "Investor Status" in org_tool.description


class TestGlossaryScopesComeFromToolMeta:
    def test_registered_tools_declare_scopes_on_meta(self) -> None:
        from fastmcp.tools.function_tool import ToolMeta

        from backstop_mcp.server.tools.get_organization import get_organization
        from backstop_mcp.server.tools.get_person import get_person
        from backstop_mcp.server.tools.list_custom_fields import list_custom_fields
        from backstop_mcp.server.tools.registry import TOOLS
        from backstop_mcp.server.tools.system_info import get_system_info

        assert (get_system_info, get_organization, get_person, list_custom_fields) == TOOLS

        org_meta = getattr(get_organization, "__fastmcp__", None)
        assert isinstance(org_meta, ToolMeta)
        assert parse_glossary_entities(_as_object_dict(org_meta.meta)) == (
            EntityType.ORGANIZATIONS,
        )

        person_meta = getattr(get_person, "__fastmcp__", None)
        assert isinstance(person_meta, ToolMeta)
        assert parse_glossary_entities(_as_object_dict(person_meta.meta)) == (EntityType.PEOPLE,)

        list_meta = getattr(list_custom_fields, "__fastmcp__", None)
        assert isinstance(list_meta, ToolMeta)
        assert parse_glossary_entities(_as_object_dict(list_meta.meta)) == ()


def _as_object_dict(meta: object) -> dict[str, object] | None:
    if meta is None:
        return None
    assert isinstance(meta, dict)
    return cast(dict[str, object], meta)
