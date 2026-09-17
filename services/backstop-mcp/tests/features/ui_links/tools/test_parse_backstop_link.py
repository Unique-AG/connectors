import pytest

from backstop_mcp.features.ui_links import (
    BackstopUiPage,
    ParsedBackstopLinkResponse,
    ParseEntityLinkUtil,
    UnrecognizedBackstopUrlResponse,
)
from backstop_mcp.features.ui_links.tools.parse_backstop_link import parse_backstop_link
from backstop_mcp.server.tools import TOOLS
from tests.features.ui_links.conftest import UI_BASE


class TestParseBackstopLink:
    def test_is_registered(self) -> None:
        assert parse_backstop_link in TOOLS

    @pytest.mark.asyncio
    async def test_parses_a_pinned_organization_url(self) -> None:
        result = await parse_backstop_link(
            url=(
                f"{UI_BASE}/backstop/crm/ManageOrganization.action"
                + "?display=&party_id=341764767&viewType=summary"
            ),
            parse_entity_link_util=ParseEntityLinkUtil(),
            ui_base_url=UI_BASE,
        )
        assert isinstance(result, ParsedBackstopLinkResponse)
        assert result.status == "ok"
        assert result.page == BackstopUiPage.ORGANIZATION
        assert result.entity_kind == "organization"
        assert result.entity_id == "341764767"
        assert result.tab == "summary"
        assert result.suggested_tool == "get_organization"
        assert result.host_mismatch is False

    @pytest.mark.asyncio
    async def test_junk_is_unrecognized(self) -> None:
        result = await parse_backstop_link(
            url="https://example.test/other",
            parse_entity_link_util=ParseEntityLinkUtil(),
            ui_base_url=UI_BASE,
        )
        assert isinstance(result, UnrecognizedBackstopUrlResponse)
        assert result.status == "unrecognized"

    @pytest.mark.asyncio
    async def test_mismatched_host_is_reported_and_still_parsed(self) -> None:
        result = await parse_backstop_link(
            url="https://other.example.test/backstop/crm/ManageOrganization.action?party_id=341764767",
            parse_entity_link_util=ParseEntityLinkUtil(),
            ui_base_url=UI_BASE,
        )
        assert isinstance(result, ParsedBackstopLinkResponse)
        assert result.host_mismatch is True
        assert result.entity_id == "341764767"
        assert result.entity_kind == "organization"

    @pytest.mark.asyncio
    async def test_parses_without_ui_base_url(self) -> None:
        result = await parse_backstop_link(
            url=f"{UI_BASE}/backstop/crm/ManageOrganization.action?party_id=341764767",
            parse_entity_link_util=ParseEntityLinkUtil(),
            ui_base_url=None,
        )
        assert isinstance(result, ParsedBackstopLinkResponse)
        assert result.host_mismatch is False
        assert result.entity_id == "341764767"
        assert result.suggested_tool == "get_organization"

    @pytest.mark.asyncio
    async def test_task_does_not_suggest_get_tasks_for_party(self) -> None:
        result = await parse_backstop_link(
            url=f"{UI_BASE}/backstop/crm/Task.action?taskId=2741757",
            parse_entity_link_util=ParseEntityLinkUtil(),
            ui_base_url=UI_BASE,
        )
        assert isinstance(result, ParsedBackstopLinkResponse)
        assert result.suggested_tool is None
        assert result.suggested_note is not None
        assert "get_tasks_for_party" in result.suggested_note
        assert result.entity_id == "2741757"
