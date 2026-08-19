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

    id: str
    stream: BackstopActivityType
    title: str | None
    description: str | None
    effective_date: date | None
    resource_type: str | None = Field(
        default=None, validation_alias=AliasPath("specific_resource", "resource_type")
    )
    resource_id: str | None = Field(
        default=None, validation_alias=AliasPath("specific_resource", "resource_id")
    )
    created_timestamp: datetime | None
    modified_timestamp: datetime | None


class EmailItemDto(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    subject: str | None
    sent_timestamp: datetime | None
    from_email: str | None
    to_emails: tuple[str, ...]
    cc_emails: tuple[str, ...]
    has_attachments: bool | None
    content_url: str | None


class ActivityPageDto(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    items: tuple[ActivityItemDto, ...]
    end_of_stream: bool


class EmailPageDto(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    items: tuple[EmailItemDto, ...]
    end_of_stream: bool


class ActivityDetailDto(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    resource_id: str
    type: str | None
    title: str | None
    description: str | None


class MeetingSpecificsDto(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    start: datetime | None
    stop: datetime | None
    location: str | None
    time_zone: str | None


class AttendeeDto(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    name: str | None


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
