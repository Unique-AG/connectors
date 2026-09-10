"""Discriminated `update_activity` input: each `kind` declares only its patchable fields.

`activity_id` is required. Every other field is optional — omit to leave it unchanged.
At least one change field must be set. Author is not a parameter. Parsed email fields
(`subject`, from, to) are not editable; only `display_subject` and tags are.
"""

from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, StringConstraints, model_validator

__all__ = [
    "UPDATE_ACTIVITY_INPUT_DESCRIPTION",
    "UpdateActivityInput",
    "UpdateCallInput",
    "UpdateDocumentInput",
    "UpdateEmailInput",
    "UpdateMeetingInput",
    "UpdateNoteInput",
    "UpdateTaskInput",
]

UPDATE_ACTIVITY_INPUT_DESCRIPTION = (
    "Required. The activity to patch. Discriminated by `kind`: `note`, `meeting`, `call`, "
    "`task`, `email`, or `document`. Needs `activity_id` (create echo, search row, or "
    "history handle) and at least one field to change. Never invent an id. Email PATCH "
    "accepts only `display_subject` and `activity_tag_ids`."
)

_NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_IDENTITY_FIELDS = frozenset({"kind", "activity_id"})

_ACTIVITY_ID_DESCRIPTION = (
    "Required. Backstop id from a create echo, a `search_activities` row, or a "
    "`get_activity_history` handle (`notes_123`, `meeting-or-calls_123`). Never invent or guess."
)


class _ActivityIdInput(BaseModel):
    activity_id: _NonEmptyStr = Field(description=_ACTIVITY_ID_DESCRIPTION)

    @model_validator(mode="after")
    def _at_least_one_change(self) -> Self:
        for name in type(self).model_fields:
            if name in _IDENTITY_FIELDS:
                continue
            if getattr(self, name) is not None:
                return self
        raise ValueError("Pass at least one field to change")


class UpdateNoteInput(_ActivityIdInput):
    """PATCH a CRM note."""

    kind: Literal["note"] = Field(description="Update a CRM note.")
    title: _NonEmptyStr | None = Field(default=None, description="Replacement note title.")
    description: _NonEmptyStr | None = Field(default=None, description="Replacement note body.")
    effective_date: date | None = Field(
        default=None, description="Replacement calendar day on the note."
    )
    activity_tag_ids: tuple[str, ...] | None = Field(
        default=None,
        description=(
            "Replacement activity-tag ids from `list_activity_tags`. Empty tuple clears tags. "
            "Omit to leave tags unchanged."
        ),
    )


class _UpdateMeetingOrCallFields(_ActivityIdInput):
    title: _NonEmptyStr | None = Field(
        default=None, description="Replacement title written on the meeting or call."
    )
    time_zone: _NonEmptyStr | None = Field(
        default=None,
        description=(
            "Replacement `/time-zones` shortName (e.g. US/Eastern), not the catalog id and "
            "not the display name. Omit to leave the zone unchanged."
        ),
    )
    start: datetime | None = Field(
        default=None, description="Replacement start timestamp (ISO-8601)."
    )
    stop: datetime | None = Field(
        default=None, description="Replacement stop timestamp (ISO-8601)."
    )
    location: _NonEmptyStr | None = Field(
        default=None, description="Replacement location. Omit to leave it unchanged."
    )
    effective_date: date | None = Field(
        default=None, description="Replacement calendar day on the activity."
    )
    attendee_party_ids: tuple[str, ...] | None = Field(
        default=None,
        description=(
            "Replacement trusted people ids as attendees. Empty tuple clears attendees. "
            "Omit to leave them unchanged. Never invent or guess."
        ),
    )
    activity_tag_ids: tuple[str, ...] | None = Field(
        default=None,
        description=(
            "Replacement activity-tag ids from `list_activity_tags`. Empty tuple clears tags. "
            "Omit to leave tags unchanged."
        ),
    )


class UpdateMeetingInput(_UpdateMeetingOrCallFields):
    """PATCH a face-to-face meeting."""

    kind: Literal["meeting"] = Field(description="Update a face-to-face meeting.")


class UpdateCallInput(_UpdateMeetingOrCallFields):
    """PATCH a phone call."""

    kind: Literal["call"] = Field(description="Update a phone call.")
    direction: Literal["PHONE_OUT", "PHONE_IN"] | None = Field(
        default=None,
        description=(
            "Replacement meeting-or-calls `type`: PHONE_OUT or PHONE_IN. Omit to leave it "
            "unchanged."
        ),
    )


class UpdateTaskInput(_ActivityIdInput):
    """PATCH a CRM task."""

    kind: Literal["task"] = Field(description="Update a CRM task.")
    title: _NonEmptyStr | None = Field(
        default=None, description="Replacement task title. Mapped to Backstop `name`."
    )
    assigned_user: _NonEmptyStr | None = Field(
        default=None,
        description=(
            "Replacement `list_system_users` login (`userName`), not a party id. Omit to "
            "leave the assignee unchanged."
        ),
    )
    description: _NonEmptyStr | None = Field(
        default=None, description="Replacement task body, mapped to wire `details`."
    )
    due_date: date | datetime | None = Field(
        default=None, description="Replacement due day or timestamp."
    )
    send_notification: bool | None = Field(
        default=None,
        description="Whether Backstop should notify the assignee after this update.",
    )


class UpdateEmailInput(_ActivityIdInput):
    """PATCH email metadata. Parsed subject/from/to are not writable."""

    kind: Literal["email"] = Field(
        description=(
            "Update email metadata. Only `display_subject` and `activity_tag_ids` are "
            "writable; parsed fields are not."
        )
    )
    display_subject: _NonEmptyStr | None = Field(
        default=None, description="Replacement display subject written on the email."
    )
    activity_tag_ids: tuple[str, ...] | None = Field(
        default=None,
        description=(
            "Replacement activity-tag ids from `list_activity_tags`. Empty tuple clears tags. "
            "Omit to leave tags unchanged."
        ),
    )


class UpdateDocumentInput(_ActivityIdInput):
    """PATCH a document's metadata. The file blob is not replaced here."""

    kind: Literal["document"] = Field(
        description="Update document metadata. The file blob is not replaced — use a new attach."
    )
    title: _NonEmptyStr | None = Field(default=None, description="Replacement document title.")
    description: _NonEmptyStr | None = Field(
        default=None, description="Replacement document description."
    )
    effective_date: date | None = Field(
        default=None, description="Replacement calendar day on the document."
    )
    activity_tag_ids: tuple[str, ...] | None = Field(
        default=None,
        description=(
            "Replacement activity-tag ids from `list_activity_tags`. Empty tuple clears tags. "
            "Omit to leave tags unchanged."
        ),
    )


type UpdateActivityInput = Annotated[
    UpdateNoteInput
    | UpdateMeetingInput
    | UpdateCallInput
    | UpdateTaskInput
    | UpdateEmailInput
    | UpdateDocumentInput,
    Field(discriminator="kind", description=UPDATE_ACTIVITY_INPUT_DESCRIPTION),
]
