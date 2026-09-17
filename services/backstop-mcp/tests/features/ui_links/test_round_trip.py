"""parse(build(target)) recovers the target for every page × tab × layout and activity kind."""

import pytest

from backstop_mcp.features.ui_links import (
    ACTIVITY_JSP_SLUG_TO_KIND,
    PAGE_SPECS,
    AccountLinkTargetDto,
    BackstopLinkResponse,
    BackstopLinkTargetDto,
    BackstopUiPage,
    BuildEntityLinkUtil,
    CallLinkTargetDto,
    DocumentLinkTargetDto,
    EmailLinkTargetDto,
    MeetingLinkTargetDto,
    NoteLinkTargetDto,
    OpportunityLinkTargetDto,
    OrganizationLinkTargetDto,
    ParsedBackstopLinkResponse,
    ParseEntityLinkUtil,
    PersonLinkTargetDto,
    ProductLinkTargetDto,
    TaskLinkTargetDto,
)
from tests.features.ui_links.conftest import UI_BASE, query_params

_BUILDER = BuildEntityLinkUtil()
_PARSER = ParseEntityLinkUtil()

_PAGE_TARGETS: tuple[tuple[BackstopLinkTargetDto, BackstopUiPage], ...] = (
    (OrganizationLinkTargetDto(party_id="341764767"), BackstopUiPage.ORGANIZATION),
    (PersonLinkTargetDto(party_id="341764767"), BackstopUiPage.PERSON),
    (ProductLinkTargetDto(entity_id="341764767"), BackstopUiPage.PRODUCT),
    (AccountLinkTargetDto(entity_id="27871657"), BackstopUiPage.ACCOUNT),
    (OpportunityLinkTargetDto(entity_id="5755163"), BackstopUiPage.OPPORTUNITY),
    (TaskLinkTargetDto(task_id="2741757"), BackstopUiPage.TASK),
    (EmailLinkTargetDto(entity_activity_details_id="1804463726"), BackstopUiPage.EMAIL),
)

_ACTIVITY_TARGETS: tuple[BackstopLinkTargetDto, ...] = (
    CallLinkTargetDto(entity_activity_details_id="76777353"),
    MeetingLinkTargetDto(entity_activity_details_id="76777273"),
    NoteLinkTargetDto(entity_activity_details_id="26211573"),
    DocumentLinkTargetDto(entity_activity_details_id="128365105"),
)

_LAYOUT = ("Investor Information", "OrganizationBean")


def _build(
    target: BackstopLinkTargetDto,
    *,
    tabs: tuple[str, ...] | None = (),
    layout_name: str | None = None,
    view_entity_type: str | None = None,
) -> BackstopLinkResponse:
    result = _BUILDER.run(
        target=target,
        ui_base_url=UI_BASE,
        tabs=tabs,
        layout_name=layout_name,
        view_entity_type=view_entity_type,
    )
    assert isinstance(result, BackstopLinkResponse)
    return result


def _parse(url: str) -> ParsedBackstopLinkResponse:
    parsed = _PARSER.run(url=url, ui_base_url=UI_BASE)
    assert isinstance(parsed, ParsedBackstopLinkResponse)
    return parsed


def _tab_cases() -> list[tuple[BackstopLinkTargetDto, str | None]]:
    cases: list[tuple[BackstopLinkTargetDto, str | None]] = []
    for target, page in _PAGE_TARGETS:
        spec = PAGE_SPECS[page]
        cases.append((target, None))
        cases.extend((target, tab) for tab in spec.tabs)
    cases.extend((target, None) for target in _ACTIVITY_TARGETS)
    return cases


@pytest.mark.parametrize(("target", "tab"), _tab_cases())
def test_round_trip_recovers_target_and_tab(target: BackstopLinkTargetDto, tab: str | None) -> None:
    built = _build(target, tabs=() if tab is None else (tab,))
    assert built.links
    parsed = _parse(built.links[0].url)
    assert parsed.to_target() == target
    assert parsed.tab == tab
    assert parsed.host_mismatch is False


@pytest.mark.parametrize(
    "target", [target for target, _page in _PAGE_TARGETS] + list(_ACTIVITY_TARGETS)
)
def test_round_trip_every_activity_kind_and_page(target: BackstopLinkTargetDto) -> None:
    parsed = _parse(_build(target, tabs=()).links[0].url)
    assert parsed.to_target() == target


@pytest.mark.parametrize(
    ("target", "page"),
    [(target, page) for target, page in _PAGE_TARGETS if PAGE_SPECS[page].supports_layout],
)
def test_round_trip_layout_recovers_target_and_layout(
    target: BackstopLinkTargetDto, page: BackstopUiPage
) -> None:
    layout_name, view_entity_type = _LAYOUT
    if page == BackstopUiPage.OPPORTUNITY:
        layout_name, view_entity_type = "Master Pipeline", "OpportunityBean"
    built = _build(
        target,
        tabs=(),
        layout_name=layout_name,
        view_entity_type=view_entity_type,
    )
    layout_url = built.links[-1].url
    parsed = _parse(layout_url)
    assert parsed.to_target() == target
    assert parsed.layout_name == layout_name
    assert parsed.view_entity_type == view_entity_type
    assert parsed.tab is None


def test_product_summary_is_omission_not_view_type_summary() -> None:
    product = ProductLinkTargetDto(entity_id="341764767")
    no_tab_url = _build(product, tabs=()).links[0].url
    asked_summary = _build(product, tabs=("summary",))
    assert len(asked_summary.links) == 1
    assert asked_summary.links[0].url == no_tab_url
    assert "viewType" not in query_params(asked_summary.links[0].url)
    assert "viewType=summary" not in asked_summary.links[0].url
    no_tab = _parse(no_tab_url)
    assert no_tab.tab is None

    all_tabs = _build(product, tabs=None)
    for link in all_tabs.links:
        assert query_params(link.url).get("viewType") != "summary"

    org = OrganizationLinkTargetDto(party_id="341764767")
    summary = _parse(_build(org, tabs=("summary",)).links[0].url)
    assert summary.tab == "summary"
    assert query_params(_build(org, tabs=("summary",)).links[0].url)["viewType"] == "summary"
    no_tab_org = _parse(_build(org, tabs=()).links[0].url)
    assert no_tab_org.tab is None
    assert "viewType" not in query_params(_build(org, tabs=()).links[0].url)

    person = PersonLinkTargetDto(party_id="412345678")
    assert query_params(_build(person, tabs=("summary",)).links[0].url)["viewType"] == "summary"

    account = AccountLinkTargetDto(entity_id="33578475")
    assert (
        query_params(_build(account, tabs=("summary",)).links[0].url)["acctViewType"] == "summary"
    )


def test_activity_slug_table_covers_every_jsp_kind() -> None:
    for slug, kind in ACTIVITY_JSP_SLUG_TO_KIND.items():
        target = {
            "call": CallLinkTargetDto(entity_activity_details_id="76777353"),
            "meeting": MeetingLinkTargetDto(entity_activity_details_id="76777273"),
            "note": NoteLinkTargetDto(entity_activity_details_id="26211573"),
            "document": DocumentLinkTargetDto(entity_activity_details_id="128365105"),
        }[kind]
        url = _build(target, tabs=()).links[0].url
        parsed = _parse(url)
        assert parsed.entity_kind == kind
        assert parsed.page == BackstopUiPage.ACTIVITY
        assert f"/activities.jsp/{slug}/" in url
