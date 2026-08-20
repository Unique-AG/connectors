from typing import ClassVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from backstop_mcp.dates import LenientDate, LenientDatetime
from backstop_mcp.lenient import LenientBool

__all__ = [
    "ActivityAttributes",
    "ActivityDetailAttributes",
    "AttendeeAttributes",
    "EmailAttributes",
    "MeetingSpecificAttributes",
    "SpecificResourceAttributes",
]


class SpecificResourceAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    resource_type: str | None = Field(
        default=None, validation_alias=AliasChoices("resourceType", "resource_type")
    )
    resource_id: str | None = Field(
        default=None, validation_alias=AliasChoices("resourceId", "resource_id")
    )


class ActivityAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    title: str | None = None
    description: str | None = None
    effective_date: LenientDate = Field(
        default=None, validation_alias=AliasChoices("effectiveDate", "effective_date")
    )
    specific_resource: SpecificResourceAttributes | None = Field(
        default=None, validation_alias=AliasChoices("specificResource", "specific_resource")
    )
    created_timestamp: LenientDatetime = Field(
        default=None, validation_alias=AliasChoices("createdTimestamp", "created_timestamp")
    )
    modified_timestamp: LenientDatetime = Field(
        default=None, validation_alias=AliasChoices("modifiedTimestamp", "modified_timestamp")
    )
    regarding: object | None = None


class EmailAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    subject: str | None = None
    sent_timestamp: LenientDatetime = Field(
        default=None, validation_alias=AliasChoices("sentTimestamp", "sent_timestamp")
    )
    from_email: str | None = Field(
        default=None, validation_alias=AliasChoices("fromEmail", "from_email")
    )
    to_emails: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("toEmails", "to_emails"),
    )
    cc_emails: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("ccEmails", "cc_emails"),
    )
    has_attachments: LenientBool = Field(
        default=None, validation_alias=AliasChoices("hasAttachments", "has_attachments")
    )
    content_url: str | None = Field(
        default=None, validation_alias=AliasChoices("contentUrl", "content_url")
    )


class ActivityDetailAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    type: str | None = None
    title: str | None = None
    description: str | None = None


class MeetingSpecificAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    start: LenientDatetime = Field(default=None, validation_alias="startTimestamp")
    stop: LenientDatetime = Field(default=None, validation_alias="stopTimestamp")
    location: str | None = None
    time_zone: str | None = Field(default=None, validation_alias="timeZone")


class AttendeeAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    name: str | None = None
    first_name: str | None = Field(default=None, validation_alias="firstName")
    last_name: str | None = Field(default=None, validation_alias="lastName")

    def display_name(self) -> str | None:
        if self.name:
            return self.name
        composed = " ".join(part for part in (self.first_name, self.last_name) if part)
        return composed or None
