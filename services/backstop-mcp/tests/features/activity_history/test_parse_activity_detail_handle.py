import pytest
from fastmcp.exceptions import ToolError

from backstop_mcp.features.activity_history import parse_activity_detail_handle


def test_splits_a_history_composite_handle() -> None:
    handle = parse_activity_detail_handle("meeting-or-calls_76537547")

    assert handle.resource_type == "meeting-or-calls"
    assert handle.resource_id == "76537547"


@pytest.mark.parametrize("activity_id", ["1659094659", "1791831538"])
def test_accepts_a_search_row_id(activity_id: str) -> None:
    handle = parse_activity_detail_handle(activity_id)

    assert handle.resource_type is None
    assert handle.resource_id == activity_id


def test_rejects_an_empty_handle() -> None:
    with pytest.raises(ToolError, match="not a valid activity_id"):
        parse_activity_detail_handle("  ")


@pytest.mark.parametrize("activity_id", ["email_42", "emails_99"])
def test_rejects_a_history_email_handle(activity_id: str) -> None:
    with pytest.raises(ToolError, match="email handle"):
        parse_activity_detail_handle(activity_id)
