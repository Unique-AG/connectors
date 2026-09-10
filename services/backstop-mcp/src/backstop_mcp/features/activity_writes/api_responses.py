"""Write-side Backstop wire shapes for activity POST/PATCH responses.

Subset we read back after a create or update. Every field is optional so one renamed key
costs that field, not the parse. `extra="ignore"` drops permission flags and the rest of the
wire we do not publish. Do not import read-side `EmailAttributes` or `TaskAttributes` —
those are different subsets for different features.
"""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.dates import LenientDate, LenientDatetime
from backstop_mcp.lenient import LenientBool

__all__ = [
    "DeletedResourceAttributes",
    "DocumentAttributes",
    "EmailAttributes",
    "MeetingOrCallAttributes",
    "NoteAttributes",
    "ResourceLinkAttributes",
    "TaskAttributes",
]


class DeletedResourceAttributes(BaseModel):
    """No fields: `DELETE` answers `204` with an empty body, so nothing is read back."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")


class ResourceLinkAttributes(BaseModel):
    """A Backstop `{resourceId, resourceType, resourceLink}` pointer (attachedTo, regarding)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    resource_id: str | None = Field(default=None, validation_alias="resourceId")
    resource_type: str | None = Field(default=None, validation_alias="resourceType")
    resource_link: str | None = Field(default=None, validation_alias="resourceLink")


class NoteAttributes(BaseModel):
    """Wire shape for `notes` attributes (subset we read back after create/update)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    title: str | None = None
    description: str | None = None
    effective_date: LenientDate = Field(default=None, validation_alias="effectiveDate")
    attached_to: ResourceLinkAttributes | None = Field(default=None, validation_alias="attachedTo")
    linked_resources: tuple[ResourceLinkAttributes, ...] | None = Field(
        default=None, validation_alias="linkedResources"
    )


class MeetingOrCallAttributes(BaseModel):
    """Wire shape for `meeting-or-calls` attributes (subset we read back after create/update)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    title: str | None = None
    type: str | None = None
    location: str | None = None
    start_timestamp: LenientDatetime = Field(default=None, validation_alias="startTimestamp")
    stop_timestamp: LenientDatetime = Field(default=None, validation_alias="stopTimestamp")
    time_zone: str | None = Field(default=None, validation_alias="timeZone")
    effective_date: LenientDate = Field(default=None, validation_alias="effectiveDate")
    regarding: ResourceLinkAttributes | None = None
    linked_resources: tuple[ResourceLinkAttributes, ...] | None = Field(
        default=None, validation_alias="linkedResources"
    )
    attendees: object | None = None


class TaskAttributes(BaseModel):
    """Write-side wire shape for `tasks` attributes (name/details, not title/description)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: str | None = None
    details: str | None = None
    status: str | None = None
    due_date: LenientDate = Field(default=None, validation_alias="dueDate")
    send_notification: LenientBool = Field(default=None, validation_alias="sendNotification")
    attached_to: ResourceLinkAttributes | None = Field(default=None, validation_alias="attachedTo")


class EmailAttributes(BaseModel):
    """Wire shape for creatable `emails` attributes (displaySubject, not subject/from/to)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    display_subject: str | None = Field(default=None, validation_alias="displaySubject")
    email_format: str | None = Field(default=None, validation_alias="emailFormat")
    resources: tuple[ResourceLinkAttributes, ...] | None = None
    created_by: object | None = Field(default=None, validation_alias="createdBy")


class DocumentAttributes(BaseModel):
    """Wire shape for `documents` attributes (subset we read back after attach)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: str | None = None
    title: str | None = None
    description: str | None = None
    file_name: str | None = Field(default=None, validation_alias="fileName")
    document_name: str | None = Field(default=None, validation_alias="documentName")
    attached_to: ResourceLinkAttributes | None = Field(default=None, validation_alias="attachedTo")
