from backstop_mcp.features.ui_links import (
    BuildEntityLinkUtil,
    OrganizationLinkTarget,
    ProductLinkTarget,
    TaskLinkTarget,
)
from tests.features.ui_links.conftest import UI_BASE, path_and_query


def test_canonical_url_is_the_no_tab_open_link() -> None:
    url = BuildEntityLinkUtil().canonical_url(
        target=OrganizationLinkTarget(party_id="341764767"),
        ui_base_url=UI_BASE,
    )
    assert url is not None
    assert path_and_query(url) == (
        "/backstop/crm/ManageOrganization.action?display=&party_id=341764767"
    )


def test_canonical_url_omits_product_view_type() -> None:
    url = BuildEntityLinkUtil().canonical_url(
        target=ProductLinkTarget(entity_id="123456789"),
        ui_base_url=UI_BASE,
    )
    assert url is not None
    assert "viewType" not in url


def test_canonical_url_emits_task_view_only() -> None:
    url = BuildEntityLinkUtil().canonical_url(
        target=TaskLinkTarget(task_id="2741757"),
        ui_base_url=UI_BASE,
    )
    assert url is not None
    assert path_and_query(url) == (
        "/backstop/crm/Task.action?popupAddEditTask=&taskId=2741757"
        + "&workflowTaskId=&viewOnly=true"
    )


def test_canonical_url_is_none_without_ui_origin() -> None:
    assert (
        BuildEntityLinkUtil().canonical_url(
            target=OrganizationLinkTarget(party_id="341764767"),
            ui_base_url=None,
        )
        is None
    )
