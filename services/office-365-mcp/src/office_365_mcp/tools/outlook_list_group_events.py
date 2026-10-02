from collections.abc import Mapping
from datetime import date, datetime
from typing import Annotated, Self
from zoneinfo import ZoneInfo

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.groups.item.calendar_view.calendar_view_request_builder import (
    CalendarViewRequestBuilder,
)
from msgraph.generated.models.event import Event
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import collect_pages, graph_errors
from office_365_mcp.shared.calendar import EventTime, event_time, window_bounds, zone_named
from office_365_mcp.shared.mail import MailAddress
from office_365_mcp.shared.odata import spelled
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller
from office_365_mcp.shared.window import runs_backwards

TOOL_NAME = "outlook_list_group_events"

STEP = "calendar_events"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Calendars.Read",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "group_id": "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81",
    "starts_on": "2026-03-02",
    "ends_on": "2026-03-08",
}

_AGAIN = "If you call this tool again with the same arguments, the call will fail the same way."

GRAPH_NOT_FOUND = (
    "Microsoft 365 reports no calendar for this `group_id`, so this tool cannot list any event. "
    + "A team name, a channel id, and a chat id are not group ids. Call teams_list_my_teams again "
    + "and copy the `team_id` of the team exactly as it reports it. "
    + _AGAIN
)

DEFAULT_TIME_ZONE = "UTC"

_EVENT_FIELDS: tuple[str, ...] = (
    "subject",
    "bodyPreview",
    "start",
    "end",
    "isAllDay",
    "isCancelled",
    "type",
    "seriesMasterId",
    "location",
    "onlineMeeting",
    "organizer",
    "webLink",
)

_EventsQuery = CalendarViewRequestBuilder.CalendarViewRequestBuilderGetQueryParameters

_DESCRIPTION = """\
Lists the events on the calendar of ONE Microsoft 365 group within a date window. Each \
recurring series becomes one row for each occurrence. Every team is a group, so this lists the \
events of a team. If this deployment exposes outlook_list_events, use that tool for the \
calendars of a person.

Notes:
- `group_id` is the `team_id` of a team, from teams_list_my_teams. A team and its group have the \
same id.
- A row has no `uri`. No other tool of this connector can open a group event.
- This tool does not sort the rows. It keeps them in the order that Microsoft 365 returns them.
"""

_ENDS_BEFORE_STARTS = (
    "This tool made no request, because `ends_on` falls before `starts_on`, and no calendar holds "
    + "a window that runs backwards. Both bounds are inside the window, and a date covers its "
    + "whole day. The same date in both lists that one day. Put the earlier bound in `starts_on` "
    + "and the later bound in `ends_on`. Then call the tool again. "
    + _AGAIN
)

_NOT_A_ZONE = (
    "This tool made no request, because it cannot resolve the name in `time_zone`. This argument "
    + "takes an IANA zone name, such as `Europe/Zurich`, `America/New_York`, or `UTC`. A Windows "
    + "zone name, a city, a country, a numeric offset such as `+02:00`, and an abbreviation "
    + "such as `CEST` are not accepted. `Etc/GMT+2` does resolve, but it is two hours BEHIND UTC. "
    + "`UTC` is the default. If the question is not about a time of day, omit the argument. "
    + _AGAIN
)


class GroupEventWindow(BaseModel):
    starts_at: str = Field(
        description=(
            "The first instant of the window, in ISO-8601 format with an offset. It is the exact "
            + "bound that this call sent to Microsoft 365."
        )
    )
    ends_at: str = Field(
        description=(
            "The last instant of the window, in ISO-8601 format with an offset. For a date in "
            + "`ends_on`, it is midnight at the start of the next day. An event that starts at "
            + "exactly this instant belongs to the next window."
        )
    )
    time_zone: str = Field(
        description=(
            "The zone that the caller named. Both bounds and every `iso` value use it. Quote it "
            + "beside any time in this answer."
        )
    )


