"""Wire response models for an activity-history tool payload, and the pure conversion from a
fetched item (`ActivityItemDto` / `EmailItemDto`) to its wire shape (`TimelineRecord`).

Standing caveats (documents excluded from the token budget concerns, same-day email-vs-activity
ordering, the meaning of `activity_types`) belong in the tool description, not in this payload —
see the design doc's "Token budget" section. This module carries no prose `notes` field.

Neither `resource_type` nor `resource_id` is surfaced on its own on history rows:
`activity_id` is already the composite `{resourceType}_{resourceId}` (see
`ResourceIdentifierDto`), so the two halves are always delivered together. `search_activities`
rows publish the same `activity_id` field with the search-row id, which
`get_activity_detail` also accepts. History email ids are `/emails` collection ids, not that
handle — `EmailRecordResponse` must not send them to `get_activity_detail`. `type` already
says which stream a record came from.

Field renames (`id`→`activity_id`, `effective_date`/`sent_timestamp`→`occurred_at`) use
`validation_alias` + `from_attributes`. Gist conversion, recipient capping, and the
`stream`→`type` assignment (kept explicit: discriminators reject aliases on `type`) stay in
`ActivityRecordResponse.from_item` / `EmailRecordResponse.from_item`.
"""

import logging
from collections.abc import Mapping
from datetime import date, datetime
from typing import Annotated, ClassVar, Literal, Self, override

from pydantic import AliasChoices, ConfigDict, Field, model_validator

from backstop_mcp.features.activity_history.extract_gist_from_html import extract_gist_from_html
from backstop_mcp.features.activity_history.fetch_activities_page import (
    ActivityType,
    BackstopActivityType,
)
from backstop_mcp.features.activity_history.internal_dto import (
    ActivityDetailDto,
    ActivityItemDto,
    ActivityRegardingDto,
    ActivityTagChipDto,
    AttendeeChipDto,
    AttendeeDto,
    EmailItemDto,
    EntityActivitiesFetchDto,
    EntityActivityDto,
    MeetingSpecificsDto,
)
from backstop_mcp.features.collection_scan import (
    AggregateBucketDto,
    AggregateBucketResponse,
    ScanCoverageResponse,
    project_fields,
    scan_coverage,
)
from backstop_mcp.features.data_hygiene import (
    AsOfResponse,
    ProvenanceAttributes,
)
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.party_resolver import (
    PartyAmbiguousResponse,
    ResolvedPartyDto,
    ResolvedPartyResponse,
)
from backstop_mcp.features.resolution import NotFoundResponse
from backstop_mcp.models import OmitNoneModel

logger = logging.getLogger(__name__)

__all__ = [
    "ActivityContinuationResponse",
    "ActivityGroupResponse",
    "ActivityHistoryResolvedResponse",
    "ActivityAttachmentResponse",
    "ActivityDetailResponse",
    "ActivityRegardingResponse",
    "ActivityTagChipResponse",
    "AttendeeResponse",
    "ActivityRecordResponse",
    "DateRangeResponse",
    "EmailRecordResponse",
    "GetActivityHistoryResponse",
    "GetSearchActivitiesResponse",
    "ResolvedPartyAsOfResponse",
    "SearchActivitiesResolvedResponse",
    "SearchActivitiesRowResponse",
    "SearchActivitiesUnavailableResponse",
    "TimelineRecord",
    "to_timeline_record",
]

_MAX_RECIPIENTS = 3
_FULL_BODY_MAX_CHARS = 10_000_000
_SHORT_DESCRIPTION_MAX_CHARS = 400
_DESCRIPTION_ROW_CAP_DISCLAIMER = (
    "include_description capped row bodies at 50; raising max_rows has no effect while that "
    "flag is set."
)


def _plain_text(html: str | None, *, max_chars: int) -> str | None:
    if not html:
        return None
    text = extract_gist_from_html(html, max_chars=max_chars).text
    return text or None


def _require_since_not_after_until(since: date | None, until: date | None) -> None:
    if since is not None and until is not None and since > until:
        raise ValueError("since must not be after until")


