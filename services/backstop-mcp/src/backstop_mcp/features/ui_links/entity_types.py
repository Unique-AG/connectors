"""CRM UI page table: path, id/tab params, allowed tabs, and the URL template.

Builder and parser share this table so a page's spelling cannot drift between them.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class BackstopUiPage(StrEnum):
    ORGANIZATION = "crm/ManageOrganization.action"
    PERSON = "crm/ManagePerson.action"
    PRODUCT = "fundaccounting/portfolio/ManageHedgeFund.action"
    ACCOUNT = "fundaccounting/ManageAccount.action"
    OPPORTUNITY = "crm/Opportunity.action"
    EMAIL = "crm/collaboration/DisplayEmailMessage.action"
    TASK = "crm/Task.action"
    LANDING = "utility/LandingPageUrl.action"
    ACTIVITY_SEARCH = "search/ActivitySearch.action"
    ACTIVITY = "activities.jsp"


ACCOUNT_SUGGESTED_NOTE: Final[str] = "This is an account id, not a party id."
TASK_SUGGESTED_NOTE: Final[str] = (
    "This is a taskId; no MCP tool loads a task by id (get_tasks_for_party is party-scoped)."
)


@dataclass(frozen=True, slots=True)
class LandingSuggestedLookup:
    """Tool (and optional caveat) for a LandingPageUrl `resourceType`."""

    tool: str | None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class ActivitySearchBeanLookup:
    """Party kind and tool for an ActivitySearch `type` / `firstSystemDefinedType` bean."""

    entity_kind: str
    tool: str


@dataclass(frozen=True, slots=True)
class UiPageSpec:
    """One CRM UI page: how to emit it and how to recognize it."""

    page: BackstopUiPage
    template: str
    id_param: str | None
    tab_param: str | None
    tabs: tuple[str, ...]
    extra_query: tuple[tuple[str, str], ...]
    query_param_order: tuple[str, ...]
    uses_display: bool
    summary_by_omission: bool
    buildable: bool
    supports_layout: bool
    entity_kind: str | None
    suggested_tool: str | None
    suggested_note: str | None
    canonical_label: str


def _action_template(page: BackstopUiPage) -> str:
    return "{ui_base}/backstop/" + page.value


_LAYOUT_QUERY_ORDER: tuple[str, ...] = ("display", "viewEntityType", "entityId", "layoutName")

PAGE_SPECS: Final[dict[BackstopUiPage, UiPageSpec]] = {
    BackstopUiPage.ORGANIZATION: UiPageSpec(
        page=BackstopUiPage.ORGANIZATION,
        template=_action_template(BackstopUiPage.ORGANIZATION),
        id_param="party_id",
        tab_param="viewType",
        tabs=("summary", "detail", "employeesView", "activities", "task", "accounts"),
        extra_query=(),
        query_param_order=("display", "party_id", "viewType"),
        uses_display=True,
        summary_by_omission=False,
        buildable=True,
        supports_layout=True,
        entity_kind="organization",
        suggested_tool="get_organization",
        suggested_note=None,
        canonical_label="Open",
    ),
    BackstopUiPage.PERSON: UiPageSpec(
        page=BackstopUiPage.PERSON,
        template=_action_template(BackstopUiPage.PERSON),
        id_param="party_id",
        tab_param="viewType",
        tabs=("summary", "detail", "activities", "task", "accounts"),
        extra_query=(),
        query_param_order=("display", "party_id", "viewType"),
        uses_display=True,
        summary_by_omission=False,
        buildable=True,
        supports_layout=True,
        entity_kind="person",
        suggested_tool="get_person",
        suggested_note=None,
        canonical_label="Open",
    ),
    BackstopUiPage.PRODUCT: UiPageSpec(
        page=BackstopUiPage.PRODUCT,
        template=_action_template(BackstopUiPage.PRODUCT),
        id_param="entityId",
        tab_param="viewType",
        tabs=(
            "accounts",
            "investors",
            "opportunities",
            "dueType",
            "actType",
            "task",
            "statsType",
            "riskType",
        ),
        extra_query=(),
        query_param_order=("display", "entityId", "viewType"),
        uses_display=True,
        summary_by_omission=True,
        buildable=True,
        supports_layout=True,
        entity_kind="product",
        suggested_tool="get_product",
        suggested_note=None,
        canonical_label="Summary",
    ),
    BackstopUiPage.ACCOUNT: UiPageSpec(
        page=BackstopUiPage.ACCOUNT,
        template=_action_template(BackstopUiPage.ACCOUNT),
        id_param="entityId",
        tab_param="acctViewType",
        tabs=("summary", "performance", "bankInfo", "transactions", "activities"),
        extra_query=(),
        query_param_order=("display", "entityId", "acctViewType"),
        uses_display=True,
        summary_by_omission=False,
        buildable=True,
        supports_layout=True,
        entity_kind="account",
        suggested_tool="get_accounts_for_party",
        suggested_note=ACCOUNT_SUGGESTED_NOTE,
        canonical_label="Open",
    ),
    BackstopUiPage.OPPORTUNITY: UiPageSpec(
        page=BackstopUiPage.OPPORTUNITY,
        template=_action_template(BackstopUiPage.OPPORTUNITY),
        id_param="entityId",
        tab_param="viewType",
        tabs=("activity", "tasks"),
        extra_query=(),
        query_param_order=("display", "entityId", "viewType"),
        uses_display=True,
        summary_by_omission=False,
        buildable=True,
        supports_layout=True,
        entity_kind="opportunity",
        suggested_tool="get_opportunities_by_ids",
        suggested_note=None,
        canonical_label="Open",
    ),
    BackstopUiPage.EMAIL: UiPageSpec(
        page=BackstopUiPage.EMAIL,
        template=_action_template(BackstopUiPage.EMAIL),
        id_param="summaryId",
        tab_param=None,
        tabs=(),
        extra_query=(("showControls", "true"),),
        query_param_order=("summaryId", "showControls"),
        uses_display=False,
        summary_by_omission=False,
        buildable=True,
        supports_layout=False,
        entity_kind="email",
        suggested_tool="get_activity_detail",
        suggested_note=None,
        canonical_label="Open",
    ),
    BackstopUiPage.TASK: UiPageSpec(
        page=BackstopUiPage.TASK,
        template=_action_template(BackstopUiPage.TASK),
        id_param="taskId",
        tab_param=None,
        tabs=(),
        extra_query=(
            ("popupAddEditTask", ""),
            ("workflowTaskId", ""),
            ("viewOnly", "true"),
        ),
        query_param_order=("popupAddEditTask", "taskId", "workflowTaskId", "viewOnly"),
        uses_display=False,
        summary_by_omission=False,
        buildable=True,
        supports_layout=False,
        entity_kind="task",
        suggested_tool=None,
        suggested_note=TASK_SUGGESTED_NOTE,
        canonical_label="Open",
    ),
    BackstopUiPage.ACTIVITY_SEARCH: UiPageSpec(
        page=BackstopUiPage.ACTIVITY_SEARCH,
        template=_action_template(BackstopUiPage.ACTIVITY_SEARCH),
        id_param=None,
        tab_param=None,
        tabs=(),
        extra_query=(),
        query_param_order=(),
        uses_display=False,
        summary_by_omission=False,
        buildable=False,
        supports_layout=False,
        entity_kind=None,
        suggested_tool=None,
        suggested_note=None,
        canonical_label="Open",
    ),
    BackstopUiPage.LANDING: UiPageSpec(
        page=BackstopUiPage.LANDING,
        template=_action_template(BackstopUiPage.LANDING),
        id_param="entityId",
        tab_param=None,
        tabs=(),
        extra_query=(),
        query_param_order=("resourceType", "entityId"),
        uses_display=False,
        summary_by_omission=False,
        buildable=False,
        supports_layout=False,
        entity_kind=None,
        suggested_tool=None,
        suggested_note=None,
        canonical_label="Open",
    ),
    BackstopUiPage.ACTIVITY: UiPageSpec(
        page=BackstopUiPage.ACTIVITY,
        template="{ui_base}/backstop/activities.jsp/{kind}/{id}",
        id_param=None,
        tab_param=None,
        tabs=(),
        extra_query=(),
        query_param_order=(),
        uses_display=False,
        summary_by_omission=False,
        buildable=True,
        supports_layout=False,
        entity_kind=None,
        suggested_tool="get_activity_detail",
        suggested_note=None,
        canonical_label="Open",
    ),
}

TAB_LABELS: Final[dict[str, str]] = {
    "summary": "Summary",
    "detail": "Detail",
    "employeesView": "Employees",
    "activities": "Activities",
    "task": "Task",
    "accounts": "Accounts",
    "investors": "Investors",
    "opportunities": "Opportunities",
    "dueType": "Due Diligence",
    "actType": "Activity",
    "statsType": "Statistics",
    "riskType": "Risk",
    "performance": "Performance",
    "bankInfo": "Bank Info",
    "transactions": "Transactions",
    "activity": "Activity",
    "tasks": "Tasks",
}

LAYOUT_QUERY_ORDER: Final[tuple[str, ...]] = _LAYOUT_QUERY_ORDER
IGNORED_QUERY_PARAMS: Final[frozenset[str]] = frozenset(
    {"display", "view", "showControls", "popupAddEditTask"}
)
LANDING_RESOURCE_TYPE_TOOLS: Final[dict[str, LandingSuggestedLookup]] = {
    "organizations": LandingSuggestedLookup("get_organization"),
    "people": LandingSuggestedLookup("get_person"),
    "contacts": LandingSuggestedLookup("get_person"),
    "employees": LandingSuggestedLookup("get_person"),
    "products": LandingSuggestedLookup("get_product"),
    "accounts": LandingSuggestedLookup("get_accounts_for_party", ACCOUNT_SUGGESTED_NOTE),
    "opportunities": LandingSuggestedLookup("get_opportunities_by_ids"),
    "tasks": LandingSuggestedLookup(None, TASK_SUGGESTED_NOTE),
}
ACTIVITY_SEARCH_BEAN_TOOLS: Final[dict[str, ActivitySearchBeanLookup]] = {
    "OrganizationBean": ActivitySearchBeanLookup("organization", "get_organization"),
    "PersonBean": ActivitySearchBeanLookup("person", "get_person"),
    "ContactBean": ActivitySearchBeanLookup("person", "get_person"),
    "EmployeeBean": ActivitySearchBeanLookup("person", "get_person"),
}

assert set(PAGE_SPECS) == set(BackstopUiPage)

# The builder emits only the params named in `query_param_order`, so anything a spec carries
# but leaves out of that tuple would vanish from the URL without failing a test.
for _page, _spec in PAGE_SPECS.items():
    if not _spec.buildable or _page == BackstopUiPage.ACTIVITY:
        continue
    _emitted = {name for name, _value in _spec.extra_query}
    if _spec.uses_display:
        _emitted.add("display")
    if _spec.id_param is not None:
        _emitted.add(_spec.id_param)
    if _spec.tab_param is not None:
        _emitted.add(_spec.tab_param)
    assert _emitted <= set(_spec.query_param_order), (
        f"{_page} emits {_emitted - set(_spec.query_param_order)} "
        "but query_param_order would drop them"
    )
