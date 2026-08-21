from datetime import date, datetime
from typing import ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict

from backstop_mcp.features.activity_history.api_responses import (
    ActivityAttributes,
    EmailAttributes,
)

__all__ = [
    "ActivityDetailDto",
    "ActivityHandleDto",
    "ActivityItemDto",
    "ActivityPageDto",
    "AttendeeDto",
    "BackstopActivityType",
    "EmailItemDto",
    "EmailPageDto",
    "MeetingSpecificsDto",
]

BackstopActivityType = Literal["meeting", "call", "note", "document"]


class ActivityItemDto(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    # A row with no id is not a record: timeline handles and detail fetches key on it.
    id: str
    # Without the stream the row cannot be typed or routed onto the right collection.
    stream: BackstopActivityType
    title: str | None = None
    description: str | None = None
    effective_date: date | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    created_timestamp: datetime | None = None
    modified_timestamp: datetime | None = None

    @classmethod
    def from_attributes(
        cls,
        item_id: str,
        stream: BackstopActivityType,
        attributes: ActivityAttributes,
    ) -> Self:
        specific = attributes.specific_resource
        return cls(
            id=item_id,
            stream=stream,
            title=attributes.title,
            description=attributes.description,
            effective_date=attributes.effective_date,
            resource_type=None if specific is None else specific.resource_type,
            resource_id=None if specific is None else specific.resource_id,
            created_timestamp=attributes.created_timestamp,
            modified_timestamp=attributes.modified_timestamp,
        )


class EmailItemDto(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    # A row with no id is not a record: timeline handles key on it.
    id: str
    subject: str | None = None
    sent_timestamp: datetime | None = None
    from_email: str | None = None
    to_emails: tuple[str, ...] = ()
    cc_emails: tuple[str, ...] = ()
    has_attachments: bool | None = None
    content_url: str | None = None

    @classmethod
    def from_attributes(cls, item_id: str, attributes: EmailAttributes) -> Self:
        return cls(
            id=item_id,
            subject=attributes.subject,
            sent_timestamp=attributes.sent_timestamp,
            from_email=attributes.from_email,
            to_emails=tuple(attributes.to_emails),
            cc_emails=tuple(attributes.cc_emails),
            has_attachments=attributes.has_attachments,
            content_url=attributes.content_url,
        )


class ActivityPageDto(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    items: tuple[ActivityItemDto, ...] = ()
    # Without this, a short page and a full page are indistinguishable.
    end_of_stream: bool


class EmailPageDto(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    items: tuple[EmailItemDto, ...] = ()
    # Without this, a short page and a full page are indistinguishable.
    end_of_stream: bool


class ActivityDetailDto(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    # Without a resource id the detail cannot be keyed back to the handle that fetched it.
    resource_id: str
    type: str | None = None
    title: str | None = None
    description: str | None = None


class MeetingSpecificsDto(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    start: datetime | None = None
    stop: datetime | None = None
    location: str | None = None
    time_zone: str | None = None


class AttendeeDto(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    name: str | None = None


class ActivityHandleDto(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    resource_type: str
    resource_id: str

    @property
    def is_meeting_or_call(self) -> bool:
        return self.resource_type == "meeting-or-calls"
