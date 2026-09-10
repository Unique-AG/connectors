"""Discriminated `log_activity` input: required fields per kind, no author parameter."""

import pytest
from pydantic import TypeAdapter, ValidationError

from backstop_mcp.features.activity_writes import (
    CallActivityInput,
    EmailActivityInput,
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
    EmailActivityInput,
)


def test_accepts_a_note_with_search_type_and_party_id_and_no_time_zone() -> None:
    parsed = _ADAPTER.validate_python(
        {
            "kind": "note",
            "search_type": "people",
            "party_id": "27871657",
            "title": "Follow up",
        }
    )

    assert isinstance(parsed, NoteActivityInput)
    assert parsed.kind == "note"
    assert parsed.title == "Follow up"
    assert parsed.search_type == "people"
    assert parsed.party_id == "27871657"


def test_rejects_meeting_without_time_zone() -> None:
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python(
            {
                "kind": "meeting",
                "search_type": "people",
                "party_id": "27871657",
                "title": "Q1 review",
            }
        )


def test_rejects_call_without_time_zone() -> None:
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python(
            {
                "kind": "call",
                "search_type": "people",
                "party_id": "27871657",
                "title": "Check in",
            }
        )


def test_call_defaults_direction_phone_out() -> None:
    parsed = _ADAPTER.validate_python(
        {
            "kind": "call",
            "search_type": "people",
            "party_id": "27871657",
            "title": "Check in",
            "time_zone": "US/Eastern",
        }
    )

    assert isinstance(parsed, CallActivityInput)
    assert parsed.direction == "PHONE_OUT"


def test_task_send_notification_defaults_false() -> None:
    parsed = _ADAPTER.validate_python(
        {
            "kind": "task",
            "search_type": "people",
            "party_id": "27871657",
            "title": "Send deck",
            "assigned_user": "jdoe",
        }
    )

    assert isinstance(parsed, TaskActivityInput)
    assert parsed.send_notification is False


def test_task_without_assigned_user_fails() -> None:
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python(
            {
                "kind": "task",
                "search_type": "people",
                "party_id": "27871657",
                "title": "Send deck",
            }
        )


def test_author_is_not_a_field_on_any_variant() -> None:
    for variant in _VARIANTS:
        assert "author" not in variant.model_fields
