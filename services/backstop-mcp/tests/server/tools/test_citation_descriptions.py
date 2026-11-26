"""A write whose result carries a title and a CRM link tells the agent not to cite it.

Conduct cites any record with a title and a link. A write's echo of the record it made is a
confirmation, not a source, so its description sends the agent to the read tool instead.
"""

from collections.abc import Callable

import pytest

from backstop_mcp.features.activity_writes.tools.log_activity import log_activity
from backstop_mcp.features.opportunity_writes.tools.create_opportunity import create_opportunity
from backstop_mcp.features.org_people.tools.get_organization import get_organization
from backstop_mcp.features.org_people.tools.get_person import get_person
from backstop_mcp.features.org_people.tools.search_people import search_people
from backstop_mcp.features.org_people_writes.tools.create_organization import (
    create_organization,
)
from backstop_mcp.features.org_people_writes.tools.create_person import create_person

_DO_NOT_CITE = "Do not cite this tool's result: it confirms the write, it is not a source."


def _description(tool: Callable[..., object]) -> str:
    return " ".join((tool.__doc__ or "").split())


@pytest.mark.parametrize(
    ("tool", "read_tool"),
    [
        (log_activity, "Cite the activity you read with `get_activity_detail` instead."),
        (create_opportunity, "Cite the deal you read with `get_opportunities_by_ids` instead."),
        (create_person, "Cite the person you read with `get_person` instead."),
        (create_organization, "Cite the organization you read with `get_organization` instead."),
    ],
)
def test_write_description_sends_citations_to_the_read_tool(
    tool: Callable[..., object], read_tool: str
) -> None:
    description = _description(tool)
    assert _DO_NOT_CITE in description
    assert read_tool in description


@pytest.mark.parametrize("tool", [get_person, get_organization, search_people])
def test_read_description_does_not_forbid_citing(tool: Callable[..., object]) -> None:
    assert "Do not cite" not in _description(tool)
