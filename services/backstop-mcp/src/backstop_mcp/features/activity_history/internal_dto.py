from datetime import date, datetime
from typing import Annotated, ClassVar, Literal, Self

from pydantic import AliasPath, BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "ActivityDetailDto",
    "ActivityHandleDto",
    "ActivityItemDto",
    "ActivityPageDto",
    "AttendeeDto",
    "BackstopActivityType",
    "DateRangeDto",
    "EmailItemDto",
    "EmailPageDto",
    "MeetingSpecificsDto",
]

BackstopActivityType = Literal["meeting", "call", "note", "document"]


class ActivityItemDto(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, populate_by_name=True)

    # A row with no id is not a record: timeline handles and detail fetches key on it.
    id: str
    # Without the stream the row cannot be typed or routed onto the right collection.
    stream: BackstopActivityType
    title: str | None = None
    description: str | None = None
    effective_date: date | None = None
    resource_type: str | None = Field(
        default=None, validation_alias=AliasPath("specific_resource", "resource_type")
    )
    resource_id: str | None = Field(
        default=None, validation_alias=AliasPath("specific_resource", "resource_id")
    )
    created_timestamp: datetime | None = None
    modified_timestamp: datetime | None = None


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


class DateRangeDto(BaseModel):
    """Min/max `occurred_at` among this page's dated items."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    start: Annotated[
        date,
        Field(description="Oldest `occurred_at` date among this page's dated items."),
    ]
    end: Annotated[
        date,
        Field(description="Newest `occurred_at` date among this page's dated items."),
    ]

    @model_validator(mode="after")
    def _start_not_after_end(self) -> Self:
        if self.start > self.end:
            raise ValueError("date_range.start must not be after date_range.end")
        return self


class ActivityHandleDto(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    resource_type: str
    resource_id: str

    @property
    def is_meeting_or_call(self) -> bool:
        return self.resource_type == "meeting-or-calls"
