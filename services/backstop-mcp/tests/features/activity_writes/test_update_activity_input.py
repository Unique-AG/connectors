"""Discriminated `update_activity` input: at least one change field, no author."""

import pytest
from pydantic import TypeAdapter, ValidationError

from backstop_mcp.features.activity_writes import UpdateActivityInput

_ADAPTER: TypeAdapter[UpdateActivityInput] = TypeAdapter(UpdateActivityInput)


def test_accepts_a_note_title_patch() -> None:
    parsed = _ADAPTER.validate_python(
        {"kind": "note", "activity_id": "76280387", "title": "Corrected"}
    )

    assert parsed.kind == "note"
    assert parsed.activity_id == "76280387"
    assert parsed.model_dump()["title"] == "Corrected"


def test_rejects_an_update_with_no_change_fields() -> None:
    with pytest.raises(ValidationError, match="Pass at least one field to change"):
        _ADAPTER.validate_python({"kind": "note", "activity_id": "76280387"})


def test_empty_tag_tuple_counts_as_a_change() -> None:
    parsed = _ADAPTER.validate_python(
        {"kind": "email", "activity_id": "77001122", "activity_tag_ids": []}
    )

    assert parsed.kind == "email"
    assert parsed.model_dump()["activity_tag_ids"] == ()


def test_meeting_and_call_share_optional_schedule_fields() -> None:
    meeting = _ADAPTER.validate_python(
        {"kind": "meeting", "activity_id": "88001122", "location": "Boardroom"}
    )
    call = _ADAPTER.validate_python(
        {"kind": "call", "activity_id": "88001122", "direction": "PHONE_IN"}
    )

    assert meeting.kind == "meeting"
    assert call.kind == "call"
    assert call.model_dump()["direction"] == "PHONE_IN"


def test_task_and_document_variants_parse() -> None:
    task = _ADAPTER.validate_python({"kind": "task", "activity_id": "99001122", "title": "Renamed"})
    document = _ADAPTER.validate_python(
        {"kind": "document", "activity_id": "88002233", "description": "Updated memo"}
    )

    assert task.kind == "task"
    assert document.kind == "document"
