import logging
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import ClassVar, Literal, Self, cast

from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, ValidationError

from backstop_mcp.backstop_client import ResourceRef
from backstop_mcp.features.activity_history.api_responses import (
    ActivityAttributes,
    EmailAttributes,
    EntityActivityAttributes,
)
from backstop_mcp.features.entity_types import SearchType, party_search_type

logger = logging.getLogger(__name__)

__all__ = [
    "ActivityAttachmentDto",
    "ActivityDetailDto",
    "ActivityItemDto",
    "ActivityPageDto",
    "ActivityRegardingDto",
    "ActivityTagChipDto",
    "AttendeeChipDto",
    "AttendeeDto",
    "BackstopActivityType",
    "EmailItemDto",
    "EmailPageDto",
    "EntityActivitiesFetchDto",
    "EntityActivityDto",
    "MeetingSpecificsDto",
    "ResourceIdentifierDto",
]

_MEETING_OR_CALL_RESOURCE_TYPE = "meeting-or-calls"

BackstopActivityType = Literal["meeting", "call", "note", "document"]


class ActivityRegardingDto(BaseModel):
    """The party or resource an activity row is about, from the inline `regarding` attribute."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    resource_type: str | None = None
    resource_link: str | None = None
    search_type: SearchType | None = None

    @classmethod
    def from_stored(cls, value: object) -> Self | None:
        if value is None:
            return None
        try:
            ref = ResourceRef.model_validate(value)
        except ValidationError:
            return None
        resource_type = ref.resource_type
        return cls(
            id=ref.resource_id,
            resource_type=resource_type,
            resource_link=ref.resource_link,
            search_type=party_search_type(resource_type) if resource_type else None,
        )


class ActivityTagChipDto(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    name: str


class AttendeeChipDto(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str | None = None
    name: str | None = None


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
    regarding: ActivityRegardingDto | None = None
    tags: tuple[ActivityTagChipDto, ...] = ()
    attendees: tuple[AttendeeChipDto, ...] = ()

    @classmethod
    def from_attributes(
        cls,
        item_id: str,
        stream: BackstopActivityType,
        attributes: ActivityAttributes,
        *,
        tags: tuple[ActivityTagChipDto, ...] = (),
        attendees: tuple[AttendeeChipDto, ...] = (),
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
            regarding=ActivityRegardingDto.from_stored(attributes.regarding),
            tags=tags,
            attendees=attendees,
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


class ActivityAttachmentDto(BaseModel):
    """One file on `/entity-activity-details`. Shape is undocumented — degrade, do not raise."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str | None = None
    name: str | None = None


def attachments_from_stored(value: object) -> tuple[ActivityAttachmentDto, ...]:
    """Project Backstop's `attachments` attribute into chips. Unexpected shapes become empty."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    items: list[ActivityAttachmentDto] = []
    for raw in value:
        if isinstance(raw, str):
            name = raw.strip()
            if name:
                items.append(ActivityAttachmentDto(name=name))
            continue
        if not isinstance(raw, Mapping):
            continue
        mapping = cast(Mapping[object, object], raw)
        raw_id = mapping.get("id") or mapping.get("resourceId")
        raw_name = (
            mapping.get("name")
            or mapping.get("fileName")
            or mapping.get("filename")
            or mapping.get("title")
        )
        attachment_id = raw_id.strip() if isinstance(raw_id, str) else None
        name = raw_name.strip() if isinstance(raw_name, str) else None
        if attachment_id or name:
            items.append(ActivityAttachmentDto(id=attachment_id or None, name=name or None))
    return tuple(items)


class ActivityDetailDto(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    # Without a resource id the detail cannot be keyed back to the handle that fetched it.
    resource_id: str
    type: str | None = None
    title: str | None = None
    description: str | None = None
    attachments: tuple[ActivityAttachmentDto, ...] = ()


class MeetingSpecificsDto(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    start: datetime | None = None
    stop: datetime | None = None
    location: str | None = None
    time_zone: str | None = None


class AttendeeDto(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    name: str | None = None


class ResourceIdentifierDto(BaseModel):
    """The `{resourceType}_{resourceId}` handle a timeline record carries as its `activity_id`.

    Confirmed live across all four activity streams: every record `/{segment}/{id}/activities`
    returns has an id of exactly `f"{specificResource.resourceType}_{specificResource.resourceId}"`
    — `meeting-or-calls_76537547` (both meetings and calls), `notes_26018215`,
    `documents_127746731`. That composite is the only id `get_activity_history` hands out, so the
    model always holds a resource type alongside a resource id and never has to guess which
    collection an id belongs to.

    The detail endpoints go the other way: `/entity-activity-details/{id}`,
    `/meeting-or-calls/{id}` and `/meeting-or-calls/{id}/attendees` all take the **bare**
    `resource_id`. Passing the composite to `/entity-activity-details` does not 404 — it answers
    `200 {"data": null}`, so the mistake surfaces as a schema error rather than a not-found (see
    `BackstopApiResourceDocument.require_data`). This is where the two forms meet, so that
    translation happens once instead of at each call site.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    resource_type: str
    resource_id: str

    @classmethod
    def from_activity_id(cls, activity_id: str) -> Self:
        """Split a timeline `activity_id` into its resource type and bare resource id.

        Splits on the LAST underscore: resource ids are numeric, while a resource type can carry
        hyphens (`meeting-or-calls`), so the final separator is the unambiguous one.
        """
        resource_type, separator, resource_id = activity_id.rpartition("_")
        if not separator or not resource_type or not resource_id:
            logger.info("activity_history.handle.malformed", extra={"activity_id": activity_id})
            raise ToolError(
                f"{activity_id!r} is not a valid activity_id. Expected "
                + "'{resource_type}_{resource_id}' (e.g. 'meeting-or-calls_76537547', "
                + "'notes_26018215'), exactly as a get_activity_history record reports it."
            )
        return cls(resource_type=resource_type, resource_id=resource_id)

    @property
    def is_meeting_or_call(self) -> bool:
        return self.resource_type == _MEETING_OR_CALL_RESOURCE_TYPE