class ActivityContinuationResponse(OmitNoneModel):
    """Params to fetch this stream's next page. Echo from a prior group's `next`; do not invent."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    limit: Annotated[
        int,
        Field(gt=0, description="Page size for this stream. Copy from the prior group's `next`."),
    ]
    offset: Annotated[
        int,
        Field(
            ge=0,
            description=(
                "Next `page[offset]` for this stream. Copy from the prior group's `next`."
            ),
        ),
    ]
    since: Annotated[
        date | None,
        Field(
            default=None,
            description=(
                "Lower date bound for this stream, copied from the prior group's `next`. "
                "Omitted (or null) when this stream has no lower bound — do not invent one."
            ),
        ),
    ] = None
    until: Annotated[
        date | None,
        Field(
            default=None,
            description=(
                "Upper date bound for this stream, copied from the prior group's `next`. "
                "Omitted (or null) when this stream has no upper bound — do not invent one."
            ),
        ),
    ] = None
    activity_tag_ids: Annotated[
        tuple[str, ...] | None,
        Field(
            default=None,
            description=(
                "Tag ids this stream is filtered to, copied from the prior group's `next`. "
                "Omitted (or null) when the stream is unfiltered. Echo them; never invent."
            ),
        ),
    ] = None

    @model_validator(mode="after")
    def _since_not_after_until(self) -> Self:
        _require_since_not_after_until(self.since, self.until)
        return self


class DateRangeResponse(OmitNoneModel):
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


class ActivityGroupResponse[ItemT](OmitNoneModel):
    """One stream's page: which type, this page's items, this page's date span, and continuation."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    activity_type: Annotated[
        ActivityType,
        Field(description="Which stream this group is: meeting, call, note, email, or document."),
    ]
    items: Annotated[
        tuple[ItemT, ...],
        Field(description="This page's records for `activity_type`, in Backstop fetch order."),
    ]
    date_range: Annotated[
        DateRangeResponse | None,
        Field(
            description=(
                "Oldest and newest `occurred_at` dates among this page's dated items. Omitted "
                "(or null) when the page is empty or every item lacks a date."
            ),
        ),
    ] = None
    next: Annotated[
        ActivityContinuationResponse | None,
        Field(
            description=(
                "Params to fetch this stream's next page. Omitted (or null) once the stream is "
                "exhausted. To continue, copy this object into a `type=next` request's `next` "
                "map under this `activity_type`."
            ),
        ),
    ] = None
    error: Annotated[
        str | None,
        Field(
            description=(
                "When this stream could not be read (Backstop 403 on a linked entity the "
                "caller cannot operate). `items` is empty and `next` is omitted — that is "
                "not an empty stream. Other groups in this response were still fetched. "
                "Retry this activity type on search_activities (the primary)."
            ),
        ),
    ] = None


class ActivityRegardingResponse(OmitNoneModel):
    """The party or resource an activity is about, from Backstop's inline `regarding` value."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str = Field(description="Backstop id of the referenced record. Echo it; never invent one.")
    resource_type: str | None = Field(
        default=None,
        description="JSON:API type of the referenced record, as Backstop stored it.",
    )
    resource_link: str | None = Field(
        default=None,
        description="Backstop API URL of the referenced record, when published.",
    )
    search_type: SearchType | None = Field(
        default=None,
        description=(
            "Party collection to echo into get_person or get_organization when resource_type "
            "is organizations, people, contacts, or employees. Omitted for other resource "
            "types — do not guess a party type."
        ),
    )

    @classmethod
    def from_dto(cls, regarding: ActivityRegardingDto) -> Self:
        return cls(
            id=regarding.id,
            resource_type=regarding.resource_type,
            resource_link=regarding.resource_link,
            search_type=regarding.search_type,
        )


class ActivityTagChipResponse(OmitNoneModel):
    """One tag currently on a timeline activity."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str = Field(
        description=(
            "Backstop id of this activity tag. Echo it into activity_tag_ids; never invent one."
        )
    )
    name: str = Field(description="Tag name as Backstop publishes it.")

    @classmethod
    def from_dto(cls, tag: ActivityTagChipDto) -> Self:
        return cls(id=tag.id, name=tag.name)


