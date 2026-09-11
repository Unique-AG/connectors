"""Discriminated `log_activity` input: required fields per kind, no author parameter.

Anything Backstop rejects a create without is required here, so the model refuses the call
instead of the agent reading a 400. There is no email kind: `POST /emails` needs the
message blob, which is `attach_file`.
"""

from datetime import date, datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from backstop_mcp.features.activity_writes import (
    CallActivityInput,
    LogActivityInput,
    MeetingActivityInput,
    NoteActivityInput,
    TaskActivityInput,
)

_ADAPTER: TypeAdapter[object] = TypeAdapter(LogActivityInput)
_VARIANTS = (
    NoteActivityInput,
    MeetingActivityInput,
    CallActivityInput,
    TaskActivityInput,
)

_TARGET = {"search_type": "people", "party_id": "27871657"}
_SCHEDULE = {
    "time_zone": "US/Eastern",
    "start": datetime(2026, 9, 10, 10, 0),
    "stop": datetime(2026, 9, 10, 11, 0),
}


def test_accepts_a_note_with_search_type_and_party_id_and_no_time_zone() -> None:
    parsed = _ADAPTER.validate_python({"kind": "note", "title": "Follow up"} | _TARGET)

    assert isinstance(parsed, NoteActivityInput)
    assert parsed.kind == "note"
    assert parsed.title == "Follow up"
    assert parsed.search_type == "people"
    assert parsed.party_id == "27871657"


def test_a_note_needs_no_effective_date_because_the_command_defaults_it() -> None:
    parsed = _ADAPTER.validate_python({"kind": "note", "title": "Follow up"} | _TARGET)

    assert isinstance(parsed, NoteActivityInput)
    assert parsed.effective_date is None


@pytest.mark.parametrize("kind", ["meeting", "call"])
@pytest.mark.parametrize("missing", ["time_zone", "start", "stop"])
def test_rejects_a_meeting_or_call_missing_a_field_backstop_requires(
    kind: str, missing: str
) -> None:
    payload = {"kind": kind, "title": "Q1 review"} | _TARGET | _SCHEDULE
    del payload[missing]

    with pytest.raises(ValidationError, match=missing):
        _ADAPTER.validate_python(payload)


def test_call_defaults_direction_phone_out() -> None:
    parsed = _ADAPTER.validate_python({"kind": "call", "title": "Check in"} | _TARGET | _SCHEDULE)

    assert isinstance(parsed, CallActivityInput)
    assert parsed.direction == "PHONE_OUT"


def test_task_send_notification_defaults_false() -> None:
    parsed = _ADAPTER.validate_python(
        {
            "kind": "task",
            "title": "Send deck",
            "assigned_user": "jdoe",
            "due_date": date(2026, 9, 20),
        }
        | _TARGET
    )

    assert isinstance(parsed, TaskActivityInput)
    assert parsed.send_notification is False


@pytest.mark.parametrize("missing", ["assigned_user", "due_date"])
def test_rejects_a_task_missing_a_field_backstop_requires(missing: str) -> None:
    payload = {
        "kind": "task",
        "title": "Send deck",
        "assigned_user": "jdoe",
        "due_date": date(2026, 9, 20),
    } | _TARGET
    del payload[missing]

    with pytest.raises(ValidationError, match=missing):
        _ADAPTER.validate_python(payload)


def test_there_is_no_email_kind_to_log() -> None:
    """`POST /emails` is `400 "Field data is required"`, so email creates are attach_file."""
    with pytest.raises(ValidationError, match="kind"):
        _ADAPTER.validate_python({"kind": "email", "display_subject": "Intro"} | _TARGET)


def test_author_is_not_a_field_on_any_variant() -> None:
    for variant in _VARIANTS:
        assert "author" not in variant.model_fields
