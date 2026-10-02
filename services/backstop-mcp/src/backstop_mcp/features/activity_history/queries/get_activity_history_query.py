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
    BackstopApiSingleResourceDocument,
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
from backstop_mcp.features.activity_history.internal_dto import AttendeeDto
from backstop_mcp.features.activity_history.queries.get_meeting_attendees_query import (
    GetMeetingAttendeesQuery,
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
    ActivityIncludesResponse,
    include_plan,
)
from backstop_mcp.features.includes import (
    ActivityTagChipResponse as ActivityTagInclude,
)
from backstop_mcp.features.party_resolver import ResolvedPartyDto
from backstop_mcp.features.ui_links import BuildEntityLinkUtil, activity_link_target

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

    def __init__(
        self,
        *,
        client: BackstopClient,
        build_entity_link_util: BuildEntityLinkUtil,
        get_meeting_attendees_query: GetMeetingAttendeesQuery,
    ) -> None:
        self._client: BackstopClient = client
        self._build_entity_link_util: BuildEntityLinkUtil = build_entity_link_util
        self._get_meeting_attendees_query: GetMeetingAttendeesQuery = get_meeting_attendees_query

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
            schema=BackstopApiSingleResourceDocument[PartyRecordResponse],
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

        attributes = document.data.attributes
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
        resources = tuple(page.items)
        if since is not None and until is not None:
            resources, cutoff_hit = self._truncate_since(resources, stream=stream, since=since)
            end_of_stream = cutoff_hit or raw_count < limit
        else:
            end_of_stream = raw_count < limit
        attendees = await self._attendees(resources, stream=stream)
        items = tuple(
            self._record_from_resource(
                resource,
                stream=stream,
                included=page.included,
                attendees=row_attendees,
                gist_max_chars=gist_max_chars,
            )
            for resource, row_attendees in zip(resources, attendees, strict=True)
        )
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
        self,
        resources: tuple[_ActivityResource, ...],
        *,
        stream: BackstopActivityType,
        since: date,
    ) -> tuple[tuple[_ActivityResource, ...], bool]:
        """Drop the first row older than `since` and everything after (stream is `-effectiveDate`).

        Rows with a missing `effectiveDate` never trip the cutoff — left intentional until we
        confirm null-date ordering against the live Backstop API. Runs before the attendee
        fetch so a truncated row costs no request.
        """
        for index, resource in enumerate(resources):
            effective_date = resource.attributes.effective_date
            if effective_date is None:
                logger.debug(
                    "activity_history.since_truncate.null_date",
                    extra={
                        "activity_id": resource.id,
                        "stream": stream,
                        "since": since.isoformat(),
                    },
                )
                continue
            if effective_date < since:
                logger.info(
                    "activity_history.since_truncate.cutoff",
                    extra={
                        "activity_id": resource.id,
                        "stream": stream,
                        "effective_date": effective_date.isoformat(),
                        "since": since.isoformat(),
                        "kept": index,
                        "dropped": len(resources) - index,
                    },
                )
                return resources[:index], True
        return resources, False

    async def _attendees(
        self,
        resources: Sequence[_ActivityResource],
        *,
        stream: BackstopActivityType,
    ) -> tuple[tuple[AttendeeResponse, ...] | None, ...]:
        """Attendees per meeting or call, aligned with `resources`. Other types stay absent.

        A missing id or a failed lookup leaves that row's attendees absent.
        """
        if stream not in {"meeting", "call"}:
            return tuple(None for _ in resources)
        resource_ids = tuple(
            None
            if resource.attributes.specific_resource is None
            else resource.attributes.specific_resource.resource_id
            for resource in resources
        )
        fetched = await asyncio.gather(
            *(
                self._get_meeting_attendees_query.run(resource_id=resource_id)
                for resource_id in resource_ids
                if resource_id is not None
            ),
            return_exceptions=True,
        )
        results = iter(fetched)
        return tuple(
            None if resource_id is None else self._attendee_responses(resource_id, next(results))
            for resource_id in resource_ids
        )

    def _record_from_resource(
        self,
        resource: BackstopApiResource[ActivityAttributes],
        *,
        stream: BackstopActivityType,
        included: list[dict[str, object]],
        attendees: tuple[AttendeeResponse, ...] | None,
        gist_max_chars: int,
    ) -> ActivityRecordResponse:
        projected = _ACTIVITY_SIDE_LOADS.project(
            document=BackstopApiSingleResourceDocument[ActivityAttributes].model_construct(
                data=resource,
                included=included,
            )
        )
        return ActivityRecordResponse.from_attributes(
            resource.id,
            stream,
            resource.attributes,
            tags=self._tag_chips(projected.activity_tags),
            attendees=attendees,
            gist_max_chars=gist_max_chars,
            url=self._record_url(stream, resource.attributes),
        )

    def _record_url(
        self, stream: BackstopActivityType, attributes: ActivityAttributes
    ) -> str | None:
        """CRM URL from the row's `specificResource` id — the `/entity-activity-details` id.

        The row's own `id` is a per-stream activities id, not that one, so a row Backstop
        sent without `specificResource` gets no link rather than a wrong one.
        """
        specific = attributes.specific_resource
        if specific is None or specific.resource_id is None:
            return None
        target = activity_link_target(
            activity_type=stream,
            entity_activity_details_id=specific.resource_id,
        )
        if target is None:
            return None
        return self._build_entity_link_util.canonical_url(target=target)

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

    def _attendee_responses(
        self,
        resource_id: str,
        fetched: tuple[AttendeeDto, ...] | BaseException,
    ) -> tuple[AttendeeResponse, ...] | None:
        """Map one attendee fetch onto the history row. A failure stays absent."""
        if isinstance(fetched, BaseException):
            logger.warning(
                "activity_history.attendees.join_failed",
                extra={"resource_id": resource_id},
                exc_info=fetched,
            )
            return None
        return tuple(
            AttendeeResponse(
                id=attendee.id,
                name=attendee.name,
                company=attendee.company_name,
                job_title=attendee.job_title,
            )
            for attendee in fetched
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
