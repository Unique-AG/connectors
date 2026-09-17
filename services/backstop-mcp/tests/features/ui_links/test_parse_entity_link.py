import json
from urllib.parse import quote

import pytest

from backstop_mcp.features.ui_links import (
    AccountLinkTarget,
    BackstopLinksResponse,
    BackstopLinkTarget,
    BackstopUiPage,
    BuildEntityLinkUtil,
    OpportunityLinkTarget,
    OrganizationLinkTarget,
    ParsedBackstopLinkResponse,
    ParseEntityLinkUtil,
    PersonLinkTarget,
    ProductLinkTarget,
    TaskLinkTarget,
    UiBaseUrlNotConfiguredResponse,
    UnrecognizedBackstopUrlResponse,
)
from tests.features.ui_links.conftest import UI_BASE, query_params

_BUILDER = BuildEntityLinkUtil(ui_base_url=UI_BASE)
_PARSER = ParseEntityLinkUtil(ui_base_url=None)


def test_non_backstop_url_is_unrecognized() -> None:
    parsed = _PARSER.run(url="https://example.test/other")
    assert isinstance(parsed, UnrecognizedBackstopUrlResponse)


def test_backstop_url_without_an_id_is_unrecognized() -> None:
    parsed = _PARSER.run(url=f"{UI_BASE}/backstop/crm/ManageOrganization.action")
    assert isinstance(parsed, UnrecognizedBackstopUrlResponse)


def test_unknown_activities_jsp_kind_is_unrecognized() -> None:
    parsed = _PARSER.run(url=f"{UI_BASE}/backstop/activities.jsp/unknown/76777353")
    assert isinstance(parsed, UnrecognizedBackstopUrlResponse)


def test_email_page_without_summary_id_is_unrecognized() -> None:
    parsed = _PARSER.run(
        url=f"{UI_BASE}/backstop/crm/collaboration/DisplayEmailMessage.action?showControls=true"
    )
    assert isinstance(parsed, UnrecognizedBackstopUrlResponse)


def test_host_mismatch_is_reported_and_the_url_is_still_parsed() -> None:
    url = "https://other.example.test/backstop/crm/ManageOrganization.action?party_id=341764767"
    parsed = ParseEntityLinkUtil(ui_base_url=UI_BASE).run(url=url)
    assert isinstance(parsed, ParsedBackstopLinkResponse)
    assert parsed.host_mismatch is True
    assert parsed.entity_id == "341764767"
    assert parsed.entity_kind == "organization"


def test_parser_does_not_require_ui_base_url() -> None:
    url = f"{UI_BASE}/backstop/crm/ManageOrganization.action?party_id=341764767"
    parsed = _PARSER.run(url=url)
    assert isinstance(parsed, ParsedBackstopLinkResponse)
    assert parsed.host_mismatch is False
    assert parsed.suggested_tool == "get_organization"


def test_builder_returns_not_configured_when_ui_base_url_is_unset() -> None:
    result = BuildEntityLinkUtil(ui_base_url=None).run(
        target=OrganizationLinkTarget(party_id="341764767"),
    )
    assert isinstance(result, UiBaseUrlNotConfiguredResponse)
    assert result.message == "UI base URL is not configured for this deployment"


def test_fragment_query_is_accepted() -> None:
    url = f"{UI_BASE}/backstop/crm/ManageOrganization.action#party_id=341764767&viewType=summary"
    parsed = _PARSER.run(url=url)
    assert isinstance(parsed, ParsedBackstopLinkResponse)
    assert parsed.entity_id == "341764767"
    assert parsed.tab == "summary"


def test_unknown_fragment_page_does_not_raise() -> None:
    parsed = _PARSER.run(url=f"{UI_BASE}/backstop/crm/UnknownPage.action#foo=bar")
    assert isinstance(parsed, UnrecognizedBackstopUrlResponse)


def test_display_and_view_are_ignored() -> None:
    url = (
        f"{UI_BASE}/backstop/crm/ManageOrganization.action"
        + "?display=&view=&party_id=341764767&viewType=detail"
    )
    parsed = _PARSER.run(url=url)
    assert isinstance(parsed, ParsedBackstopLinkResponse)
    assert parsed.tab == "detail"
    assert parsed.entity_id == "341764767"


