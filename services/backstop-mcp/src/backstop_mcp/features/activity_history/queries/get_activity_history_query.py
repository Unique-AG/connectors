"""One party's per-stream activity pages: fetch, group, and the published history payload.

Given a stream, entity, `limit`/`offset`, and optional date bounds, fetch one page and report
typed items plus whether the stream is exhausted. Active streams go through one
`asyncio.gather`. A 5xx or transport failure still fails the whole call. A 403 on one stream
(Backstop refusing a linked entity) is reported on that group and the other streams are kept.

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

import asyncio
import logging
from collections.abc import Coroutine, Mapping, Sequence
from datetime import UTC, date, datetime
from urllib.parse import quote

from backstop_mcp.backstop_client import (
    BackstopApiError,
    BackstopApiResource,
    BackstopApiResourceDocument,
    BackstopClient,
)
from backstop_mcp.features.activity_history.activity_type import (
    ActivityType,
    BackstopActivityType,
    Segment,
)
from backstop_mcp.features.activity_history.api_responses import (
    ActivityAttributes,
    EmailAttributes,
)
from backstop_mcp.features.activity_history.responses import (
    ActivityContinuationResponse,
    ActivityGroupResponse,
    ActivityHistoryResolvedResponse,
    ActivityRecordResponse,
    ActivityTagChipResponse,
    AttendeeResponse,
    DateRangeResponse,
    EmailRecordResponse,
    PartyRecordResponse,
    ResolvedPartyAsOfResponse,
    TimelineRecord,
)
from backstop_mcp.features.includes import (
    ActivityAttendeeResponse,
    ActivityIncludesResponse,
    include_plan,
)
from backstop_mcp.features.includes import (
    ActivityTagChipResponse as ActivityTagInclude,
)
from backstop_mcp.features.party_resolver import ResolvedPartyDto

logger = logging.getLogger(__name__)

_ACTIVITY_TYPE_FILTER: dict[BackstopActivityType, str] = {
    "meeting": "meetings",
    "call": "calls",
    "note": "notes",
    "document": "documents",
}
_ACTIVITY_SIDE_LOADS = include_plan(ActivityIncludesResponse, requested=("activity_tags",))

_ActivityResource = BackstopApiResource[ActivityAttributes]
_EmailResource = BackstopApiResource[EmailAttributes]
_FetchedPage = tuple[tuple[TimelineRecord, ...], bool]


class GetActivityHistoryQuery:
    """Party record plus one page per requested stream, grouped for the published payload."""

    def __init__(self, *, client: BackstopClient) -> None:
        self._client: BackstopClient = client

    async def run(
        self,
        *,
        segment: Segment,
        entity_id: str,
        party: ResolvedPartyDto,
        continuations: Mapping[ActivityType, ActivityContinuationResponse],
        gist_max_chars: int,
    ) -> ActivityHistoryResolvedResponse:
        party_path = f"/{segment}/{quote(entity_id, safe='')}"
        document = await self._client.get(
            party_path,
            schema=BackstopApiResourceDocument[PartyRecordResponse],
        )
        page_calls: dict[ActivityType, Coroutine[None, None, _FetchedPage]] = {
            activity_type: self._fetch_page(
                activity_type=activity_type,
                segment=segment,
                entity_id=entity_id,
                limit=continuation.limit,
                offset=continuation.offset,
                since=continuation.since,
                until=continuation.until,
                activity_tag_ids=continuation.activity_tag_ids or (),
                gist_max_chars=gist_max_chars,
            )
            for activity_type, continuation in continuations.items()
        }
        settled = await asyncio.gather(*page_calls.values(), return_exceptions=True)

        groups: dict[ActivityType, ActivityGroupResponse[TimelineRecord]] = {}
        for (activity_type, continuation), result in zip(
            continuations.items(), settled, strict=True
        ):
            if isinstance(result, BackstopApiError) and result.status_code == 403:
                logger.warning(
                    "activity_history.stream.forbidden",
                    extra={
                        "segment": segment,
                        "entity_id": entity_id,
                        "stream": activity_type,
                        "detail": result.detail,
                    },
                )
                groups[activity_type] = ActivityGroupResponse(
                    activity_type=activity_type,
                    items=(),
                    error=result.detail,
                )
                continue
            if isinstance(result, BaseException):
                raise result
            items, end_of_stream = result
            groups[activity_type] = self._group_page(
                items,
                activity_type=activity_type,
                end_of_stream=end_of_stream,
                limit=continuation.limit,
                offset=continuation.offset,
                since=continuation.since,
                until=continuation.until,
                activity_tag_ids=continuation.activity_tag_ids,
            )

        attributes = document.require_data(path=party_path).attributes
        return ActivityHistoryResolvedResponse(
            resolved=ResolvedPartyAsOfResponse.from_party(party, attributes=attributes),
            groups=groups,
        )

    async def _fetch_page(
        self,
        *,
        activity_type: ActivityType,
        segment: Segment,
        entity_id: str,
        limit: int,
        offset: int,
        since: date | None,
        until: date | None,
        activity_tag_ids: Sequence[str],
        gist_max_chars: int,
    ) -> tuple[tuple[TimelineRecord, ...], bool]:
        if activity_type == "email":
            return await self._email_page(
                segment=segment,
                entity_id=entity_id,
                limit=limit,
                offset=offset,
                since=since,
                until=until,
            )
        return await self._activity_page(
            segment=segment,
            entity_id=entity_id,
            stream=activity_type,
            limit=limit,
            offset=offset,
            since=since,
            until=until,
            activity_tag_ids=activity_tag_ids,
            gist_max_chars=gist_max_chars,
        )

    async def _activity_page(
        self,
        *,
        segment: Segment,
        entity_id: str,
        stream: BackstopActivityType,
        limit: int,
        offset: int,
        since: date | None,
        until: date | None,
        activity_tag_ids: Sequence[str],
        gist_max_chars: int,
    ) -> tuple[tuple[ActivityRecordResponse, ...], bool]:
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
        page = await self._client.fetch_page(
            f"/{segment}/{quote(entity_id, safe='')}/activities",
            schema=_ActivityResource,
            params={
                "fields": (
                    "title,description,effectiveDate,specificResource,"
                    "createdTimestamp,modifiedTimestamp"
                ),
                "fields[activity-tags]": "name",
                "include": _ACTIVITY_SIDE_LOADS.param,
                "sort": "-effectiveDate",
                "filter[activityType][eq]": _ACTIVITY_TYPE_FILTER[stream],
                **self._activity_date_filter(since=since, until=until),
                **self._tag_filter(activity_tag_ids),
            },
            page_size=limit,
            offset=offset,
        )
        raw_count = len(page.items)
        items = tuple(
            self._record_from_resource(
                resource,
                stream=stream,
                included=page.included,
                gist_max_chars=gist_max_chars,
            )
            for resource in page.items
        )
        if since is not None and until is not None:
            items, cutoff_hit = self._truncate_since(items, since=since)
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
        return items, end_of_stream

    async def _email_page(
        self,
        *,
        segment: Segment,
        entity_id: str,
        limit: int,
        offset: int,
        since: date | None,
        until: date | None,
    ) -> tuple[tuple[EmailRecordResponse, ...], bool]:
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
        page = await self._client.fetch_page(
            f"/{segment}/{quote(entity_id, safe='')}/emails",
            schema=_EmailResource,
            params={
                "fields": (
                    "subject,sentTimestamp,fromEmail,toEmails,ccEmails,hasAttachments,contentUrl"
                ),
                "sort": "-sentTimestamp",
                **self._email_date_filter(since=since, until=until),
            },
            page_size=limit,
            offset=offset,
        )
        items = tuple(
            EmailRecordResponse.from_attributes(resource.id, resource.attributes)
            for resource in page.items
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
        return items, end_of_stream

    def _activity_date_filter(self, *, since: date | None, until: date | None) -> dict[str, object]:
        # ge+le together silently 0-row; both-bounds sends le only (since truncated client-side).
        if until is not None:
            return {"filter[effectiveDate][le]": until.isoformat()}
        if since is not None:
            return {"filter[effectiveDate][ge]": since.isoformat()}
        return {}

    def _email_date_filter(self, *, since: date | None, until: date | None) -> dict[str, object]:
        params: dict[str, object] = {}
        if since is not None:
            params["filter[startDate]"] = since.isoformat()
        if until is not None:
            params["filter[endDate]"] = until.isoformat()
        return params

    def _tag_filter(self, activity_tag_ids: Sequence[str]) -> dict[str, object]:
        if not activity_tag_ids:
            return {}
        return {"filter[activityTagIds]": ",".join(activity_tag_ids)}

    def _truncate_since(
        self, items: tuple[ActivityRecordResponse, ...], *, since: date
    ) -> tuple[tuple[ActivityRecordResponse, ...], bool]:
        """Drop the first item older than `since` and everything after (stream is `-effectiveDate`).

        Items with a missing `occurred_at` never trip the cutoff — left intentional until we
        confirm null-date ordering against the live Backstop API.
        """
        for index, item in enumerate(items):
            if item.occurred_at is None:
                logger.debug(
                    "activity_history.since_truncate.null_date",
                    extra={
                        "activity_id": item.activity_id,
                        "stream": item.type,
                        "since": since.isoformat(),
                    },
                )
                continue
            if item.occurred_at < since:
                logger.info(
                    "activity_history.since_truncate.cutoff",
                    extra={
                        "activity_id": item.activity_id,
                        "stream": item.type,
                        "effective_date": item.occurred_at.isoformat(),
                        "since": since.isoformat(),
                        "kept": index,
                        "dropped": len(items) - index,
                    },
                )
                return items[:index], True
        return items, False

    def _record_from_resource(
        self,
        resource: BackstopApiResource[ActivityAttributes],
        *,
        stream: BackstopActivityType,
        included: list[dict[str, object]],
        gist_max_chars: int,
    ) -> ActivityRecordResponse:
        projected = _ACTIVITY_SIDE_LOADS.project(
            document=BackstopApiResourceDocument[ActivityAttributes].model_construct(
                data=resource,
                included=included,
            )
        )
        return ActivityRecordResponse.from_attributes(
            resource.id,
            stream,
            resource.attributes,
            tags=self._tag_chips(projected.activity_tags),
            attendees=self._attendee_chips(projected.attendees),
            gist_max_chars=gist_max_chars,
        )

    def _tag_chips(
        self, tags: list[ActivityTagInclude] | None
    ) -> tuple[ActivityTagChipResponse, ...]:
        chips: list[ActivityTagChipResponse] = []
        for tag in tags or ():
            tag_id = tag.id
            name = tag.name
            if not tag_id or not name:
                continue
            chips.append(ActivityTagChipResponse(id=tag_id, name=name))
        return tuple(chips)

    def _attendee_chips(
        self, attendees: list[ActivityAttendeeResponse] | None
    ) -> tuple[AttendeeResponse, ...]:
        return tuple(
            AttendeeResponse(id=attendee.id, name=attendee.name) for attendee in attendees or ()
        )

    def _group_page(
        self,
        items: Sequence[TimelineRecord],
        *,
        activity_type: ActivityType,
        end_of_stream: bool,
        limit: int,
        offset: int,
        since: date | None = None,
        until: date | None = None,
        activity_tag_ids: tuple[str, ...] | None = None,
    ) -> ActivityGroupResponse[TimelineRecord]:
        """Pass items through in fetch order; attach this page's date_range and next."""
        grouped = tuple(items)
        return ActivityGroupResponse(
            activity_type=activity_type,
            items=grouped,
            date_range=self._date_range(grouped),
            next=(
                None
                if end_of_stream
                else ActivityContinuationResponse(
                    limit=limit,
                    offset=offset + len(grouped),
                    since=since,
                    until=until,
                    activity_tag_ids=activity_tag_ids,
                )
            ),
        )

    def _occurred_date(self, item: TimelineRecord) -> date | None:
        occurred = item.occurred_at
        if occurred is None:
            return None
        if isinstance(occurred, datetime):
            utc = (
                occurred.astimezone(UTC)
                if occurred.tzinfo is not None
                else occurred.replace(tzinfo=UTC)
            )
            return utc.date()
        return occurred

    def _date_range(self, items: Sequence[TimelineRecord]) -> DateRangeResponse | None:
        dates = [occurred for item in items if (occurred := self._occurred_date(item)) is not None]
        if not dates:
            return None
        return DateRangeResponse(start=min(dates), end=max(dates))
