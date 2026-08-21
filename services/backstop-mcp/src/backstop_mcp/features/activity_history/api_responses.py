from typing import Annotated, ClassVar, cast

from pydantic import AliasChoices, BaseModel, BeforeValidator, ConfigDict, Field

from backstop_mcp.dates import LenientDate, LenientDatetime
from backstop_mcp.lenient import LenientBool, LenientInt

__all__ = [
    "ActivityAttributes",
    "ActivityDetailAttributes",
    "AttendeeAttributes",
    "EmailAttributes",
    "EntityActivitiesDocument",
    "EntityActivitiesPageAttributes",
    "EntityActivityAddressAttributes",
    "EntityActivityAssociatedWithAttributes",
    "EntityActivityAttributes",
    "EntityActivityNamedAttributes",
    "EntityActivityTagAttributes",
    "MeetingSpecificAttributes",
    "SpecificResourceAttributes",
]


def _wire_id(value: object) -> object:
    """Entity-activities ids arrive as ints (row `id`, tag `id`, author `id`)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value.strip() or None
    return None


def _dict_rows(value: object) -> tuple[dict[str, object], ...]:
    """Keep only dict rows so one junk entry cannot fail the page."""
    if not isinstance(value, list):
        return ()
    rows: list[dict[str, object]] = []
    for item in cast("list[object]", value):
        if not isinstance(item, dict):
            continue
        typed = {str(key): inner for key, inner in cast("dict[object, object]", item).items()}
        rows.append(typed)
    return tuple(rows)


WireId = Annotated[str | None, BeforeValidator(_wire_id)]
_ResultRows = Annotated[tuple[dict[str, object], ...], BeforeValidator(_dict_rows)]


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
    attachments: object = None


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


class EntityActivityNamedAttributes(BaseModel):
    """`author` / `createdBy` / `attendees[]` / `fromAddress` chips on a search row."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    name: str | None = None
    id: WireId = None


class EntityActivityTagAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    id: WireId = None
    name: str | None = None


class EntityActivityAssociatedWithAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    resource_id: WireId = Field(default=None, alias="resourceId")
    resource_type: str | None = Field(default=None, alias="resourceType")
    resource_link: str | None = Field(default=None, alias="resourceLink")


class EntityActivityAddressAttributes(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    name: str | None = None


class EntityActivityAttributes(BaseModel):
    """One `results[]` row from `POST /entity-activities`. Shape varies by `type`.

    Meeting/Call rows carry timings and attendees; Email rows carry addresses and drop those.
    Every field is optional so a renamed key costs that field, not the row. `extra="ignore"`
    drops permission flags and the rest of the 35-field meeting shape we do not publish.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    id: WireId = None
    type: str | None = None
    activity_type: str | None = Field(default=None, alias="activityType")
    title: str | None = None
    effective_date: LenientDate = Field(default=None, alias="effectiveDate")
    created_at: LenientDate = Field(default=None, alias="createdAt")
    modified_at: LenientDate = Field(default=None, alias="modifiedAt")
    start_date: LenientDatetime = Field(default=None, alias="startDate")
    stop_date: LenientDatetime = Field(default=None, alias="stopDate")
    time_zone: str | None = Field(default=None, alias="timeZone")
    location: str | None = None
    meeting_type: str | None = Field(default=None, alias="meetingType")
    short_description: str | None = Field(default=None, alias="shortDescription")
    formatted_description: str | None = Field(default=None, alias="formattedDescription")
    attachments_count: LenientInt = Field(default=None, alias="attachmentsCount")
    author: EntityActivityNamedAttributes | None = None
    attendees: tuple[EntityActivityNamedAttributes, ...] = ()
    activity_tags: tuple[EntityActivityTagAttributes, ...] = Field(default=(), alias="activityTags")
    associated_with: tuple[EntityActivityAssociatedWithAttributes, ...] = Field(
        default=(), alias="associatedWith"
    )
    from_address: EntityActivityAddressAttributes | None = Field(default=None, alias="fromAddress")
    to_addresses: tuple[EntityActivityAddressAttributes, ...] = Field(
        default=(), alias="toAddresses"
    )


class EntityActivitiesPageAttributes(BaseModel):
    """`data.attributes` of `POST /entity-activities`. `results` stay dicts until projected."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    total_count: LenientInt = Field(default=None, alias="totalCount")
    results: _ResultRows = ()
    should_include_description: LenientBool = Field(default=None, alias="shouldIncludeDescription")


class EntityActivitiesData(BaseModel):
    """The primary `data` object. Its `id` is a throwaway integer, often negative — ignored."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    attributes: EntityActivitiesPageAttributes


class EntityActivitiesDocument(BaseModel):
    """Whole `POST /entity-activities` body. `data` is one object, not a JSON:API list."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    data: EntityActivitiesData
