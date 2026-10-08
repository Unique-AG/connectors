from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.event import Event
from msgraph.generated.models.event_type import EventType
from msgraph.generated.users.item.calendars.item.events.item.instances.instances_request_builder import (  # noqa: E501
    InstancesRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import CollectedItems, collect_pages, graph_errors, graph_step
from office_365_mcp.shared.calendar import (
    SUMMARY_FIELDS,
    EventSummary,
    event_of,
    window_bounds,
    zone_named,
)
from office_365_mcp.shared.handles import EventHandle, event_handle
from office_365_mcp.shared.immutable_ids import immutable_id_headers
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller
from office_365_mcp.shared.window import runs_backwards

TOOL_NAME = "outlook_list_event_instances"

STEP_EVENTS = "calendar_events"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Calendars.Read", "Calendars.Read.Shared")

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "outlook:///events/AAMkSYNTHETIC-cal-0001%3D/AAMkAGI2SYNTHETIC-series-0001%3D",
    "starts_on": "2026-03-02",
    "ends_on": "2026-03-08",
}

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return this event. The handle is well formed, so this is not a bad "
    + "argument. Graph answers 'it was deleted', 'it moved to another calendar', and 'the "
    + "signed-in user cannot see it' with one 404. Report that this tool failed to read the "
    + "series. Do not report that the series ended. To find the series again, call "
    + "outlook_list_events for a window that holds one date of the series. Then pass the "
    + "`series_master_uri` of that row to this tool. If you call this tool again with the same "
    + "arguments, the call will fail the same way."
)

DEFAULT_TIME_ZONE = "UTC"

_InstancesQuery = InstancesRequestBuilder.InstancesRequestBuilderGetQueryParameters

_DESCRIPTION = """\
Lists the dates of ONE recurring series within a date window, given the series master. Each row \
is an occurrence, or an exception that somebody changed. outlook_list_events lists everything on \
a calendar. outlook_read_event reads one row in full.

Notes:
- Pass the `series_master_uri` of an outlook_list_events row. The `uri` of that row names one \
date and is not the master. If you pass a `uri`, this tool refuses and gives the master handle.
- `ends_on` must not fall before `starts_on`. Both arguments take a date or a moment. A bare \
date covers its whole day.
- On a calendar that the signed-in user does not own, a row whose `sensitivity` is `private` or \
`confidential` belongs to the owner. Report only that something is on then. Do not report its \
subject or `preview`.
"""

_NOT_AN_EVENT_HANDLE = (
    "outlook_list_event_instances read nothing, because `uri` is not an event handle. A readable "
    + "handle has exactly one shape:\n"
    + "  outlook:///events/{calendar_id}/{event_id}\n"
    + "Both ids are percent-encoded. Copy the `series_master_uri` of an outlook_list_events row, "
    + "and do not assemble one. A calendar handle, a mail handle, a subject line, and a bare "
    + "event id are not event handles. If you call this tool again with the same arguments, the "
    + "call will fail the same way."
)

_NOT_A_ZONE = (
    "outlook_list_event_instances read nothing, because it cannot resolve `time_zone`. This "
    + "argument takes an IANA zone name, such as `Europe/Zurich`, `America/New_York`, or `UTC`. "
    + "A Windows zone name, a city, a numeric offset, and an abbreviation such as `CEST` are not "
    + "IANA names. `Etc/GMT+2` does resolve, but it is two hours BEHIND UTC. `UTC` is the "
    + "default. If the question is not about a time of day, omit the argument. If you call this "
    + "tool again with the same arguments, the call will fail the same way."
)

_ENDS_BEFORE_STARTS = (
    "outlook_list_event_instances read nothing, because `ends_on` falls before `starts_on`. A "
    + "window cannot run backwards. Both arguments include what they name, so one date in both "
    + "bounds lists that one day. Put the earlier bound in `starts_on` and the later bound in "
    + "`ends_on`. If you call this tool again with the same arguments, the call will fail the "
    + "same way."
)

_DOES_NOT_REPEAT = (
    "outlook_list_event_instances read nothing, because this event is not part of a recurring "
    + "series. Only a series has instances. To read this event, call outlook_read_event with "
    + "the same `uri`. If you call this tool again with the same arguments, the call will fail "
    + "the same way."
)

_IS_ONE_DATE_OF_A_SERIES = (
    "outlook_list_event_instances read nothing. This event is one date of a recurring series, "
    + "and it is not the series master. Call this tool again with the `series_master_uri` of the "
    + "same row, which is:\n  "
)


class InstanceWindow(BaseModel):
    starts_at: str = Field(
        description=(
            "This is the first instant of the window, in ISO-8601 format with an offset, in the "
            + "zone that `time_zone` names. A date in `starts_on` opens the window at midnight "
            + "of that day."
        )
    )
    ends_at: str = Field(
        description=(
            "This is the last instant of the window, in ISO-8601 format with an offset, in the "
            + "zone that `time_zone` names. A date in `ends_on` closes the window at midnight "
            + "of the day after it. An occurrence that starts at exactly this instant belongs to "
            + "the next window."
        )
    )
    time_zone: str = Field(
        description=(
            "This is the zone that the caller named. Both bounds and every `iso` value in "
            + "`events` use this zone. Quote it beside any time in the answer."
        )
    )


