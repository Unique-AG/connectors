"""Per-stream single-page fetch for the four activity types plus email.

This is only the per-stream single-page fetch primitive: given a stream kind, a party, a
`limit`/`offset`, and optional `since`/`until` bounds, fetch exactly one page and report typed
items plus whether the stream is now exhausted. The k-way merge across streams, the response/wire
models for a tool payload, and config-driven page sizing all live in later modules — see the
package docstring.

**Why per-type, not one `activityType` request covering all four**: the activities list cannot
carry the meeting/call subtype back on the wire. Both meetings and calls surface as JSON:API
resources whose own `id` looks like `meeting-or-calls_76280387` (Backstop's
`{internal-type}_{numeric-id}` convention) and whose `specificResource.resourceType` is literally
the string `"meeting-or-calls"` — there is no field that distinguishes a meeting from a call in
the response. Requesting one `activityType` per stream is what lets each item be labelled
`stream="meeting"` vs `stream="call"` at all: the label is carried through from what *we asked
for*, not parsed back out of the response.

**Why pagination never reads `links.next`/`total_count`**: a date filter on `/activities` (
`filter[effectiveDate][ge|le]`) makes `links.next` disappear and degrades `totalResourceCount` to
a running count. Driving every page via explicit `page[limit]`/`page[offset]` through
`BackstopClient.fetch_page` sidesteps that regardless of whether a date filter is present, so
`ActivityPage`/`EmailPage` don't even expose those fields — there's no way for a later layer to
misuse them.

**The two date dialects**: activities take `filter[effectiveDate][ge|le]`, but `ge`+`le` together
silently return zero rows, so a both-bounds request sends `le` only and this layer truncates the
`since` side client-side (see `_truncate_since`). Emails take `filter[startDate]`/
`filter[endDate]`, which combine into a true range server-side, so no client-side truncation is
needed there — and `filter[sentTimestamp][ge]` must never be sent, since Backstop silently ignores
it (accepted, count unchanged, wrong answer, no error).
"""

from datetime import date, datetime
from typing import ClassVar, Literal

from pydantic import AliasChoices, AliasPath, BaseModel, ConfigDict, Field

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.dates import LenientDate

__all__ = [
    "ActivityItem",
    "ActivityPage",
    "ActivityStreamKind",
    "EmailItem",
    "EmailPage",
    "PartySegment",
    "StreamKind",
    "fetch_activity_page",
    "fetch_email_page",
]

# The four activity kinds this layer can request individually, plus email (a different endpoint
# entirely). `activityType`'s valid values are `[notes, meetings, calls, documents]` — the plural
# wire spellings live in `_ACTIVITY_TYPE_FILTER` below, keyed by the singular kind used everywhere
# else in this codebase's vocabulary.
ActivityStreamKind = Literal["meeting", "call", "note", "document"]
StreamKind = ActivityStreamKind | Literal["email"]

# `{segment}` in `/{segment}/{id}/activities|emails` — organizations for an organization party,
# people for a person party. Party resolution itself (mapping a resolved party to a segment) is a
# later task; this layer just takes the segment it's told.
PartySegment = Literal["organizations", "people"]

_ACTIVITY_TYPE_FILTER: dict[ActivityStreamKind, str] = {
    "meeting": "meetings",
    "call": "calls",
    "note": "notes",
    "document": "documents",
}

# Fixed field lists confirmed against the live instance — see module docstring. `description` is
# fetched despite its size (18-58KB HTML) because a later layer computes a gist from it; this
# layer carries it through raw.
_ACTIVITY_FIELDS = (
    "title,description,effectiveDate,specificResource,createdTimestamp,modifiedTimestamp"
)
_EMAIL_FIELDS = "subject,sentTimestamp,fromEmail,toEmails,ccEmails,hasAttachments,contentUrl"

_ACTIVITY_SORT = "-effectiveDate"
_EMAIL_SORT = "-sentTimestamp"