class GroupEventSummary(BaseModel):
    subject: str | None = Field(
        description=(
            "The text of the subject line of this group event, as Graph returns it. It is the "
            + "title of the event. This field is null when Graph returns no subject."
        )
    )
    preview: str | None = Field(
        description=(
            "A plain-text preview of the body of this group event. The preview can run over "
            + "several lines and can include the text of a meeting join link. This tool does not "
            + "return the full body. This field is null when Graph returns no preview."
        )
    )
    start: EventTime | None = Field(
        description=(
            "When this group event starts. Graph gives the time in UTC by default, and this tool "
            + "asks for no other zone. `iso` converts the same instant into the zone that the "
            + "`time_zone` argument names. This field is null when Graph returns no start time."
        )
    )
    end: EventTime | None = Field(
        description=(
            "When this group event ends, in the same form as `start`. This field is null when "
            + "Graph returns no end time."
        )
    )
    all_day: bool | None = Field(
        description=(
            "True if this group event lasts all day, and false if it does not. Microsoft "
            + "states that the `start` and `end` of an all-day event are both midnight in one "
            + "zone. This field is null when Graph returns no value."
        )
    )
    cancelled: bool | None = Field(
        description=(
            "True if this group event is canceled, and false if it is not. Report a canceled "
            + "event as canceled, and not as planned. This field is null when Graph returns no "
            + "value."
        )
    )
    kind: str | None = Field(
        description=(
            "The kind of row, as Microsoft spells it. `singleInstance` is an event that does not "
            + "repeat. `occurrence` is one date of a recurring series. `exception` is a date that "
            + "somebody changed. A calendar view returns only these three kinds. This field is "
            + "null when Graph returns no kind."
        )
    )
    in_series: bool = Field(
        description=(
            "True if this row belongs to a recurring series, because Graph names a series master "
            + "for it. False if the event does not repeat. This field is never null."
        )
    )
    location: str | None = Field(
        description=(
            "The name of the place of this group event, as one line of text. It can be a room or "
            + "a place that the organizer typed. This tool returns no street address and no "
            + "coordinates. This field is null when Graph returns no location."
        )
    )
    join_url: str | None = Field(
        description=(
            "The link that joins the online meeting of this group event. A client opens the link "
            + "in a browser, and the link then sends the user into the meeting. This field is "
            + "null when Graph returns no online meeting for the event."
        )
    )
    organizer: MailAddress | None = Field(
        description=(
            "Who organized this group event, as a display name and an email address. This field "
            + "is null when Graph returns no organizer."
        )
    )
    web_link: str | None = Field(
        description=(
            "The link that Microsoft 365 reports for this group event, to open it in Outlook on "
            + "the web. Microsoft states that the link opens the event only in earlier versions "
            + "of Outlook on the web. This field is null when Graph returns no link."
        )
    )

    @classmethod
    def from_event(cls, event: Event, *, zone: ZoneInfo) -> Self:
        online = event.online_meeting
        return cls(
            subject=event.subject,
            preview=event.body_preview,
            start=event_time(event.start, zone=zone),
            end=event_time(event.end, zone=zone),
            all_day=event.is_all_day,
            cancelled=event.is_cancelled,
            kind=spelled(event.type),
            in_series=event.series_master_id is not None,
            location=None if event.location is None else event.location.display_name,
            join_url=None if online is None else online.join_url,
            organizer=MailAddress.from_recipient(event.organizer),
            web_link=event.web_link,
        )


class GroupEvents(BaseModel):
    window: GroupEventWindow = Field(
        description=(
            "The exact range that this call sent to Microsoft 365. Report this range whenever "
            + "you use the answer to say what a team has planned. A window in the wrong zone "
            + "gives a correct answer to the wrong question."
        )
    )
    events: list[GroupEventSummary] = Field(
        description=(
            "The occurrences inside the window. One row shows one date of a recurring series, "
            + "and never the whole series. A cancelled event still appears, with `cancelled` set "
            + "to true. An empty list means that nothing matched inside the window. Read "
            + "`capped` before you treat an empty list as nothing planned."
        )
    )
    capped: bool = Field(
        description=(
            "True means that this call stopped with more of the window still available, because "
            + "`limit` filled up. To get more rows, raise `limit` or narrow the window. False "
            + "means that this call returned everything in the window, however few rows that is."
        )
    )


