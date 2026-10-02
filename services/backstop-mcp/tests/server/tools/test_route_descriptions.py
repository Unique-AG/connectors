"""The tool that owns a call repeats the server-instruction route the model relies on.

`server/instructions.py` names the route once; the model reads the tool description at the
moment it picks arguments, so each route sentence is mirrored there.
"""

from collections.abc import Callable

import pytest

from backstop_mcp.features.accounts.tools.get_capital_flows import get_capital_flows
from backstop_mcp.features.accounts.tools.get_product_investors import get_product_investors
from backstop_mcp.features.activity_history.tools.get_activity_detail import (
    get_activity_detail,
)
from backstop_mcp.features.activity_history.tools.search_activities import search_activities
from backstop_mcp.features.activity_tags.tools.list_activity_tags import list_activity_tags
from backstop_mcp.features.opportunities.tools.search_opportunities import search_opportunities
from backstop_mcp.features.org_people.tools.get_person import get_person
from backstop_mcp.features.org_people.tools.search_organizations import search_organizations
from backstop_mcp.features.reports.tools.run_report import run_report

_ROUTES: tuple[tuple[Callable[..., object], str], ...] = (
    (run_report, 'A quoted report name, or "pull my X report", is this tool'),
    (run_report, "Do not rebuild it with get_capital_flows"),
    (run_report, "This tool cannot filter by product or date"),
    (run_report, "Keep every transaction type inside the cut"),
    (run_report, "replaces the product set"),
    (get_capital_flows, "Use this when no report is named"),
    (search_activities, "A named calendar day is both `start_date` and `end_date`"),
    (search_activities, '"since March" is only `start_date`'),
    (search_activities, "a later email is not evidence the earlier ask was inside it"),
    (search_activities, "then every returned id in `activity_tag_ids`"),
    (search_activities, "grouped by investor"),
    (get_activity_detail, "A later email is not evidence the earlier ask was inside it"),
    (get_product_investors, "is every feeder in this one call"),
    (get_product_investors, "Do not ask onshore or offshore before continuing"),
    (get_product_investors, "Balance can order that list; it is not the answer"),
    (get_person, "`job_title`, `department`, the `locations` include, and `email`"),
    (get_person, "Do not ask the user for Backstop field names"),
    (search_opportunities, "A stage-change question"),
    (search_opportunities, "including deals that closed — do not pass `is_open`"),
    (search_opportunities, "do not walk get_opportunities_by_ids for this question"),
    (search_opportunities, "the representative on the investor organization"),
    (search_opportunities, "call list_custom_fields for both organizations and opportunities"),
    (search_organizations, "call list_custom_fields for both organizations and opportunities"),
    (search_organizations, "`country` is the stored full name"),
    (search_opportunities, "retry once with `exclude_custom_fields=true`"),
    (search_organizations, "retry once with `exclude_custom_fields=true`"),
    (list_activity_tags, "pass every matching id to search_activities `activity_tag_ids`"),
)


def _description(tool: Callable[..., object]) -> str:
    return " ".join((tool.__doc__ or "").split())


@pytest.mark.parametrize(("tool", "phrase"), _ROUTES)
def test_tool_description_carries_the_route(tool: Callable[..., object], phrase: str) -> None:
    assert phrase in _description(tool)


def test_stage_change_example_keeps_closed_deals() -> None:
    doc = _description(search_opportunities)
    example = doc[doc.index("Stage changes: {") :].split("}", 1)[0]
    assert '"is_open": true' not in example