class _SpecificResource(BaseModel):
    """The `specificResource` attribute on an activity resource: `{resourceType, resourceId}`."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    resource_type: str | None = Field(
        default=None, validation_alias=AliasChoices("resourceType", "resource_type")
    )
    resource_id: str | None = Field(
        default=None, validation_alias=AliasChoices("resourceId", "resource_id")
    )


class _ActivityAttributes(BaseModel):
    """Wire shape of one `/activities` resource's `attributes`, restricted to `_ACTIVITY_FIELDS`."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    title: str | None = None
    description: str | None = None
    effective_date: LenientDate = Field(
        default=None, validation_alias=AliasChoices("effectiveDate", "effective_date")
    )
    specific_resource: _SpecificResource | None = Field(
        default=None, validation_alias=AliasChoices("specificResource", "specific_resource")
    )
    created_timestamp: datetime | None = Field(
        default=None, validation_alias=AliasChoices("createdTimestamp", "created_timestamp")
    )
    modified_timestamp: datetime | None = Field(
        default=None, validation_alias=AliasChoices("modifiedTimestamp", "modified_timestamp")
    )


class _EmailAttributes(BaseModel):
    """Wire shape of one `/emails` resource's `attributes`, restricted to `_EMAIL_FIELDS`.

    `sent_timestamp` is a real timestamp (not date-only); pydantic's built-in `datetime`
    coercion already parses Backstop's `2026-06-25T00:00:00.000-0400` spelling (offset without a
    colon), so no bespoke lenient-datetime parser is needed here the way `LenientDate` is for
    `effectiveDate`.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    subject: str | None = None
    sent_timestamp: datetime | None = Field(
        default=None, validation_alias=AliasChoices("sentTimestamp", "sent_timestamp")
    )
    from_email: str | None = Field(
        default=None, validation_alias=AliasChoices("fromEmail", "from_email")
    )
    to_emails: list[str] = Field(
        default_factory=list, validation_alias=AliasChoices("toEmails", "to_emails")
    )
    cc_emails: list[str] = Field(
        default_factory=list, validation_alias=AliasChoices("ccEmails", "cc_emails")
    )
    has_attachments: bool | None = Field(
        default=None, validation_alias=AliasChoices("hasAttachments", "has_attachments")
    )
    content_url: str | None = Field(
        default=None, validation_alias=AliasChoices("contentUrl", "content_url")
    )


# `fetch_page(schema=...)` wants the type of one element of the JSON:API `data` array — a whole
# resource (id/type/attributes), not just the attributes model. See `BackstopApiResource` in
# `backstop_client.json_api`.
_ActivityResource = BackstopApiResource[_ActivityAttributes]
_EmailResource = BackstopApiResource[_EmailAttributes]


class ActivityItem(BaseModel):
    """One parsed activity — meeting, call, note, or document, per `stream`.

    `id` is Backstop's own resource id, prefixed for meetings/calls (`meeting-or-calls_...`) and
    unprefixed-looking-but-still-wire-native for notes/documents. `stream` is never parsed from
    the response — meetings and calls are indistinguishable on the wire (see module docstring) —
    it is the stream kind the caller requested this item under. `description` is the raw HTML
    body, untouched; gisting it is a later layer's job (`activity_history.gist`).
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    stream: ActivityStreamKind
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


class EmailItem(BaseModel):
    """One parsed email from `/{segment}/{id}/emails`."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    subject: str | None
    sent_timestamp: datetime | None
    from_email: str | None
    to_emails: tuple[str, ...]
    cc_emails: tuple[str, ...]
    has_attachments: bool | None
    content_url: str | None


class ActivityPage(BaseModel):
    """One fetched page of one activity stream.

    `end_of_stream` is true when Backstop's raw page came back shorter than the requested
    `limit` (no more data), or — only in the both-bounds case — when the `since` cutoff was hit
    within this page. Deliberately carries no `total_count`/`next_path`: see module docstring.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    items: tuple[ActivityItem, ...]
    end_of_stream: bool