def test_task_preserves_view_only_and_workflow_task_id() -> None:
    url = (
        f"{UI_BASE}/backstop/crm/Task.action"
        + "?popupAddEditTask=&taskId=2741757&workflowTaskId=99&viewOnly=true"
    )
    parsed = _PARSER.run(url=url)
    assert isinstance(parsed, ParsedBackstopLinkResponse)
    assert parsed.view_only is True
    assert parsed.workflow_task_id == "99"
    assert parsed.entity_id == "2741757"
    assert parsed.suggested_tool is None
    assert parsed.suggested_note is not None


def test_built_task_url_preserves_empty_workflow_task_id() -> None:
    result = _BUILDER.run(
        target=TaskLinkTarget(task_id="2741757"),
        tabs=(),
    )
    assert isinstance(result, BackstopLinksResponse)
    parsed = _PARSER.run(url=result.links[0].url)
    assert isinstance(parsed, ParsedBackstopLinkResponse)
    assert parsed.workflow_task_id == ""
    assert parsed.view_only is True


@pytest.mark.parametrize(
    ("target", "tabs", "expected"),
    [
        (
            OrganizationLinkTarget(party_id="341764767"),
            ("detail",),
            {"display": "", "party_id": "341764767", "viewType": "detail"},
        ),
        (
            PersonLinkTarget(party_id="412345678"),
            ("detail",),
            {"display": "", "party_id": "412345678", "viewType": "detail"},
        ),
        (
            ProductLinkTarget(entity_id="123456789"),
            (),
            {"display": "", "entityId": "123456789"},
        ),
        (
            AccountLinkTarget(entity_id="33578475"),
            ("summary",),
            {"display": "", "entityId": "33578475", "acctViewType": "summary"},
        ),
        (
            OpportunityLinkTarget(entity_id="5755163"),
            ("activity",),
            {"display": "", "entityId": "5755163", "viewType": "activity"},
        ),
    ],
)
def test_standard_entity_params_include_empty_display(
    target: BackstopLinkTarget, tabs: tuple[str, ...], expected: dict[str, str]
) -> None:
    result = _BUILDER.run(target=target, tabs=tabs)
    assert isinstance(result, BackstopLinksResponse)
    assert query_params(result.links[0].url) == expected


@pytest.mark.parametrize(
    ("kind", "tool"),
    [
        ("organization", "get_organization"),
        ("person", "get_person"),
        ("product", "get_product"),
        ("account", "get_accounts_for_party"),
        ("opportunity", "get_opportunities_by_ids"),
        ("email", "get_activity_detail"),
        ("call", "get_activity_detail"),
    ],
)
def test_suggested_tool_is_data_on_the_parsed_response(kind: str, tool: str) -> None:
    paths = {
        "organization": f"{UI_BASE}/backstop/crm/ManageOrganization.action?party_id=1",
        "person": f"{UI_BASE}/backstop/crm/ManagePerson.action?party_id=1",
        "product": f"{UI_BASE}/backstop/fundaccounting/portfolio/ManageHedgeFund.action?entityId=1",
        "account": f"{UI_BASE}/backstop/fundaccounting/ManageAccount.action?entityId=1",
        "opportunity": f"{UI_BASE}/backstop/crm/Opportunity.action?entityId=1",
        "email": f"{UI_BASE}/backstop/crm/collaboration/DisplayEmailMessage.action?summaryId=1",
        "call": f"{UI_BASE}/backstop/activities.jsp/calls/1",
    }
    parsed = _PARSER.run(url=paths[kind])
    assert isinstance(parsed, ParsedBackstopLinkResponse)
    assert parsed.suggested_tool == tool
    if kind == "account":
        assert parsed.suggested_note is not None


def test_parsed_task_url_does_not_suggest_get_tasks_for_party() -> None:
    parsed = _PARSER.run(url=f"{UI_BASE}/backstop/crm/Task.action?taskId=2741757")
    assert isinstance(parsed, ParsedBackstopLinkResponse)
    assert parsed.suggested_tool is None
    assert parsed.suggested_note is not None


def test_landing_task_does_not_suggest_get_tasks_for_party() -> None:
    url = (
        f"{UI_BASE}/backstop/utility/LandingPageUrl.action" + "?resourceType=tasks&entityId=2741757"
    )
    parsed = _PARSER.run(url=url)
    assert isinstance(parsed, ParsedBackstopLinkResponse)
    assert parsed.suggested_tool is None
    assert parsed.suggested_note is not None


