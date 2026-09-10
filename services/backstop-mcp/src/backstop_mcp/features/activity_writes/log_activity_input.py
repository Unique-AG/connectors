"""Discriminated `log_activity` input: each `kind` declares only its own required fields.

Pydantic rejects a meeting or call without `time_zone` before any HTTP call. Author is not a
parameter — the authenticated caller is the author. Party targeting matches
`PartyResolveItemDto` in spirit (exactly one of `party_id` or `search`) without importing that DTO.
"""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from backstop_mcp.features.activity_writes._party_target_input import (
    PartyTargetInput,
    SecondaryPartyInput,
)

__all__ = [
    "CallActivityInput",
    "EmailActivityInput",
    "LOG_ACTIVITY_INPUT_DESCRIPTION",
    "LogActivityInput",
    "MeetingActivityInput",
    "NoteActivityInput",
    "TaskActivityInput",
]

LOG_ACTIVITY_INPUT_DESCRIPTION = (
    "Required. The activity to create. Discriminated by `kind`: `note`, `meeting`, "
    "`call`, `task`, or `email` (metadata stub only). Every kind needs `search_type` "
    "and exactly one of `party_id` or `search` — `party_id` alone is rejected. Author "
    "is the authenticated caller, not a field. Activity-tag ids come from "
    "`list_activity_tags` and are never created. For a file or a real `.msg`/`.eml` "
    "blob use `attach_file` after this create."
)


class _MeetingOrCallFields(BaseModel):
    """Shared meeting/call fields. `time_zone` is required — that is the discriminator's point."""

    title: str = Field(description="Required. Title written on the meeting or call.")
    time_zone: str = Field(
        description=(
            "Required. A `/time-zones` shortName (e.g. US/Eastern), not the catalog id and "
            "not the display name — name is ambiguous. Resolve via the time-zone catalog "
            "before calling."
        )
    )
    start: datetime | None = Field(
        default=None,
        description=(
            "Start timestamp (ISO-8601). Omit when Backstop should default. "
            "Required in practice for a useful meeting or call."
        ),
    )
    stop: datetime | None = Field(
        default=None,
        description="Stop timestamp (ISO-8601). Omit when Backstop should default.",
    )
    location: str | None = Field(
        default=None,
        description="Where the meeting or call took place. Omit when there is none.",
    )
    effective_date: date | None = Field(
        default=None,
        description="Calendar day on the activity, for backdating. Omit to use today.",
    )
    attendee_party_ids: tuple[str, ...] = Field(
        default=(),
        description=(
            "Trusted Backstop people ids to add as attendees. Empty when there are none. "
            "Never invent or guess — echo ids from a prior resolve."
        ),
    )
    activity_tag_ids: tuple[str, ...] = Field(
        default=(),
        description=(
            "Activity-tag ids from `list_activity_tags`. Empty when none apply. "
            "Tags are never created automatically."
        ),
    )


class NoteActivityInput(PartyTargetInput, SecondaryPartyInput):
    """A CRM note. Notes have no attendees and no time zone."""

    kind: Literal["note"] = Field(
        description="Log a CRM note. Notes have no attendees or time zone."
    )
    title: str = Field(description="Required. Title written on the note.")
    description: str | None = Field(default=None, description="Note body. Omit when there is none.")
    effective_date: date | None = Field(
        default=None,
        description="Calendar day on the note, for backdating. Omit to use today.",
    )
    activity_tag_ids: tuple[str, ...] = Field(
        default=(),
        description=(
            "Activity-tag ids from `list_activity_tags`. Empty when none apply. "
            "Tags are never created automatically."
        ),
    )


class MeetingActivityInput(PartyTargetInput, SecondaryPartyInput, _MeetingOrCallFields):
    """A face-to-face meeting. Maps to meeting-or-calls `type=FACE_TO_FACE` later."""

    kind: Literal["meeting"] = Field(
        description="Log a face-to-face meeting. Requires `time_zone`."
    )


class CallActivityInput(PartyTargetInput, SecondaryPartyInput, _MeetingOrCallFields):
    """A phone call. Maps to meeting-or-calls `PHONE_OUT` / `PHONE_IN` later."""

    kind: Literal["call"] = Field(
        description="Log a phone call. Requires `time_zone`. Defaults to an outbound call."
    )
    direction: Literal["PHONE_OUT", "PHONE_IN"] = Field(
        default="PHONE_OUT",
        description=(
            "PHONE_OUT is the default (we called them). PHONE_IN is inbound. Written as "
            "meeting-or-calls `type`."
        ),
    )


class TaskActivityInput(PartyTargetInput, SecondaryPartyInput):
    """A CRM task. Tasks have no activity tags, no effective date, and no author field."""

    kind: Literal["task"] = Field(
        description="Log a CRM task. Requires `assigned_user`; tasks have no activity tags."
    )
    title: str = Field(description="Required. Task title. Mapped to Backstop `name` on create.")
    assigned_user: str = Field(
        description=(
            "Required. A `list_system_users` login (`userName`), not the caller and not a "
            "party id. Tasks have no author field; this is who the task is assigned to."
        )
    )
    description: str | None = Field(
        default=None, description="Task body, mapped to wire `details`. Omit when there is none."
    )
    due_date: date | datetime | None = Field(
        default=None, description="Due day or timestamp. Omit when the task has no due date."
    )
    send_notification: bool = Field(
        default=False,
        description=(
            "Whether Backstop should notify the assignee. Defaults to false and is echoed "
            "on the response."
        ),
    )


class EmailActivityInput(PartyTargetInput):
    """An email metadata stub. The body/blob is `attach_file`, not this tool."""

    kind: Literal["email"] = Field(
        description=(
            "Log email metadata (displaySubject, format, tags). Subject/from/to parse from "
            "a blob via `attach_file`, not here."
        )
    )
    display_subject: str | None = Field(
        default=None,
        description="Display subject written on the email. Omit when Backstop should default.",
    )
    email_format: str | None = Field(
        default=None,
        description=(
            "Optional. Backstop `emailFormat` when known (`eml` or `msg`). The message "
            "blob is `attach_file`, not this field."
        ),
    )
    activity_tag_ids: tuple[str, ...] = Field(
        default=(),
        description=(
            "Activity-tag ids from `list_activity_tags`. Empty when none apply. "
            "Tags are never created automatically."
        ),
    )


type LogActivityInput = Annotated[
    NoteActivityInput
    | MeetingActivityInput
    | CallActivityInput
    | TaskActivityInput
    | EmailActivityInput,
    Field(discriminator="kind", description=LOG_ACTIVITY_INPUT_DESCRIPTION),
]
