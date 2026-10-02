from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Annotated, Self
from zoneinfo import ZoneInfo

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.generated.models.reminder import Reminder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import MAX_SCANNED_ITEMS, collect_pages, graph_errors
from office_365_mcp.shared.calendar import EventTime, event_time, window_bounds, zone_named
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller
from office_365_mcp.shared.window import runs_backwards

TOOL_NAME = "outlook_list_reminders"

STEP = "reminder_view"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Calendars.ReadBasic",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"starts_on": "2026-03-02", "ends_on": "2026-03-08"}

DEFAULT_TIME_ZONE = "UTC"

_WIRE_FORMAT = "%Y-%m-%dT%H:%M:%S.0000000"

_DESCRIPTION = """\
Lists the reminders that the signed-in user has on calendar events inside a date window. Each row \
gives the subject, the times of the event, the location, and the time when the reminder fires. \
outlook_list_events lists the events themselves.

Notes:
- `ends_on` must not fall before `starts_on`. Both arguments take a date or a moment. A bare \
date covers its whole day.
- A row has no event handle. To read the event, find it with outlook_list_events. Then pass \
its `uri` to outlook_read_event.
- Graph does not say which calendars this view covers. An empty list does not prove that no \
calendar holds a reminder.
"""

_ENDS_BEFORE_STARTS = (
    "outlook_list_reminders read nothing, because `ends_on` falls before `starts_on` and no "
    + "calendar holds a window that runs backwards. Put the earlier bound in `starts_on` and the "
    + "later bound in `ends_on`. Then call again. If you call this tool again with the same "
    + "arguments, the call will fail the same way."
)

_NOT_A_ZONE = (
    "outlook_list_reminders read nothing, because it cannot resolve the name in `time_zone`. "
    + "This argument takes an IANA zone name, such as `Europe/Zurich`, `America/New_York`, or "
    + "`UTC`. A Windows zone name, a city, a numeric offset, and an abbreviation such as `CEST` "
    + "do not work. If you call this tool again with the same arguments, the call will fail the "
    + "same way."
)


class ReminderSummary(BaseModel):
    subject: str | None = Field(
        description="The subject line of the event that has the reminder, or null if there is none."
    )
    starts: EventTime | None = Field(
        description=(
            "When the event starts, or null if Graph returned no time. `iso` gives the same "
            + "instant in the zone that the `time_zone` argument names."
        )
    )
    ends: EventTime | None = Field(
        description=(
            "When the event ends, or null if Graph returned no time. `iso` gives the same "
            + "instant in the zone that the `time_zone` argument names."
        )
    )
    location: str | None = Field(
        description="The location of the event as one line of text, or null if there is none."
    )
    web_link: str | None = Field(
        description=(
            "A link that opens the event in Outlook on the web, or null if Graph returned none. "
            + "This row has no event handle, because a reminder carries no calendar id and an "
            + "event handle needs one."
        )
    )
    fires_at: EventTime | None = Field(
        description=(
            "The time when the reminder is set to fire, or null if Graph returned none. It has "
            + "the same parts as `starts`."
        )
    )

    @classmethod
    def from_reminder(cls, reminder: Reminder, *, zone: ZoneInfo) -> Self:
        location = reminder.event_location
        return cls(
            subject=reminder.event_subject,
            starts=event_time(reminder.event_start_time, zone=zone),
            ends=event_time(reminder.event_end_time, zone=zone),
            location=None if location is None else location.display_name,
            web_link=reminder.event_web_link,
            fires_at=event_time(reminder.reminder_fire_time, zone=zone),
        )


class Reminders(BaseModel):
    reminders: list[ReminderSummary] = Field(
        description=(
            "These are the reminders that Graph returned for the window, in the order that Graph "
            + "returns them. An empty list means that Graph returned no reminder. Read `capped` "
            + "before you report that the list is complete."
        )
    )
    capped: bool = Field(
        description=(
            "True means that the listing stopped early, with more reminders still available. "
            + "Narrow the window to read the rest. False means that the listing read every "
            + "reminder that Graph returned for the window."
        )
    )


async def list_reminders(
    client: GraphServiceClient,
    *,
    starts_on: date | datetime,
    ends_on: date | datetime,
    time_zone: str = DEFAULT_TIME_ZONE,
) -> Reminders:
    zone = zone_named(time_zone)
    if zone is None:
        raise ToolError(_NOT_A_ZONE)
    if runs_backwards(starts_on, ends_on, zone=zone):
        raise ToolError(_ENDS_BEFORE_STARTS)
    opens, closes = (
        _utc_on_the_wire(bound) for bound in window_bounds(starts_on, ends_on, zone=zone)
    )
    view = client.me.reminder_view_with_start_date_time_with_end_date_time(
        end_date_time=closes, start_date_time=opens
    )
    base_url = view.request_adapter.base_url  # pyright: ignore[reportUnknownMemberType]
    documented_view = view.with_url(
        f"{base_url}/me/reminderView(startDateTime='{opens}',endDateTime='{closes}')"
    )

    with graph_errors(TOOL_NAME, step=STEP):
        first_page = await documented_view.get()
        assert first_page is not None, "Graph answered a reminder view with no collection"
        collected = await collect_pages(first_page, client, limit=MAX_SCANNED_ITEMS)

    return Reminders(
        reminders=[
            ReminderSummary.from_reminder(reminder, zone=zone) for reminder in collected.items
        ],
        capped=collected.capped,
    )


def _utc_on_the_wire(moment: str) -> str:
    return datetime.fromisoformat(moment).astimezone(UTC).strftime(_WIRE_FORMAT)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="List Reminders",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def outlook_list_reminders(
        starts_on: Annotated[
            date | datetime,
            Field(
                description=(
                    "This is where the window opens. A date, such as `2026-03-02`, opens at "
                    + "midnight of that day in `time_zone`. A moment, such as "
                    + "`2026-03-02T13:00:00`, opens partway through the day. A moment with no "
                    + "offset uses `time_zone`. A moment with its own offset keeps that offset. "
                    + "For upcoming reminders, use the date of today."
                )
            ),
        ],
        ends_on: Annotated[
            date | datetime,
            Field(
                description=(
                    "This is where the window closes, in the same forms as `starts_on`. A date "
                    + "covers the whole of that day, so the same date in both bounds lists that "
                    + "one day. A moment closes at the exact second that it names. A window with "
                    + "very many reminders returns only some of them, and `capped` says so."
                )
            ),
        ],
        time_zone: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "This is the zone for the window bounds and for each `iso` time in the "
                    + "answer. Use an IANA name, such as `Europe/Zurich`, `America/New_York`, or "
                    + "`UTC`. If the question is about a time of day, pass the zone of the user. "
                    + "The default zone is UTC. This tool refuses a Windows zone name, such as "
                    + "`W. Europe Standard Time`."
                ),
            ),
        ] = DEFAULT_TIME_ZONE,
        client: GraphServiceClient = graph,
    ) -> Reminders:
        return await list_reminders(
            client, starts_on=starts_on, ends_on=ends_on, time_zone=time_zone
        )
