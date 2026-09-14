from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import ClassVar, Self, cast

from pydantic import BaseModel, ConfigDict, ValidationError

from backstop_mcp.backstop_client import ResourceRef
from backstop_mcp.features.activity_history.api_responses import (
    EntityActivityAttributes,
)
from backstop_mcp.features.entity_types import SearchType, party_search_type

__all__ = [
    "ActivityAttachmentDto",
    "ActivityDetailDto",
    "ActivityRegardingDto",
    "ActivityTagChipDto",
    "AttendeeChipDto",
    "AttendeeDto",
    "EntityActivitiesFetchDto",
    "EntityActivityDto",
    "MeetingSpecificsDto",
]


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
