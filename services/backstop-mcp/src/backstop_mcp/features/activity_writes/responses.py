"""Published activity-write response models.

`LoggedActivityResponse` is a discriminated union on `kind`, matching the input: a note
does not carry `time_zone` or `send_notification`. `LogActivityResponse` is the later
`log_activity` return (success or unresolved party).
"""

from typing import Annotated, Literal

from pydantic import Field

from backstop_mcp.features.party_resolver import PartyAmbiguousResponse
from backstop_mcp.features.resolution import NotFoundResponse
from backstop_mcp.models import OmitNoneModel

__all__ = [
    "AttachFileResponse",
    "AttachedFileResponse",
    "DeletedActivityResponse",
    "LogActivityResponse",
    "LoggedActivityResponse",
    "LoggedCallResponse",
    "LoggedEmailResponse",
    "LoggedMeetingResponse",
    "LoggedNoteResponse",
    "LoggedTaskResponse",
    "UpdatedActivityResponse",
]

_ID_DESCRIPTION = "Backstop id of the created activity. Echo it; never invent one."
_TITLE_DESCRIPTION = "Title (or task name) as written. Omitted when the create did not send one."


class _LoggedActivityBase(OmitNoneModel):
    id: str = Field(description=_ID_DESCRIPTION)
    title: str | None = Field(default=None, description=_TITLE_DESCRIPTION)


class LoggedNoteResponse(_LoggedActivityBase):
    """A note after a successful create."""

    kind: Literal["note"] = Field(default="note", description="A CRM note.")
    resource_type: Literal["notes"] = Field(
        default="notes",
        description="Backstop collection this record lives in.",
    )


class LoggedMeetingResponse(_LoggedActivityBase):
    """A face-to-face meeting after a successful create."""

    kind: Literal["meeting"] = Field(default="meeting", description="A face-to-face meeting.")
    resource_type: Literal["meeting-or-calls"] = Field(
        default="meeting-or-calls",
        description="Backstop collection this record lives in.",
    )
    meeting_type: Literal["FACE_TO_FACE"] = Field(
        default="FACE_TO_FACE",
        description="Always FACE_TO_FACE for `kind=meeting`.",
    )
    time_zone: str = Field(
        description="The `/time-zones` shortName written on the meeting (e.g. US/Eastern)."
    )


class LoggedCallResponse(_LoggedActivityBase):
    """A phone call after a successful create."""

    kind: Literal["call"] = Field(default="call", description="A phone call.")
    resource_type: Literal["meeting-or-calls"] = Field(
        default="meeting-or-calls",
        description="Backstop collection this record lives in.",
    )
    meeting_type: Literal["PHONE_OUT", "PHONE_IN"] = Field(
        description="PHONE_OUT when we called them; PHONE_IN when they called us."
    )
    time_zone: str = Field(
        description="The `/time-zones` shortName written on the call (e.g. US/Eastern)."
    )


class LoggedTaskResponse(_LoggedActivityBase):
    """A task after a successful create."""

    kind: Literal["task"] = Field(default="task", description="A CRM task.")
    resource_type: Literal["tasks"] = Field(
        default="tasks",
        description="Backstop collection this record lives in.",
    )
    send_notification: bool = Field(
        description="Echo of the task `send_notification` flag. False unless the caller set it."
    )


class LoggedEmailResponse(_LoggedActivityBase):
    """An email metadata stub after a successful create."""

    kind: Literal["email"] = Field(default="email", description="An email metadata stub.")
    resource_type: Literal["emails"] = Field(
        default="emails",
        description="Backstop collection this record lives in.",
    )


type LoggedActivityResponse = Annotated[
    LoggedNoteResponse
    | LoggedMeetingResponse
    | LoggedCallResponse
    | LoggedTaskResponse
    | LoggedEmailResponse,
    Field(discriminator="kind"),
]


class AttachedFileResponse(OmitNoneModel):
    """A document or email after a successful file attach."""

    id: str = Field(description="Backstop id of the created document or email. Echo it.")
    kind: Literal["document", "email"] = Field(
        description="Which collection the file was created in: document or email."
    )


class UpdatedActivityResponse(OmitNoneModel):
    """An activity after a successful PATCH."""

    id: str = Field(description="Backstop id of the updated activity. Echo it; never invent one.")
    resource_type: Literal["notes", "meeting-or-calls", "tasks", "emails", "documents"] = Field(
        description="Backstop collection this record lives in."
    )


class DeletedActivityResponse(OmitNoneModel):
    """A hard delete: Backstop has no recycle bin, so `permanent` is always true."""

    id: str = Field(description="Backstop id of the deleted activity.")
    resource_type: Literal["notes", "meeting-or-calls", "tasks", "emails", "documents"] = Field(
        description="Backstop collection the deleted record lived in."
    )
    permanent: Literal[True] = Field(
        default=True,
        description="Always true: Backstop hard-deletes the record. There is no recycle bin.",
    )


type LogActivityResponse = LoggedActivityResponse | PartyAmbiguousResponse | NotFoundResponse

type AttachFileResponse = AttachedFileResponse | PartyAmbiguousResponse | NotFoundResponse
