import pytest
from fastmcp.tools.base import Tool
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from backstop_mcp.config import CustomFieldOverrideConfig
from backstop_mcp.custom_fields import (
    configure_custom_fields_service,
    create_custom_fields_service,
)
from backstop_mcp.custom_fields.middleware import CustomFieldGlossaryMiddleware
from backstop_mcp.custom_fields.store import save_snapshot
from backstop_mcp.custom_fields.types import CustomFieldDefinition
from backstop_mcp.db.engine import get_session

type DatabaseFixture = tuple[AsyncEngine, async_sessionmaker[AsyncSession]]


class TestGlossaryMiddleware:
    @pytest.mark.asyncio
    async def test_appends_org_glossary_only_to_registered_tools(
        self, db: DatabaseFixture
    ) -> None:
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
            )

        service = create_custom_fields_service(
            session_factory=factory,
            base_url=base_url,
            overrides={
                "organizations:1:is1": CustomFieldOverrideConfig(
                    display_name="Investor Status",
                    aliases=["status"],
                )
            },
        )
        configure_custom_fields_service(service)
        await service.ensure_loaded(client=None)

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