def test_landing_account_keeps_party_scoped_tool_with_note() -> None:
    url = (
        f"{UI_BASE}/backstop/utility/LandingPageUrl.action"
        + "?resourceType=accounts&entityId=27871657"
    )
    parsed = _PARSER.run(url=url)
    assert isinstance(parsed, ParsedBackstopLinkResponse)
    assert parsed.suggested_tool == "get_accounts_for_party"
    assert parsed.suggested_note == "This is an account id, not a party id."


_NBSP = "\u00a0"


def _activity_search_url(related: list[dict[str, object]]) -> str:
    payload = json.dumps(related, separators=(",", ":"), ensure_ascii=False)
    fragment = f"/?inheritRelationships=true&selectedRelatedToUrl={quote(payload, safe='')}"
    return f"{UI_BASE}/backstop/search/ActivitySearch.action#{fragment}"


def test_activity_search_nbsp_name_yields_the_party() -> None:
    parsed = _PARSER.run(
        url=_activity_search_url(
            [
                {
                    "entityType": "PartyBean",
                    "name": f"Nicu{_NBSP}Test{_NBSP}Advisors{_NBSP}LLC",
                    "firstSystemDefinedType": "OrganizationBean",
                    "id": "341764767",
                    "type": "OrganizationBean",
                }
            ]
        )
    )
    assert isinstance(parsed, ParsedBackstopLinkResponse)
    assert parsed.page == BackstopUiPage.ACTIVITY_SEARCH
    assert parsed.entity_id == "341764767"
    assert parsed.entity_kind == "organization"
    assert parsed.suggested_tool == "get_organization"
    assert parsed.to_target() == OrganizationLinkTarget(party_id="341764767")


def test_activity_search_regular_spaces_in_name_are_accepted() -> None:
    parsed = _PARSER.run(
        url=_activity_search_url(
            [
                {
                    "entityType": "PartyBean",
                    "name": "Nicu Test Advisors LLC",
                    "firstSystemDefinedType": "OrganizationBean",
                    "id": "341764767",
                    "type": "OrganizationBean",
                }
            ]
        )
    )
    assert isinstance(parsed, ParsedBackstopLinkResponse)
    assert parsed.entity_id == "341764767"
    assert parsed.entity_kind == "organization"


@pytest.mark.parametrize(
    ("bean", "kind", "tool"),
    [
        ("PersonBean", "person", "get_person"),
        ("ContactBean", "person", "get_person"),
        ("EmployeeBean", "person", "get_person"),
    ],
)
def test_activity_search_person_beans_suggest_get_person(bean: str, kind: str, tool: str) -> None:
    parsed = _PARSER.run(
        url=_activity_search_url(
            [
                {
                    "entityType": "PartyBean",
                    "name": "Jane Doe",
                    "firstSystemDefinedType": bean,
                    "id": "412345678",
                    "type": bean,
                }
            ]
        )
    )
    assert isinstance(parsed, ParsedBackstopLinkResponse)
    assert parsed.entity_kind == kind
    assert parsed.suggested_tool == tool
    assert parsed.to_target() == PersonLinkTarget(party_id="412345678")


def test_activity_search_without_related_is_unrecognized() -> None:
    parsed = _PARSER.run(
        url=f"{UI_BASE}/backstop/search/ActivitySearch.action#/?inheritRelationships=true"
    )
    assert isinstance(parsed, UnrecognizedBackstopUrlResponse)


def test_activity_search_malformed_related_is_unrecognized() -> None:
    parsed = _PARSER.run(
        url=(
            f"{UI_BASE}/backstop/search/ActivitySearch.action" + "#/?selectedRelatedToUrl=not-json"
        )
    )
    assert isinstance(parsed, UnrecognizedBackstopUrlResponse)


def test_activity_search_empty_related_is_unrecognized() -> None:
    parsed = _PARSER.run(url=_activity_search_url([]))
    assert isinstance(parsed, UnrecognizedBackstopUrlResponse)


def test_activity_search_unknown_bean_still_yields_the_id() -> None:
    parsed = _PARSER.run(
        url=_activity_search_url(
            [{"id": "99", "type": "UnknownBean", "name": "X", "entityType": "PartyBean"}]
        )
    )
    assert isinstance(parsed, ParsedBackstopLinkResponse)
    assert parsed.entity_id == "99"
    assert parsed.entity_kind is None
    assert parsed.suggested_tool is None
    assert parsed.to_target() is None
