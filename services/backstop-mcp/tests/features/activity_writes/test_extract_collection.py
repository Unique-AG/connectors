import pytest
from fastmcp.exceptions import ToolError

from backstop_mcp.features.activity_writes import extract_collection
from backstop_mcp.utils import parse_activity_handle


def test_bare_id_uses_kind_for_the_collection() -> None:
    collection, resource_id = extract_collection(parse_activity_handle("76280387"), kind="note")

    assert collection == "notes"
    assert resource_id == "76280387"


def test_matching_history_handle_strips_the_prefix() -> None:
    collection, resource_id = extract_collection(
        parse_activity_handle("meeting-or-calls_88001122"), kind="call"
    )

    assert collection == "meeting-or-calls"
    assert resource_id == "88001122"


@pytest.mark.parametrize("activity_id", ["emails_77001122", "email_77001122"])
def test_accepts_either_email_history_prefix(activity_id: str) -> None:
    collection, resource_id = extract_collection(parse_activity_handle(activity_id), kind="email")

    assert collection == "emails"
    assert resource_id == "77001122"


def test_rejects_a_handle_for_a_different_collection() -> None:
    with pytest.raises(ToolError, match="kind=note targets /notes"):
        extract_collection(parse_activity_handle("tasks_99001122"), kind="note")


def test_rejects_a_slash_in_the_handle() -> None:
    with pytest.raises(ToolError, match="not a Backstop activity id"):
        extract_collection(parse_activity_handle("notes/76280387"), kind="note")


def test_unknown_prefix_is_a_bare_id_that_contains_an_underscore() -> None:
    collection, resource_id = extract_collection(parse_activity_handle("foo_bar"), kind="task")

    assert collection == "tasks"
    assert resource_id == "foo_bar"