async def list_group_events(
    client: GraphServiceClient,
    *,
    group_id: str,
    starts_on: date | datetime,
    ends_on: date | datetime,
    time_zone: str = DEFAULT_TIME_ZONE,
    limit: int,
) -> GroupEvents:
    assert limit >= 1, f"limit must be at least 1, got {limit}"
    zone = zone_named(time_zone)
    if zone is None:
        raise ToolError(_NOT_A_ZONE)
    if runs_backwards(starts_on, ends_on, zone=zone):
        raise ToolError(_ENDS_BEFORE_STARTS)
    opens, closes = window_bounds(starts_on, ends_on, zone=zone)

    with graph_errors(TOOL_NAME, step=STEP):
        first_page = await client.groups.by_group_id(group_id).calendar_view.get(
            request_configuration=RequestConfiguration[_EventsQuery](
                query_parameters=_EventsQuery(
                    start_date_time=opens,
                    end_date_time=closes,
                    select=list(_EVENT_FIELDS),
                )
            )
        )
        assert first_page is not None, "Graph answered a group calendar view with no collection"
        collected = await collect_pages(first_page, client, limit=limit)

    return GroupEvents(
        window=GroupEventWindow(starts_at=opens, ends_at=closes, time_zone=time_zone),
        events=[GroupEventSummary.from_event(event, zone=zone) for event in collected.items],
        capped=collected.capped,
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="List Group Calendar Events",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def outlook_list_group_events(
        group_id: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The group whose calendar to list. Pass the `team_id` of a team, exactly as "
                    + "teams_list_my_teams reports it. A team and its Microsoft 365 group have "
                    + "the same id. A team name is not an id. Copy the id, and never build one."
                ),
            ),
        ],
        starts_on: Annotated[
            date | datetime,
            Field(
                description=(
                    "Where the window opens. This bound is inside the window. A date, such as "
                    + "`2026-03-02`, opens at midnight of that day in `time_zone`. A moment, "
                    + "such as `2026-03-02T13:00:00`, opens at that time. A moment with no "
                    + "offset is read in `time_zone`. A moment with an offset keeps that offset."
                )
            ),
        ],
        ends_on: Annotated[
            date | datetime,
            Field(
                description=(
                    "Where the window closes. This bound is inside the window, in the same forms "
                    + "as `starts_on`. A date covers the whole of that day. A moment closes at "
                    + "the second that it names. A window much wider than `limit` returns only "
                    + "part of its rows, and `capped` says when this happens."
                )
            ),
        ],
        time_zone: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The zone for the window and for every time in this answer, as an IANA name "
                    + "such as `Europe/Zurich` or `UTC`. Name a place, such as `Europe/Berlin`. "
                    + "If the question is about a time of day, pass the zone of the user. The "
                    + "default zone is UTC, and it reports the correct events at the wrong hour "
                    + "of day."
                ),
            ),
        ] = DEFAULT_TIME_ZONE,
        limit: Annotated[
            int,
            Field(
                ge=1,
                description=(
                    "This is the most events that this call returns. Paging happens inside the "
                    + "call, so this is the full answer, and not only a first page of it. Raise "
                    + "this value to get more events. Do not call this tool again with the same "
                    + "arguments."
                ),
            ),
        ] = 25,
        client: GraphServiceClient = graph,
    ) -> GroupEvents:
        return await list_group_events(
            client,
            group_id=group_id,
            starts_on=starts_on,
            ends_on=ends_on,
            time_zone=time_zone,
            limit=limit,
        )