class EventInstances(BaseModel):
    window: InstanceWindow = Field(
        description=(
            "This is the range that this call asked Microsoft for. Report this range when you "
            + "say which dates a series has. A window in the wrong zone gives a correct answer "
            + "to the wrong question."
        )
    )
    events: list[EventSummary] = Field(
        description=(
            "These are the occurrences and exceptions of the series inside the window. Graph "
            + "sets their order, so sort by `start.iso` when order matters. Microsoft states "
            + "that an occurrence canceled from the series is not in this list. Pass the `uri` "
            + "of a row to outlook_read_event to read the full body."
        )
    )
    capped: bool = Field(
        description=(
            "True means that this call stopped with more of the window still available, because "
            + "`limit` filled up. To get more rows, raise `limit` or narrow the window. False "
            + "means that this call returned every instance in the window, however few that is."
        )
    )


async def list_event_instances(
    client: GraphServiceClient,
    *,
    uri: str,
    starts_on: date | datetime,
    ends_on: date | datetime,
    time_zone: str = DEFAULT_TIME_ZONE,
    limit: int,
) -> EventInstances:
    assert limit >= 1, f"limit must be at least 1, got {limit}"
    handle = event_handle(uri)
    if handle is None:
        raise ToolError(_NOT_AN_EVENT_HANDLE)
    zone = zone_named(time_zone)
    if zone is None:
        raise ToolError(_NOT_A_ZONE)
    if runs_backwards(starts_on, ends_on, zone=zone):
        raise ToolError(_ENDS_BEFORE_STARTS)
    opens, closes = window_bounds(starts_on, ends_on, zone=zone)

    with graph_errors(TOOL_NAME):
        event = await event_of(client, calendar_id=handle.calendar_id, event_id=handle.event_id)
        collected = (
            await _instances_of(client, handle, opens=opens, closes=closes, limit=limit)
            if event.type == EventType.SeriesMaster
            else None
        )

    if collected is None:
        raise ToolError(_not_a_series_master(event, calendar_id=handle.calendar_id))
    return EventInstances(
        window=InstanceWindow(starts_at=opens, ends_at=closes, time_zone=time_zone),
        events=[
            EventSummary.from_event(instance, calendar_id=handle.calendar_id, zone=zone)
            for instance in collected.items
        ],
        capped=collected.capped,
    )


async def _instances_of(
    client: GraphServiceClient, handle: EventHandle, *, opens: str, closes: str, limit: int
) -> CollectedItems[Event]:
    headers = immutable_id_headers()
    with graph_step(STEP_EVENTS):
        first_page = (
            await client.me.calendars.by_calendar_id(handle.calendar_id)
            .events.by_event_id(handle.event_id)
            .instances.get(
                request_configuration=RequestConfiguration[_InstancesQuery](
                    query_parameters=_InstancesQuery(
                        start_date_time=_in_utc(opens),
                        end_date_time=_in_utc(closes),
                        select=list(SUMMARY_FIELDS),
                    ),
                    headers=headers,
                )
            )
        )
        assert first_page is not None, "Graph answered an instances read with no collection"
        return await collect_pages(first_page, client, limit=limit, headers=headers)


def _in_utc(moment: str) -> str:
    return datetime.fromisoformat(moment).astimezone(UTC).isoformat(timespec="seconds")


def _not_a_series_master(event: Event, *, calendar_id: str) -> str:
    if event.series_master_id is None:
        return _DOES_NOT_REPEAT
    master = EventHandle(calendar_id, event.series_master_id)
    return (
        f"{_IS_ONE_DATE_OF_A_SERIES}{master.uri}\n"
        + "If you call this tool again with the same arguments, the call will fail the same way."
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="List Event Instances",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def outlook_list_event_instances(
        uri: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "This is the handle of the recurring series master, in this shape:\n"
                    + "  outlook:///events/{calendar_id}/{event_id}\n"
                    + "Copy the `series_master_uri` of an outlook_list_events row, verbatim. The "
                    + "`uri` of that row is one date of the series, and it is not the master. If "
                    + "you pass a `uri`, this tool refuses and names the master handle to pass."
                ),
            ),
        ],
        starts_on: Annotated[
            date | datetime,
            Field(
                description=(
                    "This is where the window opens, and this bound is inside the window. A "
                    + "date, such as `2026-03-02`, opens at midnight of that day in `time_zone`. "
                    + "A moment, such as `2026-03-02T13:00:00`, opens partway through the day. A "
                    + "moment with no offset is read in `time_zone`."
                )
            ),
        ],
        ends_on: Annotated[
            date | datetime,
            Field(
                description=(
                    "This is where the window closes, and this bound is inside the window. It "
                    + "takes the same two forms as `starts_on`. A date covers the whole of that "
                    + "day, so the same date in both bounds lists one day. A moment closes at "
                    + "the exact second that it names."
                )
            ),
        ],
        time_zone: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "This is the zone for the window and for every time in the answer, as an "
                    + "IANA name such as `Europe/Zurich` or `UTC`. If the question is about a "
                    + "time of day, pass the zone of the user. The default zone is UTC. Do not "
                    + "use an `Etc/GMT` key. Its sign runs the other way."
                ),
            ),
        ] = DEFAULT_TIME_ZONE,
        limit: Annotated[
            int,
            Field(
                ge=1,
                description=(
                    "This is the most instances that this call returns. Paging happens inside "
                    + "the call, so this is the full answer, and not only a first page of it. "
                    + "Raise this value to get more instances. Do not call this tool again with "
                    + "the same arguments."
                ),
            ),
        ] = 25,
        client: GraphServiceClient = graph,
    ) -> EventInstances:
        return await list_event_instances(
            client,
            uri=uri,
            starts_on=starts_on,
            ends_on=ends_on,
            time_zone=time_zone,
            limit=limit,
        )
