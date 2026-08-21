"""Wire response models for an activity-history tool payload, and the pure conversion from a
fetched item (`ActivityItemDto` / `EmailItemDto`) to its wire shape (`TimelineRecord`).

Standing caveats (documents excluded from the token budget concerns, same-day email-vs-activity
ordering, the meaning of `activity_types`) belong in the tool description, not in this payload —
see the design doc's "Token budget" section. This module carries no prose `notes` field.

Neither `resource_type` nor `resource_id` is surfaced on its own: `activity_id` is already the
composite `{resourceType}_{resourceId}` (see `ResourceIdentifierDto`), so the two halves are always
delivered together. A bare `resource_id` would be an id with no collection to look it up in —
unusable on its own, and easy to mistake for something `get_activity_detail` accepts. `type`
already says which stream a record came from.

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

from backstop_mcp.features.activity_history.fetch_activities import (
    ActivityType,
    BackstopActivityType,
)
from backstop_mcp.features.activity_history.gist_from_html import to_gist
from backstop_mcp.features.activity_history.internal_dto import (
    ActivityDetailDto,
    ActivityItemDto,
    AttendeeDto,
    EmailItemDto,
    MeetingSpecificsDto,
)
from backstop_mcp.features.data_hygiene import (
    AsOfResponse,
    ProvenanceAttributes,
)
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
    "ActivityDetailResponse",
    "AttendeeResponse",
    "ActivityRecordResponse",
    "DateRangeResponse",
    "EmailRecordResponse",
    "GetActivityHistoryResponse",
    "ResolvedPartyAsOfResponse",
    "TimelineRecord",
    "to_timeline_record",
]

_MAX_RECIPIENTS = 3
_FULL_BODY_MAX_CHARS = 10_000_000


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
            "never invent one."
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

    @classmethod
    def from_item(cls, item: ActivityItemDto, *, gist_max_chars: int) -> Self:
        gist = to_gist(item.description or "", max_chars=gist_max_chars)
        return cls(
            type=item.stream,
            activity_id=item.id,
            resource_id=item.resource_id,
            occurred_at=item.effective_date,
            title=item.title,
            gist=gist.text,
            gist_truncated=gist.truncated,
            description_length=gist.full_length if gist.truncated else None,
        )


class EmailRecordResponse(OmitNoneModel):
    """One email record on the timeline. No gist: emails carry no HTML body to convert."""

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True, extra="ignore")

    type: Literal["email"] = Field(default="email", description="Always 'email'.")
    activity_id: str = Field(
        validation_alias=AliasChoices("activity_id", "id"),
        description=(
            "Handle for this email on the timeline. Emails have no body on this tool — "
            "subject and addresses only."
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


class AttendeeResponse(OmitNoneModel):
    """One trimmed attendee: a single display name (see `AttendeeAttributes.display_name`)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, from_attributes=True)

    name: str | None = Field(default=None, description="Display name of the attendee.")


class ActivityDetailResponse(OmitNoneModel):
    """`get_activity_detail`'s payload: full body plus meeting specifics and attendees.

    `type`, `title` and `body` come from `entity-activity-details`; `start`/`stop`/`location`/
    `time_zone` and `attendees` come from `/meeting-or-calls/{resource_id}`, which is only
    fetched for a meeting-or-calls handle (it 404s for a note or document — see
    `fetch_activity_detail.py`). They are therefore absent for a note or document because nobody
    asked, not because Backstop returned nothing.
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
        gist = to_gist(detail.description or "", max_chars=_FULL_BODY_MAX_CHARS)
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
        )
