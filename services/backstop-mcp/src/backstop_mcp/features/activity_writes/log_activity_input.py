"""Discriminated `log_activity` input: each `kind` declares only its own required fields.

Pydantic rejects a meeting or call without `time_zone` before any HTTP call. Author is not a
parameter — the authenticated caller is the author. Party targeting matches
`PartyResolveItemDto` in spirit (exactly one of `party_id` or `search`) without importing that DTO.
"""

from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.party_resolver import (
    PARTY_ID_REQUIRES_SEARCH_TYPE_DESCRIPTION,
    REQUIRED_SEARCH_TYPE_DESCRIPTION,
    SEARCH_REQUIRES_SEARCH_TYPE_DESCRIPTION,
)

__all__ = [
    "CallActivityInput",
    "EmailActivityInput",
    "LogActivityInput",
    "MeetingActivityInput",
    "NoteActivityInput",
    "TaskActivityInput",
]

_NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

_SECONDARY_SEARCH_TYPE_DESCRIPTION = (
    "Collection for `secondary_party_id` when linking a second party (a person at an "
    "organisation). Pass together with `secondary_party_id`. Omit both when there is no "
    "secondary party."
)
_SECONDARY_PARTY_ID_DESCRIPTION = (
    "Trusted Backstop id of a second party to link (linkedResources / secondaryRegarding), "
    "for a person-at-organisation case. Pass together with `secondary_search_type`. "
    "Do not repeat the parent party. Never invent or guess."
)


class _PartyTargetInput(BaseModel):
    """Every log_activity variant attaches to one party the way `get_tasks_for_party` does."""

    search_type: SearchType = Field(description=REQUIRED_SEARCH_TYPE_DESCRIPTION)
    party_id: _NonEmptyStr | None = Field(
        default=None, description=PARTY_ID_REQUIRES_SEARCH_TYPE_DESCRIPTION
    )
    search: _NonEmptyStr | None = Field(
        default=None, description=SEARCH_REQUIRES_SEARCH_TYPE_DESCRIPTION
    )

    @field_validator("party_id", "search", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _exactly_one_selector(self) -> Self:
        if (self.party_id is None) == (self.search is None):
            raise ValueError("Exactly one of party_id or search must be provided")
        if self.party_id is not None and "/" in self.party_id:
            raise ValueError(f"party_id {self.party_id!r} must not contain '/'")
        return self


class _SecondaryPartyInput(BaseModel):
    """Optional second party for linkedResources / secondaryRegarding (parent excluded later)."""

    secondary_search_type: SearchType | None = Field(
        default=None, description=_SECONDARY_SEARCH_TYPE_DESCRIPTION
    )
    secondary_party_id: _NonEmptyStr | None = Field(
        default=None, description=_SECONDARY_PARTY_ID_DESCRIPTION
    )

    @field_validator("secondary_party_id", mode="before")
    @classmethod
    def _blank_secondary_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _secondary_pairing(self) -> Self:
        if (self.secondary_party_id is None) != (self.secondary_search_type is None):
            raise ValueError("secondary_party_id and secondary_search_type must be passed together")
        if self.secondary_party_id is not None and "/" in self.secondary_party_id:
            raise ValueError(f"secondary_party_id {self.secondary_party_id!r} must not contain '/'")
        return self


class _MeetingOrCallFields(BaseModel):
    """Shared meeting/call fields. `time_zone` is required — that is the discriminator's point."""

    title: str = Field(description="Title written on the meeting-or-call.")
    time_zone: str = Field(
        description=(
            "Required. A `/time-zones` shortName (e.g. US/Eastern), not the catalog id and "
            "not the display name — name is ambiguous. Resolve via the time-zone catalog "
            "before calling."
        )
    )
    start: datetime | None = Field(
        default=None, description="Start timestamp. Omit when Backstop should default."
    )
    stop: datetime | None = Field(
        default=None, description="Stop timestamp. Omit when Backstop should default."
    )
    location: str | None = Field(default=None, description="Where the meeting or call took place.")
    effective_date: date | None = Field(
        default=None,
        description="Calendar day on the activity, for backdating. Omit to use today.",
    )
    attendee_party_ids: tuple[str, ...] = Field(
        default=(),
        description="Backstop party ids to add as attendees. Empty when there are none.",
    )
    activity_tag_ids: tuple[str, ...] = Field(
        default=(),
        description="Activity-tag ids from `list_activity_tags`. Empty when none apply.",
    )


class NoteActivityInput(_PartyTargetInput, _SecondaryPartyInput):
    """A CRM note. Notes have no attendees and no time zone."""

    kind: Literal["note"] = Field(
        description="Log a CRM note. Notes have no attendees or time zone."
    )
    title: str = Field(description="Note title.")
    description: str | None = Field(default=None, description="Note body. Omit when there is none.")
    effective_date: date | None = Field(
        default=None,
        description="Calendar day on the note, for backdating. Omit to use today.",
    )
    activity_tag_ids: tuple[str, ...] = Field(
        default=(),
        description="Activity-tag ids from `list_activity_tags`. Empty when none apply.",
    )


class MeetingActivityInput(_PartyTargetInput, _SecondaryPartyInput, _MeetingOrCallFields):
    """A face-to-face meeting. Maps to meeting-or-calls `type=FACE_TO_FACE` later."""

    kind: Literal["meeting"] = Field(
        description="Log a face-to-face meeting. Requires `time_zone`."
    )


class CallActivityInput(_PartyTargetInput, _SecondaryPartyInput, _MeetingOrCallFields):
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


class TaskActivityInput(_PartyTargetInput, _SecondaryPartyInput):
    """A CRM task. Tasks have no activity tags, no effective date, and no author field."""

    kind: Literal["task"] = Field(
        description="Log a CRM task. Requires `assigned_user`; tasks have no activity tags."
    )
    title: str = Field(description="Task title. Mapped to wire `name` on create.")
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


class EmailActivityInput(_PartyTargetInput):
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
        default=None, description="Email format Backstop expects, when known."
    )
    activity_tag_ids: tuple[str, ...] = Field(
        default=(),
        description="Activity-tag ids from `list_activity_tags`. Empty when none apply.",
    )


type LogActivityInput = Annotated[
    NoteActivityInput
    | MeetingActivityInput
    | CallActivityInput
    | TaskActivityInput
    | EmailActivityInput,
    Field(discriminator="kind"),
]
