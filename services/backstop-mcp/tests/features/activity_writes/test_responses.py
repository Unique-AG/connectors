"""`published_output_schema` wraps a response union as a root object; OmitNoneModel drops nulls."""

import pytest
from pydantic import TypeAdapter, ValidationError

from backstop_mcp.features.activity_writes import (
    AttachedFileResponse,
    DeletedActivityResponse,
    LogActivityResponse,
    LoggedActivityResponse,
    LoggedCallResponse,
    LoggedMeetingResponse,
    LoggedNoteResponse,
    LoggedTaskResponse,
    UpdatedActivityResponse,
)
from backstop_mcp.models import published_output_schema

_ADAPTER: TypeAdapter[object] = TypeAdapter(LoggedActivityResponse)
_WRITE_RESPONSES = (
    LoggedActivityResponse
    | AttachedFileResponse
    | UpdatedActivityResponse
    | DeletedActivityResponse
)


def test_published_output_schema_wraps_a_union_as_an_object() -> None:
    schema = published_output_schema(_WRITE_RESPONSES)

    assert schema["type"] == "object"
    assert "anyOf" in schema or "oneOf" in schema


def test_published_output_schema_covers_the_log_activity_return_union() -> None:
    schema = published_output_schema(LogActivityResponse)

    assert schema["type"] == "object"
    assert "anyOf" in schema or "oneOf" in schema


def test_note_omits_title_on_dump_and_has_no_meeting_fields() -> None:
    dumped = LoggedNoteResponse(id="76280387").model_dump()

    assert dumped == {"id": "76280387", "kind": "note", "resource_type": "notes"}
    assert "meeting_type" not in LoggedNoteResponse.model_fields
    assert "time_zone" not in LoggedNoteResponse.model_fields
    assert "send_notification" not in LoggedNoteResponse.model_fields


def test_meeting_requires_time_zone() -> None:
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python({"id": "1", "kind": "meeting"})


def test_call_requires_meeting_type_and_time_zone() -> None:
    parsed = _ADAPTER.validate_python(
        {
            "id": "1",
            "kind": "call",
            "meeting_type": "PHONE_OUT",
            "time_zone": "US/Eastern",
        }
    )

    assert isinstance(parsed, LoggedCallResponse)
    assert parsed.meeting_type == "PHONE_OUT"
    assert parsed.time_zone == "US/Eastern"
    assert parsed.resource_type == "meeting-or-calls"


def test_task_requires_send_notification() -> None:
    parsed = _ADAPTER.validate_python({"id": "1", "kind": "task", "send_notification": False})

    assert isinstance(parsed, LoggedTaskResponse)
    assert parsed.send_notification is False
    assert "time_zone" not in LoggedTaskResponse.model_fields


def test_meeting_defaults_face_to_face() -> None:
    parsed = _ADAPTER.validate_python({"id": "1", "kind": "meeting", "time_zone": "US/Eastern"})

    assert isinstance(parsed, LoggedMeetingResponse)
    assert parsed.meeting_type == "FACE_TO_FACE"
