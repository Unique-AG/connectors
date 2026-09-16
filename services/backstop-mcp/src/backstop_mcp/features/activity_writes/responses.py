"""Published activity-write response models.

`LoggedActivityResponse` is a discriminated union on `kind`, matching the input: a note
does not carry `time_zone` or `send_notification`. `LogActivityResponse` is the later
`log_activity` return (success or unresolved party). There is no logged-email member —
`POST /emails` requires the message blob, so email creates are `attach_file` only.
"""

from typing import Annotated, Literal

from pydantic import Field

from backstop_mcp.features.elicitation_utils import DeletionNeedsConfirmationResponse
from backstop_mcp.features.party_resolver import PartyAmbiguousResponse
from backstop_mcp.features.resolution import NotFoundResponse
from backstop_mcp.models import OmitNoneModel

__all__ = [
    "ActivityBaseResponse",
    "AttachFileResponse",
    "AttachedFileResponse",
    "DeleteActivityResponse",
    "DeletedActivityResponse",
    "LogActivityResponse",
    "LoggedActivityResponse",
    "LoggedCallResponse",
    "LoggedMeetingResponse",
    "LoggedNoteResponse",
    "LoggedTaskResponse",
    "UpdatedActivityResponse",
]

_ID_DESCRIPTION = "Backstop id of the activity. Echo it; never invent one."
_TITLE_DESCRIPTION = "Title (or task name) as written. Omitted when the create did not send one."
_COLLECTION_DESCRIPTION = "Backstop collection this record lives in."
_RESOURCE_TYPE = Literal["notes", "meeting-or-calls", "tasks", "emails", "documents"]


class ActivityBaseResponse(OmitNoneModel):
    """Id every activity-write success response echoes."""

    id: str = Field(description=_ID_DESCRIPTION)


class _LoggedActivityResponse(ActivityBaseResponse):
    title: str | None = Field(default=None, description=_TITLE_DESCRIPTION)


class _LoggedMeetingOrCallResponse(_LoggedActivityResponse):
    resource_type: Literal["meeting-or-calls"] = Field(
        default="meeting-or-calls",
        description=_COLLECTION_DESCRIPTION,
    )
    time_zone: str = Field(
        description="The `/time-zones` shortName written on the meeting or call (e.g. US/Eastern)."
    )


class LoggedNoteResponse(_LoggedActivityResponse):
    """A note after a successful create."""

    kind: Literal["note"] = Field(default="note", description="A CRM note.")
    resource_type: Literal["notes"] = Field(
        default="notes",
        description=_COLLECTION_DESCRIPTION,
    )


class LoggedMeetingResponse(_LoggedMeetingOrCallResponse):
    """A face-to-face meeting after a successful create."""

    kind: Literal["meeting"] = Field(default="meeting", description="A face-to-face meeting.")
    meeting_type: Literal["FACE_TO_FACE"] = Field(
        default="FACE_TO_FACE",
        description="Always FACE_TO_FACE for `kind=meeting`.",
    )


class LoggedCallResponse(_LoggedMeetingOrCallResponse):
    """A phone call after a successful create."""

    kind: Literal["call"] = Field(default="call", description="A phone call.")
    meeting_type: Literal["PHONE_OUT", "PHONE_IN"] = Field(
        description="PHONE_OUT when we called them; PHONE_IN when they called us."
    )


class LoggedTaskResponse(_LoggedActivityResponse):
    """A task after a successful create."""

    kind: Literal["task"] = Field(default="task", description="A CRM task.")
    resource_type: Literal["tasks"] = Field(
        default="tasks",
        description=_COLLECTION_DESCRIPTION,
    )
    send_notification: bool = Field(
        description="Echo of the task `send_notification` flag. False unless the caller set it."
    )


type LoggedActivityResponse = Annotated[
    LoggedNoteResponse | LoggedMeetingResponse | LoggedCallResponse | LoggedTaskResponse,
    Field(discriminator="kind"),
]


class AttachedFileResponse(ActivityBaseResponse):
    """A document or email after a successful file attach."""

    kind: Literal["document", "email"] = Field(
        description="Which collection the file was created in: document or email."
    )


class UpdatedActivityResponse(ActivityBaseResponse):
    """An activity after a successful PATCH."""

    resource_type: _RESOURCE_TYPE = Field(description=_COLLECTION_DESCRIPTION)


class DeletedActivityResponse(ActivityBaseResponse):
    """A hard delete: Backstop has no recycle bin, so `permanent` is always true."""

    resource_type: _RESOURCE_TYPE = Field(
        description="Backstop collection the deleted record lived in."
    )
    permanent: Literal[True] = Field(
        default=True,
        description="Always true: Backstop hard-deletes the record. There is no recycle bin.",
    )


type DeleteActivityResponse = DeletedActivityResponse | DeletionNeedsConfirmationResponse

type LogActivityResponse = LoggedActivityResponse | PartyAmbiguousResponse | NotFoundResponse

type AttachFileResponse = AttachedFileResponse | PartyAmbiguousResponse | NotFoundResponse
