"""The tool that owns a call repeats the server-instruction route the model relies on.

`server/instructions.py` names the route once; the model reads the tool description at the
moment it picks arguments, so each route sentence is mirrored there.
"""

from collections.abc import Callable

import pytest

from backstop_mcp.features.accounts.tools.get_capital_flows import get_capital_flows
from backstop_mcp.features.activity_history.tools.get_activity_detail import (
    get_activity_detail,
)
from backstop_mcp.features.activity_history.tools.search_activities import search_activities
from backstop_mcp.features.activity_tags.tools.list_activity_tags import list_activity_tags
from backstop_mcp.features.opportunities.tools.search_opportunities import search_opportunities
from backstop_mcp.features.org_people.tools.get_person import get_person
from backstop_mcp.features.org_people.tools.search_organizations import search_organizations
from backstop_mcp.features.org_people.tools.search_people import search_people
from backstop_mcp.features.reports.tools.run_report import run_report

_ROUTES: tuple[tuple[Callable[..., object], str], ...] = (
    (run_report, "Never invent a name"),
    (run_report, "can't be filtered by product or date"),
    (run_report, "following `next_offset`"),
    (get_capital_flows, "Backstop refuses an unfiltered read"),
    (search_activities, "A named calendar day is both `start_date` and `end_date`"),
    (search_activities, '"since March" is only `start_date`'),
    (search_activities, "then every returned id in `activity_tag_ids`"),
    (search_activities, "`attachments_count` is a count only"),
    (search_activities, "only when the user needs more rows"),
    (get_activity_detail, "An empty list means nothing was attached"),
    (get_person, "`job_title`, `department`, the `locations` include, and `email`"),
    (get_person, "Do not ask the user for standard field names"),
    (search_opportunities, "A stage-change question"),
    (search_opportunities, "including deals that closed — do not pass `is_open`"),
    (search_opportunities, "do not walk get_opportunities_by_ids for this question"),
    (search_opportunities, "deal-level representative login"),
    (search_opportunities, "is never filtered on"),
    (search_opportunities, "only when the user needs more rows"),
    (search_opportunities, "A counting question uses `mode=aggregate`"),
    (search_organizations, "`location_filter` is one location"),
    (search_opportunities, "retry once with `exclude_custom_fields=true`"),
    (search_organizations, "retry once with `exclude_custom_fields=true`"),
    (search_organizations, "only when the user needs more rows than this page holds"),
    (search_people, "exact display name"),
    (search_people, "`location_filter` is one location"),
    (search_people, "retry once with `exclude_custom_fields=true`"),
    (search_people, "only when the user needs more rows than this page holds"),
    (search_people, "`email` (exact on email, email2, or email3)"),
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