class AttendeeResponse(OmitNoneModel):
    """One person listed on a meeting or call."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, from_attributes=True)

    id: str | None = Field(
        default=None,
        description=(
            "Backstop people id when side-loaded on the timeline. Pass it as party_id to "
            "get_person. Omitted on get_activity_detail, which does not receive people ids."
        ),
    )
    name: str | None = Field(default=None, description="Display name of the attendee.")

    @classmethod
    def from_chip(cls, attendee: AttendeeChipDto) -> Self:
        return cls(id=attendee.id, name=attendee.name)


class ActivityAttachmentResponse(OmitNoneModel):
    """One file attached to an activity. Only `get_activity_detail` lists these."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, from_attributes=True)

    id: str | None = Field(
        default=None,
        description="Backstop id of the file when the detail record carries one.",
    )
    name: str | None = Field(
        default=None,
        description="File name as Backstop publishes it. Omitted when the row has no name.",
    )


class ActivityRecordResponse(OmitNoneModel):
    """One meeting/call/note/document record on the timeline."""

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True, extra="ignore")

    # Plain field name required: pydantic discriminators reject AliasChoices on `type`.
    type: BackstopActivityType = Field(
        title="Type",
        description="Which stream this record is: meeting, call, note, or document.",
    )
    activity_id: str = Field(
        validation_alias=AliasChoices("activity_id", "id"),
        description=(
            "Handle for this record. Pass it to `get_activity_detail` for the full body — "
            "the same argument `search_activities` rows use. Never invent one."
        ),
    )
    resource_id: str | None = Field(
        default=None,
        description=(
            "Backstop resource id when present. Distinct from `activity_id`; used internally "
            "for related fetches."
        ),
    )
    occurred_at: date | None = Field(
        default=None,
        validation_alias=AliasChoices("occurred_at", "effective_date"),
        description="Day this activity happened. Omitted when Backstop has no date.",
    )
    title: str | None = Field(default=None, description="Title as Backstop stores it.")
    gist: str | None = Field(
        default=None,
        description=(
            "Truncated markdown of the HTML body. Call `get_activity_detail` with "
            "`activity_id` when `gist_truncated` is true, or whenever you need the full text."
        ),
    )
    gist_truncated: bool = Field(
        default=False,
        description=(
            "True when `gist` was cut to a token budget — the full body is on "
            "`get_activity_detail`."
        ),
    )
    description_length: int | None = Field(
        default=None,
        description=(
            "Character length of the full converted body, present only when "
            "`gist_truncated` is true."
        ),
    )
    regarding: ActivityRegardingResponse | None = Field(
        default=None,
        description=(
            "The party or resource this activity is about. Echo `id` and `search_type` into "
            "get_person or get_organization. Omitted when Backstop does not publish one."
        ),
    )
    tags: tuple[ActivityTagChipResponse, ...] = Field(
        default=(),
        description=(
            "Tags currently on this activity. Empty when there are none. Echo a tag's id "
            "into activity_tag_ids; never invent one. Look up names with list_activity_tags."
        ),
    )
    attendees: tuple[AttendeeResponse, ...] = Field(
        default=(),
        description=(
            "People listed on a meeting or call. Empty for a note or document, and when a "
            "meeting has no attendees."
        ),
    )

    @classmethod
    def from_item(cls, item: ActivityItemDto, *, gist_max_chars: int) -> Self:
        gist = extract_gist_from_html(item.description or "", max_chars=gist_max_chars)
        return cls(
            type=item.stream,
            activity_id=item.id,
            resource_id=item.resource_id,
            occurred_at=item.effective_date,
            title=item.title,
            gist=gist.text,
            gist_truncated=gist.truncated,
            description_length=gist.full_length if gist.truncated else None,
            regarding=(
                None
                if item.regarding is None
                else ActivityRegardingResponse.from_dto(item.regarding)
            ),
            tags=tuple(ActivityTagChipResponse.from_dto(tag) for tag in item.tags),
            attendees=tuple(AttendeeResponse.from_chip(attendee) for attendee in item.attendees),
        )