class EntityActivityDto(BaseModel):
    """One projected entity-activities row. A row without `id` is dropped by the fetch."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    type: str | None = None
    activity_type: str | None = None
    title: str | None = None
    effective_date: date | None = None
    created_at: date | None = None
    modified_at: date | None = None
    start: datetime | None = None
    stop: datetime | None = None
    time_zone: str | None = None
    location: str | None = None
    meeting_type: str | None = None
    short_description: str | None = None
    description: str | None = None
    attachments_count: int | None = None
    author: AttendeeChipDto | None = None
    attendees: tuple[str, ...] = ()
    tags: tuple[ActivityTagChipDto, ...] = ()
    associated_with: tuple[ActivityRegardingDto, ...] = ()
    from_address: str | None = None
    to_addresses: tuple[str, ...] = ()

    @classmethod
    def from_attributes(cls, attributes: EntityActivityAttributes) -> Self | None:
        if not attributes.id:
            return None
        author = attributes.author
        return cls(
            id=attributes.id,
            type=attributes.type,
            activity_type=attributes.activity_type,
            title=attributes.title,
            effective_date=attributes.effective_date,
            created_at=attributes.created_at,
            modified_at=attributes.modified_at,
            start=attributes.start_date,
            stop=attributes.stop_date,
            time_zone=attributes.time_zone,
            location=attributes.location,
            meeting_type=attributes.meeting_type,
            short_description=attributes.short_description,
            description=attributes.formatted_description,
            attachments_count=attributes.attachments_count,
            author=(None if author is None else AttendeeChipDto(name=author.name, id=author.id)),
            attendees=tuple(
                name for chip in attributes.attendees if (name := chip.name) is not None
            ),
            tags=tuple(
                ActivityTagChipDto(id=tag.id, name=tag.name)
                for tag in attributes.activity_tags
                if tag.id and tag.name
            ),
            associated_with=tuple(
                ActivityRegardingDto(
                    id=party.resource_id,
                    resource_type=party.resource_type,
                    resource_link=party.resource_link,
                    search_type=(
                        party_search_type(party.resource_type) if party.resource_type else None
                    ),
                )
                for party in attributes.associated_with
                if party.resource_id
            ),
            from_address=None if attributes.from_address is None else attributes.from_address.name,
            to_addresses=tuple(
                address.name for address in attributes.to_addresses if address.name is not None
            ),
        )


class EntityActivitiesFetchDto(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    rows: tuple[EntityActivityDto, ...]
    total_count: int | None
    rows_dropped: int
    rows_received: int
    pages_fetched: int
    ceiling_clamped: bool
    truncated_by_row_cap: bool
    partial_due_to_error: bool = False
