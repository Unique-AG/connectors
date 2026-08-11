"""Per-stream single-page fetch for meetings/calls/notes/documents and email.

Given a stream, entity, `limit`/`offset`, and optional date bounds, fetch one page and report
typed items plus whether the stream is exhausted.

Backstop quirks this layer absorbs:
- Meetings and calls are indistinguishable on the wire (`meeting-or-calls`); request one
  `activityType` at a time and label items from what we asked for.
- Date filters on `/activities` break `links.next` / `totalResourceCount` — always page via
  explicit `page[limit]`/`page[offset]`.
- `filter[effectiveDate][ge]`+`[le]` together return zero rows; both-bounds sends `le` only and
  truncates `since` client-side. Emails use `filter[startDate]`/`filter[endDate]` as a real range.
- Never send `filter[sentTimestamp][ge]` — Backstop accepts it and silently ignores it.
"""

from datetime import date, datetime
from typing import ClassVar, Literal

from pydantic import AliasChoices, AliasPath, BaseModel, ConfigDict, Field

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.dates import LenientDate

__all__ = [
    "ActivityItem",
    "ActivityPage",
    "ActivityType",
    "BackstopActivityType",
    "EmailItem",
    "EmailPage",
    "Segment",
    "fetch_activity_page",
    "fetch_email_page",
]

BackstopActivityType = Literal["meeting", "call", "note", "document"]
ActivityType = BackstopActivityType | Literal["email"]
Segment = Literal["organizations", "people"]

_ACTIVITY_TYPE_FILTER: dict[BackstopActivityType, str] = {
    "meeting": "meetings",
    "call": "calls",
    "note": "notes",
    "document": "documents",
}
_ACTIVITY_FIELDS = (
    "title,description,effectiveDate,specificResource,createdTimestamp,modifiedTimestamp"
)
_EMAIL_FIELDS = "subject,sentTimestamp,fromEmail,toEmails,ccEmails,hasAttachments,contentUrl"


class _SpecificResource(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    resource_type: str | None = Field(
        default=None, validation_alias=AliasChoices("resourceType", "resource_type")
    )
    resource_id: str | None = Field(
        default=None, validation_alias=AliasChoices("resourceId", "resource_id")
    )


class _ActivityAttributes(BaseModel):
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


_ActivityResource = BackstopApiResource[_ActivityAttributes]
_EmailResource = BackstopApiResource[_EmailAttributes]


class ActivityItem(BaseModel):
    """One activity; `stream` is the requested type (not parsed from the wire)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

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


class EmailItem(BaseModel):
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
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    items: tuple[ActivityItem, ...]
    end_of_stream: bool


class EmailPage(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    items: tuple[EmailItem, ...]
    end_of_stream: bool


def _activity_date_filter_params(*, since: date | None, until: date | None) -> dict[str, object]:
    # ge+le together silently 0-row; both-bounds sends le only (since truncated client-side).
    if until is not None:
        return {"filter[effectiveDate][le]": until.isoformat()}
    if since is not None:
        return {"filter[effectiveDate][ge]": since.isoformat()}
    return {}


def _email_date_filter_params(*, since: date | None, until: date | None) -> dict[str, object]:
    params: dict[str, object] = {}
    if since is not None:
        params["filter[startDate]"] = since.isoformat()
    if until is not None:
        params["filter[endDate]"] = until.isoformat()
    return params


def _truncate_since(
    items: tuple[ActivityItem, ...], *, since: date
) -> tuple[tuple[ActivityItem, ...], bool]:
    """Drop the first item older than `since` and everything after (stream is `-effectiveDate`)."""
    for index, item in enumerate(items):
        if item.effective_date is not None and item.effective_date < since:
            return items[:index], True
    return items, False


async def fetch_activity_page(
    client: BackstopClient,
    *,
    segment: Segment,
    entity_id: str,
    stream: BackstopActivityType,
    limit: int,
    offset: int,
    since: date | None = None,
    until: date | None = None,
) -> ActivityPage:
    """Fetch one page of one activity type. Future-dated items are kept."""
    page = await client.fetch_page(
        f"/{segment}/{entity_id}/activities",
        schema=_ActivityResource,
        params={
            "fields": _ACTIVITY_FIELDS,
            "sort": "-effectiveDate",
            "filter[activityType][eq]": _ACTIVITY_TYPE_FILTER[stream],
            **_activity_date_filter_params(since=since, until=until),
        },
        page_size=limit,
        offset=offset,
    )
    raw_count = len(page.items)
    items = tuple(
        ActivityItem.model_validate(
            {**resource.attributes.model_dump(), "id": resource.id, "stream": stream}
        )
        for resource in page.items
    )
    if since is not None and until is not None:
        items, cutoff_hit = _truncate_since(items, since=since)
        return ActivityPage(items=items, end_of_stream=cutoff_hit or raw_count < limit)
    return ActivityPage(items=items, end_of_stream=raw_count < limit)


async def fetch_email_page(
    client: BackstopClient,
    *,
    segment: Segment,
    entity_id: str,
    limit: int,
    offset: int,
    since: date | None = None,
    until: date | None = None,
) -> EmailPage:
    """Fetch one page of emails. `since`/`until` map to startDate/endDate independently."""
    page = await client.fetch_page(
        f"/{segment}/{entity_id}/emails",
        schema=_EmailResource,
        params={
            "fields": _EMAIL_FIELDS,
            "sort": "-sentTimestamp",
            **_email_date_filter_params(since=since, until=until),
        },
        page_size=limit,
        offset=offset,
    )
    items = tuple(
        EmailItem.model_validate({**resource.attributes.model_dump(), "id": resource.id})
        for resource in page.items
    )
    return EmailPage(items=items, end_of_stream=len(page.items) < limit)
