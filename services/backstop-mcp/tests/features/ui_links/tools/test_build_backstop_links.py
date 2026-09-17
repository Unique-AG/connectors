import pytest
from pydantic import ValidationError

from backstop_mcp.features.ui_links import (
    BackstopLinksResponse,
    BuildEntityLinkUtil,
    CallLinkTarget,
    EmailLinkTarget,
    OpportunityLinkTarget,
    OrganizationLinkTarget,
    ProductLinkTarget,
    TaskLinkTarget,
    UiBaseUrlNotConfiguredResponse,
)
from backstop_mcp.features.ui_links.tools.build_backstop_links import build_backstop_links
from backstop_mcp.server.tools import TOOLS
from tests.features.ui_links.conftest import UI_BASE, path_and_query, query_params


class TestBuildBackstopLinks:
    def test_is_registered(self) -> None:
        assert build_backstop_links in TOOLS

    @pytest.mark.asyncio
    async def test_organization_returns_labeled_urls(self) -> None:
        result = await build_backstop_links(
            target=OrganizationLinkTarget(party_id="341764767"),
            build_entity_link_util=BuildEntityLinkUtil(),
            ui_base_url=UI_BASE,
        )
        assert isinstance(result, BackstopLinksResponse)
        assert result.status == "ok"
        assert result.links
        labels = [link.label for link in result.links]
        assert "Open" in labels
        assert "Summary" in labels
        assert all(link.url.startswith(f"{UI_BASE}/backstop/") for link in result.links)
        assert any("party_id=341764767" in link.url for link in result.links)

    @pytest.mark.asyncio
    async def test_task_returns_labeled_url(self) -> None:
        result = await build_backstop_links(
            target=TaskLinkTarget(task_id="2741757"),
            tabs=(),
            build_entity_link_util=BuildEntityLinkUtil(),
            ui_base_url=UI_BASE,
        )
        assert isinstance(result, BackstopLinksResponse)
        assert [link.label for link in result.links] == ["Open"]
        assert path_and_query(result.links[0].url) == (
            "/backstop/crm/Task.action?popupAddEditTask=&taskId=2741757"
            + "&workflowTaskId=&viewOnly=true"
        )

    @pytest.mark.asyncio
    async def test_email_returns_labeled_url(self) -> None:
        result = await build_backstop_links(
            target=EmailLinkTarget(entity_activity_details_id="1804463726"),
            tabs=(),
            build_entity_link_util=BuildEntityLinkUtil(),
            ui_base_url=UI_BASE,
        )
        assert isinstance(result, BackstopLinksResponse)
        assert [link.label for link in result.links] == ["Open"]
        assert path_and_query(result.links[0].url) == (
            "/backstop/crm/collaboration/DisplayEmailMessage.action"
            + "?summaryId=1804463726&showControls=true"
        )

    @pytest.mark.asyncio
    async def test_activity_returns_labeled_url(self) -> None:
        result = await build_backstop_links(
            target=CallLinkTarget(entity_activity_details_id="76777353"),
            tabs=(),
            build_entity_link_util=BuildEntityLinkUtil(),
            ui_base_url=UI_BASE,
        )
        assert isinstance(result, BackstopLinksResponse)
        assert [link.label for link in result.links] == ["Open"]
        assert path_and_query(result.links[0].url) == "/backstop/activities.jsp/calls/76777353"

    @pytest.mark.asyncio
    async def test_product_summary_has_no_view_type_summary(self) -> None:
        result = await build_backstop_links(
            target=ProductLinkTarget(entity_id="123456789"),
            build_entity_link_util=BuildEntityLinkUtil(),
            ui_base_url=UI_BASE,
        )
        assert isinstance(result, BackstopLinksResponse)
        assert result.links
        for link in result.links:
            assert query_params(link.url).get("viewType") != "summary"
            assert "viewType=summary" not in link.url

    @pytest.mark.asyncio
    async def test_empty_tabs_returns_canonical_only(self) -> None:
        result = await build_backstop_links(
            target=OrganizationLinkTarget(party_id="341764767"),
            tabs=(),
            build_entity_link_util=BuildEntityLinkUtil(),
            ui_base_url=UI_BASE,
        )
        assert isinstance(result, BackstopLinksResponse)
        assert [link.label for link in result.links] == ["Open"]
        assert "viewType" not in query_params(result.links[0].url)

    @pytest.mark.asyncio
    async def test_unset_ui_base_url_is_not_configured(self) -> None:
        result = await build_backstop_links(
            target=OrganizationLinkTarget(party_id="341764767"),
            build_entity_link_util=BuildEntityLinkUtil(),
            ui_base_url=None,
        )
        assert isinstance(result, UiBaseUrlNotConfiguredResponse)
        assert result.status == "not_configured"

    @pytest.mark.asyncio
    async def test_layout_from_layout_name_and_view_entity_type(self) -> None:
        result = await build_backstop_links(
            target=OpportunityLinkTarget(entity_id="5755163"),
            tabs=(),
            layout_name="Master Pipeline",
            view_entity_type="OpportunityBean",
            build_entity_link_util=BuildEntityLinkUtil(),
            ui_base_url=UI_BASE,
        )
        assert isinstance(result, BackstopLinksResponse)
        assert result.links[-1].label == "Master Pipeline"
        assert path_and_query(result.links[-1].url) == (
            "/backstop/crm/Opportunity.action?display=&viewEntityType=OpportunityBean"
            + "&entityId=5755163&layoutName=Master+Pipeline"
        )

    def test_email_target_rejects_activity_id(self) -> None:
        with pytest.raises(ValidationError):
            EmailLinkTarget.model_validate({"kind": "email", "activity_id": "1804463726"})