class EmailRecordResponse(OmitNoneModel):
    """One email record on the timeline. No gist: emails carry no HTML body to convert."""

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True, extra="ignore")

    type: Literal["email"] = Field(default="email", description="Always 'email'.")
    activity_id: str = Field(
        validation_alias=AliasChoices("activity_id", "id"),
        description=(
            "Handle for this email on the `/emails` collection. Emails have no body on this "
            "tool — subject and addresses only. Do not pass this to `get_activity_detail`: "
            "history email ids are not `/entity-activity-details` ids. Use `search_activities` "
            "for the body and attachment list."
        ),
    )
    occurred_at: datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("occurred_at", "sent_timestamp"),
        description="When the email was sent.",
    )
    subject: str | None = Field(default=None, description="Email subject line.")
    from_email: str | None = Field(default=None, description="Sender address.")
    to_emails: tuple[str, ...] = Field(
        default=(),
        description=(
            "Up to three To: addresses. When more were on the wire, `to_emails_count` is the total."
        ),
    )
    to_emails_count: int | None = Field(
        default=None,
        description="Total To: recipients, present only when more than three were capped.",
    )
    cc_emails: tuple[str, ...] = Field(
        default=(),
        description=(
            "Up to three Cc: addresses. When more were on the wire, `cc_emails_count` is the total."
        ),
    )
    cc_emails_count: int | None = Field(
        default=None,
        description="Total Cc: recipients, present only when more than three were capped.",
    )
    has_attachments: bool | None = Field(
        default=None,
        description="Whether Backstop marked this email as having attachments.",
    )

    @classmethod
    def from_item(cls, item: EmailItemDto) -> Self:
        to_emails, to_emails_count = _cap_recipients(item.to_emails)
        cc_emails, cc_emails_count = _cap_recipients(item.cc_emails)
        return cls(
            activity_id=item.id,
            occurred_at=item.sent_timestamp,
            subject=item.subject,
            from_email=item.from_email,
            to_emails=to_emails,
            to_emails_count=to_emails_count,
            cc_emails=cc_emails,
            cc_emails_count=cc_emails_count,
            has_attachments=item.has_attachments,
        )


type TimelineRecord = Annotated[
    ActivityRecordResponse | EmailRecordResponse, Field(discriminator="type")
]


def _cap_recipients(emails: tuple[str, ...]) -> tuple[tuple[str, ...], int | None]:
    """First three addresses, plus a count populated only when something was dropped."""
    if len(emails) <= _MAX_RECIPIENTS:
        return emails, None
    logger.debug(
        "activity_history.recipients.capped",
        extra={"total": len(emails), "kept": _MAX_RECIPIENTS},
    )
    return emails[:_MAX_RECIPIENTS], len(emails)


def to_timeline_record(
    item: ActivityItemDto | EmailItemDto, *, gist_max_chars: int
) -> TimelineRecord:
    """Convert one fetched item to its wire shape. Pure: no HTTP, no config lookups.

    Picks the union arm; construction lives on the concrete models.
    """
    if isinstance(item, EmailItemDto):
        return EmailRecordResponse.from_item(item)
    return ActivityRecordResponse.from_item(item, gist_max_chars=gist_max_chars)


class ResolvedPartyAsOfResponse(ResolvedPartyResponse):
    """Resolved party identity plus `as_of` provenance from the same record."""

    as_of: AsOfResponse | None = Field(
        default=None,
        description=(
            "When and by whom the party record was last saved. Omitted when Backstop did "
            "not provide it. Relay this; do not treat age as a staleness verdict."
        ),
    )

    @classmethod
    @override
    def from_party(
        cls,
        party: ResolvedPartyDto,
        *,
        attributes: Mapping[str, object] | ProvenanceAttributes | None = None,
    ) -> Self:
        if isinstance(attributes, ProvenanceAttributes):
            dump: Mapping[str, object] | None = attributes.model_dump(
                by_alias=True, exclude_none=True
            )
            provenance: ProvenanceAttributes | None = attributes
        elif attributes is None:
            dump = None
            provenance = None
        else:
            dump = attributes
            provenance = ProvenanceAttributes.model_validate(attributes)
        resolved = ResolvedPartyResponse.from_party(party, attributes=dump)
        return cls(
            id=resolved.id,
            search_type=resolved.search_type,
            name=resolved.name,
            as_of=AsOfResponse.from_attributes(provenance),
        )