class EmailPage(BaseModel):
    """One fetched page of the email stream. See `ActivityPage` for the `end_of_stream` rule —
    emails never need client-side since-truncation, so it is always the short-page check alone.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    items: tuple[EmailItem, ...]
    end_of_stream: bool


def _activity_from_resource(
    resource: BackstopApiResource[_ActivityAttributes], *, stream: ActivityStreamKind
) -> ActivityItem:
    return ActivityItem.model_validate(
        {**resource.attributes.model_dump(), "id": resource.id, "stream": stream}
    )


def _email_from_resource(resource: BackstopApiResource[_EmailAttributes]) -> EmailItem:
    return EmailItem.model_validate({**resource.attributes.model_dump(), "id": resource.id})


def _activity_date_filter_params(*, since: date | None, until: date | None) -> dict[str, object]:
    """`filter[effectiveDate][...]` per the two-bound rule.

    `ge`+`le` together silently 0-row this endpoint, so a both-bounds request sends `le` only;
    `_truncate_since` applies the `since` cutoff client-side against the fetched page instead.
    """
    if until is not None:
        return {"filter[effectiveDate][le]": until.isoformat()}
    if since is not None:
        return {"filter[effectiveDate][ge]": since.isoformat()}
    return {}


def _email_date_filter_params(*, since: date | None, until: date | None) -> dict[str, object]:
    """`filter[startDate]`/`filter[endDate]` — true window bounds, sent independently.

    Never send `filter[sentTimestamp]`: its `[ge]` operator is silently ignored by Backstop
    (accepted, count unchanged, wrong answer, no error).
    """
    params: dict[str, object] = {}
    if since is not None:
        params["filter[startDate]"] = since.isoformat()
    if until is not None:
        params["filter[endDate]"] = until.isoformat()
    return params


def _truncate_since(
    items: tuple[ActivityItem, ...], *, since: date
) -> tuple[tuple[ActivityItem, ...], bool]:
    """Drop the first item older than `since` and everything after it; report whether that fired.

    The stream is sorted `-effectiveDate` (descending), so once one fetched item's
    `effective_date` is older than `since`, every later item on this page — and every later page
    — is too. An item with no parseable `effective_date` can't be compared, so it's kept as-is and
    scanning continues past it rather than being treated as the cutoff.
    """
    for index, item in enumerate(items):
        if item.effective_date is not None and item.effective_date < since:
            return items[:index], True
    return items, False


async def fetch_activity_page(
    client: BackstopClient,
    *,
    segment: PartySegment,
    party_id: str,
    stream: ActivityStreamKind,
    limit: int,
    offset: int,
    since: date | None = None,
    until: date | None = None,
) -> ActivityPage:
    """Fetch exactly one page of one activity stream kind (meeting/call/note/document).

    Requests a single `filter[activityType][eq]` value — never a comma-joined multi-value — so
    every returned item can be labelled `stream=<stream>` without parsing anything back out of
    the response (see module docstring). `limit`/`offset` go straight through to
    `BackstopClient.fetch_page`; alignment (`offset` a multiple of `limit`) is the caller's
    responsibility, not re-derived or validated here.

    Activities are frequently future-dated (scheduled meetings) and are never filtered out for
    that reason — "newest first" legitimately includes future items.
    """
    params: dict[str, object] = {
        "fields": _ACTIVITY_FIELDS,
        "sort": _ACTIVITY_SORT,
        "filter[activityType][eq]": _ACTIVITY_TYPE_FILTER[stream],
        **_activity_date_filter_params(since=since, until=until),
    }
    page = await client.fetch_page(
        f"/{segment}/{party_id}/activities",
        schema=_ActivityResource,
        params=params,
        page_size=limit,
        offset=offset,
    )
    raw_count = len(page.items)
    items = tuple(_activity_from_resource(resource, stream=stream) for resource in page.items)

    if since is not None and until is not None:
        items, cutoff_hit = _truncate_since(items, since=since)
        return ActivityPage(items=items, end_of_stream=cutoff_hit or raw_count < limit)
    return ActivityPage(items=items, end_of_stream=raw_count < limit)


async def fetch_email_page(
    client: BackstopClient,
    *,
    segment: PartySegment,
    party_id: str,
    limit: int,
    offset: int,
    since: date | None = None,
    until: date | None = None,
) -> EmailPage:
    """Fetch exactly one page of the email stream.

    `since`/`until` map to `filter[startDate]`/`filter[endDate]` independently — unlike
    activities, both bounds combine into a true range server-side, so no client-side truncation
    is needed. `limit`/`offset` go straight through to `BackstopClient.fetch_page`, same as
    `fetch_activity_page`.
    """
    params: dict[str, object] = {
        "fields": _EMAIL_FIELDS,
        "sort": _EMAIL_SORT,
        **_email_date_filter_params(since=since, until=until),
    }
    page = await client.fetch_page(
        f"/{segment}/{party_id}/emails",
        schema=_EmailResource,
        params=params,
        page_size=limit,
        offset=offset,
    )
    items = tuple(_email_from_resource(resource) for resource in page.items)
    return EmailPage(items=items, end_of_stream=len(page.items) < limit)
