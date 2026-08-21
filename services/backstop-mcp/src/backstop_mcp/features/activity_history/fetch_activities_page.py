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
- Emails have no `activityTags` / `attendees` includes and no `filter[activityTagIds]`.
"""

import logging
from collections.abc import Sequence
from datetime import date
from typing import Literal
from urllib.parse import quote

from backstop_mcp.backstop_client import (
    BackstopApiResource,
    BackstopApiResourceDocument,
    BackstopClient,
)
from backstop_mcp.features.activity_history.api_responses import (
    ActivityAttributes,
    EmailAttributes,
)
from backstop_mcp.features.activity_history.internal_dto import (
    ActivityItemDto,
    ActivityPageDto,
    ActivityTagChipDto,
    AttendeeChipDto,
    BackstopActivityType,
    EmailItemDto,
    EmailPageDto,
)
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.includes import (
    ActivityAttendeeResponse,
    ActivityIncludesResponse,
    ActivityTagChipResponse,
    include_plan,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ActivityItemDto",
    "ActivityPageDto",
    "ActivityType",
    "BackstopActivityType",
    "EmailItemDto",
    "EmailPageDto",
    "Segment",
    "fetch_activity_page",
    "fetch_activities_page",
    "fetch_email_page",
]

ActivityType = BackstopActivityType | Literal["email"]
# Same vocabulary as party resolve: person-scoped quick-search can return contacts/employees.
Segment = SearchType

_ACTIVITY_TYPE_FILTER: dict[BackstopActivityType, str] = {
    "meeting": "meetings",
    "call": "calls",
    "note": "notes",
    "document": "documents",
}
_ACTIVITY_FIELDS = (
    "title,description,effectiveDate,specificResource,createdTimestamp,modifiedTimestamp,regarding"
)
_ACTIVITY_TAG_FIELDS = "name"
_ATTENDEE_FIELDS = "name,firstName,lastName"
_EMAIL_FIELDS = "subject,sentTimestamp,fromEmail,toEmails,ccEmails,hasAttachments,contentUrl"
_ACTIVITY_SIDE_LOADS = include_plan(
    ActivityIncludesResponse, requested=("activity_tags", "attendees")
)

_ActivityResource = BackstopApiResource[ActivityAttributes]
_EmailResource = BackstopApiResource[EmailAttributes]


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


def _tag_filter_params(activity_tag_ids: Sequence[str]) -> dict[str, object]:
    if not activity_tag_ids:
        return {}
    return {"filter[activityTagIds]": ",".join(activity_tag_ids)}


def _truncate_since(
    items: tuple[ActivityItemDto, ...], *, since: date
) -> tuple[tuple[ActivityItemDto, ...], bool]:
    """Drop the first item older than `since` and everything after (stream is `-effectiveDate`).

    Items with a missing `effective_date` never trip the cutoff — left intentional until we
    confirm null-date ordering against the live Backstop API.
    """
    for index, item in enumerate(items):
        if item.effective_date is None:
            logger.debug(
                "activity_history.since_truncate.null_date",
                extra={"activity_id": item.id, "stream": item.stream, "since": since.isoformat()},
            )
            continue
        if item.effective_date < since:
            logger.info(
                "activity_history.since_truncate.cutoff",
                extra={
                    "activity_id": item.id,
                    "stream": item.stream,
                    "effective_date": item.effective_date.isoformat(),
                    "since": since.isoformat(),
                    "kept": index,
                    "dropped": len(items) - index,
                },
            )
            return items[:index], True
    return items, False


def _tag_chips(tags: list[ActivityTagChipResponse] | None) -> tuple[ActivityTagChipDto, ...]:
    chips: list[ActivityTagChipDto] = []
    for tag in tags or ():
        tag_id = tag.id
        name = tag.name
        if not tag_id or not name:
            continue
        chips.append(ActivityTagChipDto(id=tag_id, name=name))
    return tuple(chips)


def _attendee_chips(
    attendees: list[ActivityAttendeeResponse] | None,
) -> tuple[AttendeeChipDto, ...]:
    return tuple(
        AttendeeChipDto(id=attendee.id, name=attendee.name) for attendee in attendees or ()
    )


def _item_from_resource(
    resource: BackstopApiResource[ActivityAttributes],
    *,
    stream: BackstopActivityType,
    included: list[dict[str, object]],
) -> ActivityItemDto:
    projected = _ACTIVITY_SIDE_LOADS.project(
        document=BackstopApiResourceDocument[ActivityAttributes].model_construct(
            data=resource,
            included=included,
        )
    )
    return ActivityItemDto.from_attributes(
        resource.id,
        stream,
        resource.attributes,
        tags=_tag_chips(projected.activity_tags),
        attendees=_attendee_chips(projected.attendees),
    )


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
    activity_tag_ids: Sequence[str] = (),
) -> ActivityPageDto:
    """Fetch one page of one activity type. Future-dated items are kept."""
    logger.debug(
        "activity_history.activity_page.fetch",
        extra={
            "segment": segment,
            "entity_id": entity_id,
            "stream": stream,
            "limit": limit,
            "offset": offset,
            "since": since.isoformat() if since is not None else None,
            "until": until.isoformat() if until is not None else None,
            "activity_tag_ids": list(activity_tag_ids),
        },
    )
    page = await client.fetch_page(
        f"/{segment}/{quote(entity_id, safe='')}/activities",
        schema=_ActivityResource,
        params={
            "fields": _ACTIVITY_FIELDS,
            "fields[activity-tags]": _ACTIVITY_TAG_FIELDS,
            "fields[people]": _ATTENDEE_FIELDS,
            "include": _ACTIVITY_SIDE_LOADS.param,
            "sort": "-effectiveDate",
            "filter[activityType][eq]": _ACTIVITY_TYPE_FILTER[stream],
            **_activity_date_filter_params(since=since, until=until),
            **_tag_filter_params(activity_tag_ids),
        },
        page_size=limit,
        offset=offset,
    )
    raw_count = len(page.items)
    items = tuple(
        _item_from_resource(resource, stream=stream, included=page.included)
        for resource in page.items
    )
    if since is not None and until is not None:
        items, cutoff_hit = _truncate_since(items, since=since)
        end_of_stream = cutoff_hit or raw_count < limit
    else:
        end_of_stream = raw_count < limit
    logger.info(
        "activity_history.activity_page.fetched",
        extra={
            "segment": segment,
            "entity_id": entity_id,
            "stream": stream,
            "raw_count": raw_count,
            "kept": len(items),
            "end_of_stream": end_of_stream,
            "offset": offset,
        },
    )
    return ActivityPageDto(items=items, end_of_stream=end_of_stream)


async def fetch_email_page(
    client: BackstopClient,
    *,
    segment: Segment,
    entity_id: str,
    limit: int,
    offset: int,
    since: date | None = None,
    until: date | None = None,
) -> EmailPageDto:
    """Fetch one page of emails. `since`/`until` map to startDate/endDate independently."""
    logger.debug(
        "activity_history.email_page.fetch",
        extra={
            "segment": segment,
            "entity_id": entity_id,
            "limit": limit,
            "offset": offset,
            "since": since.isoformat() if since is not None else None,
            "until": until.isoformat() if until is not None else None,
        },
    )
    page = await client.fetch_page(
        f"/{segment}/{quote(entity_id, safe='')}/emails",
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
        EmailItemDto.from_attributes(resource.id, resource.attributes) for resource in page.items
    )
    end_of_stream = len(page.items) < limit
    logger.info(
        "activity_history.email_page.fetched",
        extra={
            "segment": segment,
            "entity_id": entity_id,
            "count": len(items),
            "end_of_stream": end_of_stream,
            "offset": offset,
        },
    )
    return EmailPageDto(items=items, end_of_stream=end_of_stream)


async def fetch_activities_page(
    client: BackstopClient,
    *,
    activity_type: ActivityType,
    segment: Segment,
    entity_id: str,
    limit: int,
    offset: int,
    since: date | None = None,
    until: date | None = None,
    activity_tag_ids: Sequence[str] = (),
) -> ActivityPageDto | EmailPageDto:
    """Dispatch to the activity or email single-page fetcher for `activity_type`."""
    if activity_type == "email":
        return await fetch_email_page(
            client,
            segment=segment,
            entity_id=entity_id,
            limit=limit,
            offset=offset,
            since=since,
            until=until,
        )
    return await fetch_activity_page(
        client,
        segment=segment,
        entity_id=entity_id,
        stream=activity_type,
        limit=limit,
        offset=offset,
        since=since,
        until=until,
        activity_tag_ids=activity_tag_ids,
    )