class ActivityHistoryResolvedResponse(OmitNoneModel):
    """`get_activity_history` once the party was resolved and its timeline fetched."""

    status: Literal["resolved"] = Field(
        default="resolved",
        description="Always 'resolved': the party was found and its timeline fetched.",
    )
    resolved: ResolvedPartyAsOfResponse = Field(
        description=(
            "The party identity this call settled on, plus `as_of` provenance. Echo "
            "`id` / `search_type` / `name` as `party_id` later."
        )
    )
    groups: dict[ActivityType, ActivityGroupResponse[TimelineRecord]] = Field(
        description=(
            "One entry per requested stream (meeting, call, note, email, document), not a "
            "single merged timeline. Each group's `date_range` is that page's span."
        )
    )


type GetActivityHistoryResponse = (
    PartyAmbiguousResponse | NotFoundResponse | ActivityHistoryResolvedResponse
)


class ActivityDetailResponse(OmitNoneModel):
    """`get_activity_detail`'s payload: full body, meeting specifics, attendees, and attachments.

    `type`, `title`, `body` and `attachments` come from `entity-activity-details`; `start`/`stop`/
    `location`/`time_zone` and `attendees` come from `/meeting-or-calls/{resource_id}`, which is
    only fetched for a meeting-or-calls handle (it 404s for a note or document — see
    `fetch_activity_detail.py`). Meeting fields are therefore absent for a note or document
    because nobody asked, not because Backstop returned nothing. The attachment list is this
    tool's one unique capability versus `search_activities`, which only publishes a count.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True, from_attributes=True, extra="ignore"
    )

    activity_id: str = Field(
        description="The activity this detail is for — the same handle that was passed in."
    )
    type: str | None = Field(
        default=None,
        description=(
            "Activity kind as Backstop names it. Omitted for records that do not carry one."
        ),
    )
    title: str | None = Field(default=None, description="Title as Backstop stores it.")
    body: str = Field(
        description=(
            "Full converted markdown of the HTML description — unlike the timeline `gist`, "
            "this is not truncated for a token budget."
        )
    )
    start: datetime | None = Field(
        default=None,
        description="Meeting/call start time. Omitted for a note or document.",
    )
    stop: datetime | None = Field(
        default=None,
        description="Meeting/call end time. Omitted for a note or document.",
    )
    location: str | None = Field(
        default=None,
        description="Meeting/call location. Omitted for a note or document.",
    )
    time_zone: str | None = Field(
        default=None,
        description="Meeting/call time zone. Omitted for a note or document.",
    )
    attendees: list[AttendeeResponse] = Field(
        default_factory=list,
        description="People listed on a meeting/call. Empty for a note or document.",
    )
    attachments: tuple[ActivityAttachmentResponse, ...] = Field(
        default=(),
        description=(
            "Files attached to this activity. This is the only tool that lists them — "
            "search_activities publishes `attachments_count` only. Empty when there are none."
        ),
    )

    @classmethod
    def from_detail(
        cls,
        *,
        activity_id: str,
        detail: ActivityDetailDto,
        specifics: MeetingSpecificsDto | None,
        attendees: tuple[AttendeeDto, ...],
    ) -> Self:
        """Convert the fetched parts to the tool's wire shape. Pure: no HTTP.

        `activity_id` is echoed from the caller's composite handle rather than rebuilt from
        `detail.resource_id`, so what comes back is byte-identical to what went in — and stays
        a handle the model can pass straight back to this tool.
        """
        gist = extract_gist_from_html(detail.description or "", max_chars=_FULL_BODY_MAX_CHARS)
        return cls(
            activity_id=activity_id,
            type=detail.type,
            title=detail.title,
            body=gist.text,
            start=None if specifics is None else specifics.start,
            stop=None if specifics is None else specifics.stop,
            location=None if specifics is None else specifics.location,
            time_zone=None if specifics is None else specifics.time_zone,
            attendees=[AttendeeResponse(name=attendee.name) for attendee in attendees],
            attachments=tuple(
                ActivityAttachmentResponse(id=item.id, name=item.name)
                for item in detail.attachments
            ),
        )


class SearchActivitiesUnavailableResponse(OmitNoneModel):
    """The undocumented search endpoint did not answer. Not 'there is no activity'."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    status: Literal["unavailable"] = Field(
        default="unavailable",
        description=(
            "Always 'unavailable': POST /entity-activities failed. This is not an empty "
            "result — the primary path is undocumented and may 404 on another tenant."
        ),
    )
    fallback_tool: Literal["get_activity_history"] = Field(
        default="get_activity_history",
        description=(
            "Call get_activity_history with a resolved party instead. That path is "
            "party-scoped only — there is no documented firm-wide activity collection."
        ),
    )
    message: str = Field(
        description=(
            "Why the primary failed, and that get_activity_history is the documented "
            "fallback. A firm-wide question cannot be served on the fallback; narrow to a party."
        )
    )


