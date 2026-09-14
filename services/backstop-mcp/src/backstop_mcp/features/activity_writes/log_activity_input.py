"""Discriminated `log_activity` input: each `kind` declares only its own required fields.

Every field Backstop rejects a create without is required here, so the failure is a schema
error the model sees rather than a 400 it has to interpret: `time_zone`, `start` and `stop`
on a meeting or call, `due_date` on a task. Author is not a parameter — the authenticated
caller is the author. Party targeting matches `PartyResolveItemDto` in spirit (exactly one
of `party_id` or `search`) without importing that DTO.

There is no `email` variant. `POST /emails` answers `400 "Field data is required in POST
request."`, so a metadata-only email record cannot be created through the API; importing a
real `.msg`/`.eml` is `attach_file(kind="email")`.
"""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field

from backstop_mcp.features.activity_writes._party_target_input import (
    PartyTargetInput,
    SecondaryPartyInput,
)

__all__ = [
    "CallActivityInput",
    "LOG_ACTIVITY_INPUT_DESCRIPTION",
    "LogActivityInput",
    "MeetingActivityInput",
    "NoteActivityInput",
    "TaskActivityInput",
]

LOG_ACTIVITY_INPUT_DESCRIPTION = (
    "Required. The activity to create. Discriminated by `kind`: `note`, `meeting`, "
    "`call`, or `task`. Every kind needs `search_type` and exactly one of `party_id` or "
    "`search` — `party_id` alone is rejected. Author is the authenticated caller, not a "
    "field. Activity-tag ids come from `list_activity_tags` and are never created. For a "
    "file, or for an email of any kind, use `attach_file` — email records require the "
    "message blob and cannot be logged here."
)


class ActivityBaseInput(PartyTargetInput, SecondaryPartyInput):
    """Party targeting plus the title every `log_activity` kind writes."""

    title: str = Field(
        description=(
            "Required. Title written on the activity. On a task this is mapped to Backstop "
            "`name` on create."
        )
    )


class _DatedTaggedActivityInput(ActivityBaseInput):
    """Notes, meetings, and calls accept a backdate and activity tags."""

    effective_date: date | None = Field(
        default=None,
        description="Calendar day on the activity, for backdating. Omit to use today.",
    )
    activity_tag_ids: tuple[str, ...] = Field(
        default=(),
        description=(
            "Activity-tag ids from `list_activity_tags`. Empty when none apply. "
            "Tags are never created automatically."
        ),
    )


class _MeetingOrCallFields(_DatedTaggedActivityInput):
    """Shared meeting/call fields.

    `time_zone`, `start` and `stop` are required because Backstop requires them
    (`400 "Field startTimestamp is required"`, and the same for `stopTimestamp` and
    `timeZone`) even though its swagger's required list omits them. Requiring them here is
    the discriminator's point: the model rejects an unloggable meeting before any HTTP call.
    """

    time_zone: str = Field(
        description=(
            "Required. A `/time-zones` shortName (e.g. US/Eastern), not the catalog id and "
            "not the display name — name is ambiguous. Resolve via the time-zone catalog "
            "before calling."
        )
    )
    start: datetime = Field(
        description="Required. Start timestamp (ISO-8601). Backstop rejects a create without it."
    )
    stop: datetime = Field(
        description="Required. Stop timestamp (ISO-8601). Backstop rejects a create without it."
    )
    location: str | None = Field(
        default=None,
        description="Where the meeting or call took place. Omit when there is none.",
    )
    attendee_party_ids: tuple[str, ...] = Field(
        default=(),
        description=(
            "Trusted Backstop people ids to add as attendees. Empty when there are none. "
            "Never invent or guess — echo ids from a prior resolve."
        ),
    )


class NoteActivityInput(_DatedTaggedActivityInput):
    """A CRM note. Notes have no attendees and no time zone."""

    kind: Literal["note"] = Field(
        description="Log a CRM note. Notes have no attendees or time zone."
    )
    description: str | None = Field(default=None, description="Note body. Omit when there is none.")


class MeetingActivityInput(_MeetingOrCallFields):
    """A face-to-face meeting. Maps to meeting-or-calls `type=FACE_TO_FACE` later."""

    kind: Literal["meeting"] = Field(
        description="Log a face-to-face meeting. Requires `time_zone`."
    )


class CallActivityInput(_MeetingOrCallFields):
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


class TaskActivityInput(ActivityBaseInput):
    """A CRM task. Tasks have no activity tags, no effective date, and no author field."""

    kind: Literal["task"] = Field(
        description="Log a CRM task. Requires `assigned_user`; tasks have no activity tags."
    )
    assigned_user: str = Field(
        description=(
            "Required. A `list_system_users` login (`userName`), not the caller and not a "
            "party id. Tasks have no author field; this is who the task is assigned to."
        )
    )
    description: str | None = Field(
        default=None, description="Task body, mapped to wire `details`. Omit when there is none."
    )
    due_date: date | datetime = Field(
        description=(
            "Required. Due day or timestamp. Backstop rejects a task create without it "
            '(`400 "Field dueDate is required"`).'
        )
    )
    send_notification: bool = Field(
        default=False,
        description=(
            "Whether Backstop should email the assignee. Defaults to false and is echoed "
            "on the response. Always sent explicitly: Backstop defaults an omitted flag to "
            "true, so the quiet default has to be written."
        ),
    )


type LogActivityInput = Annotated[
    NoteActivityInput | MeetingActivityInput | CallActivityInput | TaskActivityInput,
    Field(discriminator="kind", description=LOG_ACTIVITY_INPUT_DESCRIPTION),
]