class SearchActivitiesRowResponse(OmitNoneModel):
    """One activity from entity-activities.

    Fields not requested, or not present on this type, are omitted.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str = Field(
        description=(
            "Same value as `activity_id`. Pass either to get_activity_detail. Distinct from "
            "the composite `meeting-or-calls_{id}` get_activity_history returns, which also "
            "works there. History email ids do not. Never invent one."
        )
    )
    activity_id: str = Field(
        description=(
            "Pass this to get_activity_detail. Same value as `id` — the id "
            "`/entity-activity-details` uses. A get_activity_history `activity_id` "
            "(`meeting-or-calls_76537547`) also works. History email ids do not."
        )
    )
    type: str | None = Field(
        default=None,
        description=(
            "Discriminator: Meeting, Call, Email, Email Blast, Note, Document. Finer than "
            "`activity_type`, which collapses meetings and calls to `meeting`."
        ),
    )
    activity_type: str | None = Field(
        default=None,
        description="Coarse stream name as Backstop stores it, e.g. meeting, email, note.",
    )
    title: str | None = Field(default=None, description="Title as Backstop stores it.")
    effective_date: date | None = Field(
        default=None,
        description="Day the activity is dated. Normalized from Backstop's US `M/D/YYYY`.",
    )
    created_at: date | None = Field(
        default=None, description="Day the record was created. Normalized from US `M/D/YYYY`."
    )
    modified_at: date | None = Field(
        default=None, description="Day the record was last saved. Normalized from US `M/D/YYYY`."
    )
    start: datetime | None = Field(
        default=None,
        description="Meeting/call start. ISO with offset. Omitted on email, note, and document.",
    )
    stop: datetime | None = Field(
        default=None,
        description="Meeting/call end. ISO with offset. Omitted on other types.",
    )
    time_zone: str | None = Field(
        default=None, description="Meeting/call time zone. Omitted on other types."
    )
    location: str | None = Field(
        default=None, description="Meeting/call location. Omitted on other types."
    )
    meeting_type: str | None = Field(
        default=None,
        description=(
            "Labelled meeting kind, e.g. 'Face to Face', 'Phone - Inbound', "
            "'Phone - Outbound'. Better than the raw FACE_TO_FACE enum."
        ),
    )
    short_description: str | None = Field(
        default=None,
        description=(
            "Plain-text snippet from Backstop's shortDescription (HTML entities decoded). "
            "Full body is `description` when include_description was set."
        ),
    )
    description: str | None = Field(
        default=None,
        description=(
            "Plain-text body from formattedDescription. Only present when include_description "
            "was true. `attachments_count` is a count only — pass `activity_id` to "
            "`get_activity_detail` for the file list."
        ),
    )
    attachments_count: int | None = Field(
        default=None,
        description=(
            "How many files are attached. A count only — pass `activity_id` to "
            "`get_activity_detail` for the file list."
        ),
    )
    author: AttendeeResponse | None = Field(
        default=None, description="Who authored this activity, when Backstop publishes one."
    )
    attendees: tuple[str, ...] | None = Field(
        default=None,
        description="Attendee display names on a meeting or call. No people ids on this path.",
    )
    tags: tuple[ActivityTagChipResponse, ...] | None = Field(
        default=None,
        description=(
            "Tags on this activity. Empty when there are none. Echo a tag's id into "
            "activity_tag_ids; never invent one."
        ),
    )
    associated_with: tuple[ActivityRegardingResponse, ...] | None = Field(
        default=None,
        description=(
            "Parties this activity is about — a list, mixing people and organizations. "
            "Richer than REST's single `regarding`. Echo `id` and `search_type`."
        ),
    )
    from_address: str | None = Field(
        default=None, description="Email sender. Omitted on non-email types."
    )
    to_addresses: tuple[str, ...] | None = Field(
        default=None, description="Email recipients. Empty on non-email types."
    )

    @classmethod
    def from_dto(cls, row: EntityActivityDto, *, fields: frozenset[str]) -> Self:
        """Only the requested `fields`, plus `id` and `activity_id`.

        Both identifiers are the same value: `id` is what the search endpoint stores, and
        `activity_id` is the handle `get_activity_detail` takes (also from get_activity_history).
        A row the caller cannot identify is no use.

        The two description fields are the only ones whose published shape is not their stored
        shape: Backstop sends HTML and this publishes plain text, truncated. They are computed
        here only when selected, since flattening a note body is the expensive part of a row.
        """
        include = fields | {"id", "activity_id"}
        overrides: dict[str, object] = {"activity_id": row.id}
        if "short_description" in include:
            overrides["short_description"] = _plain_text(
                row.short_description, max_chars=_SHORT_DESCRIPTION_MAX_CHARS
            )
        if "description" in include:
            overrides["description"] = _plain_text(row.description, max_chars=_FULL_BODY_MAX_CHARS)
        return project_fields(row, fields=include, into=cls, overrides=overrides)


class SearchActivitiesResolvedResponse(OmitNoneModel):
    """A completed entity-activities search: row bodies or aggregate counts, plus coverage."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    status: Literal["resolved"] = Field(
        default="resolved",
        description=(
            "Always 'resolved': the search ran. An empty `rows` list is 'none in that window'."
        ),
    )
    resolved: ResolvedPartyResponse | None = Field(
        default=None,
        description=(
            "The party this search was scoped to, when a party filter was used. Omitted on a "
            "firm-wide search. Echo `id` / `search_type` / `name` as party_id later."
        ),
    )
    mode: Literal["rows", "aggregate"] = Field(
        description=(
            "`rows` returns activity bodies; `aggregate` returns counts grouped by `group_by`."
        )
    )
    coverage: ScanCoverageResponse = Field(
        description="How much of the matching set was scanned, and whether it was truncated."
    )
    rows: tuple[SearchActivitiesRowResponse, ...] = Field(
        default=(),
        description=(
            "Matching activities in Backstop's newest-effectiveDate-first order. Empty in "
            "aggregate mode."
        ),
    )
    aggregates: tuple[AggregateBucketResponse, ...] = Field(
        default=(),
        description="Count buckets in aggregate mode. Empty in rows mode.",
    )

    @classmethod
    def from_fetch(
        cls,
        fetch: EntityActivitiesFetchDto,
        *,
        mode: Literal["rows", "aggregate"],
        fields: frozenset[str],
        resolved: ResolvedPartyResponse | None,
        ceiling: int,
        aggregates: tuple[AggregateBucketDto, ...] = (),
        description_row_capped: bool = False,
    ) -> Self:
        extra = (_DESCRIPTION_ROW_CAP_DISCLAIMER,) if description_row_capped else ()
        coverage = scan_coverage(
            rows_scanned=fetch.rows_received,
            visible_count=fetch.total_count,
            rows_dropped=fetch.rows_dropped,
            ceiling=ceiling,
            ceiling_clamped=fetch.ceiling_clamped,
            truncated_by_row_cap=fetch.truncated_by_row_cap,
            partial_due_to_error=fetch.partial_due_to_error,
            extra_disclaimers=extra,
        )
        rows = ()
        if mode == "rows":
            rows = tuple(
                SearchActivitiesRowResponse.from_dto(row, fields=fields) for row in fetch.rows
            )
        return cls(
            resolved=resolved,
            mode=mode,
            coverage=coverage,
            rows=rows,
            aggregates=tuple(AggregateBucketResponse.from_dto(bucket) for bucket in aggregates),
        )


type GetSearchActivitiesResponse = (
    PartyAmbiguousResponse
    | NotFoundResponse
    | SearchActivitiesUnavailableResponse
    | SearchActivitiesResolvedResponse
)
