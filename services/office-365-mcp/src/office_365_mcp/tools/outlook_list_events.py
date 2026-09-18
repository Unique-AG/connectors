"""`outlook_list_events` — one calendar's occurrences over a window, never a recurrence rule.

`GET /me/events` returns series masters, so this reads `calendarView`, whose required
`startDateTime`/`endDateTime` carry their own offset and ignore the `Prefer: outlook.timezone`
header (https://learn.microsoft.com/en-us/graph/api/calendar-list-calendarview). That header is not
sent, so rows arrive in UTC. A `calendarView` row carries no calendar id, so the calendar is read
first and supplies half of every handle minted here.

`calendarView` accepts a `$filter` on a FLAT property, which its own page documents nowhere —
hence server-side `cancelled` and `subject_contains`, both live-verified. A NESTED path is the
exception: `responseStatus/response` answers alone but returns 500 as soon as it is conjoined with
another property, so `owner_response` stays a predicate over the rows. There is no attendee filter
at any spelling.
"""

from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import Annotated, Literal

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.headers_collection import HeadersCollection
from msgraph.generated.models.event import Event
from msgraph.generated.users.item.calendars.item.calendar_view.calendar_view_request_builder import (  # noqa: E501
    CalendarViewRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import collect_pages, graph_errors, graph_step
from office_365_mcp.shared.calendar import (
    SUMMARY_FIELDS,
    CalendarSummary,
    EventSummary,
    calendar_of,
    spelled,
    window_bounds,
    zone_named,
)
from office_365_mcp.shared.handles import calendar_handle
from office_365_mcp.shared.odata import odata_literal
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller
from office_365_mcp.shared.window import runs_backwards

TOOL_NAME = "outlook_list_events"

STEP_EVENTS = "calendar_events"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Calendars.Read", "Calendars.Read.Shared")

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"starts_on": "2026-03-02", "ends_on": "2026-03-08"}

GRAPH_NOT_FOUND = (
    "Microsoft 365 will not return this calendar, so this tool cannot list any event in it. If the "
    + "caller used `calendar_ref`, the handle is well formed. The calendar was most likely "
    + "deleted, or the person who shared it stopped sharing it. So call outlook_list_calendars "
    + "again and take the `uri` it reports now, which also shows whether that calendar is still "
    + "on offer. If "
    + "the caller passed no `calendar_ref`, this mailbox reports no primary calendar at all, which "
    + "does not happen for a licensed Microsoft 365 mailbox and is worth reporting as such. "
    + "Retrying with the same argument will fail identically."
)

MAX_RESULTS = 50

DEFAULT_TIME_ZONE = "UTC"

MIN_FRAGMENT_CHARACTERS = 2

type OwnerResponse = Literal["accepted", "tentativelyAccepted", "declined", "notResponded"]

_EARLIEST_FIRST = "start/dateTime"

_PREFER_IMMUTABLE_IDS = ("Prefer", 'IdType="ImmutableId"')

_EventsQuery = CalendarViewRequestBuilder.CalendarViewRequestBuilderGetQueryParameters

_DESCRIPTION = """\
Lists the occurrences on ONE calendar within a date window, earliest start first, expanding each \
recurring series into one row per occurrence.

Notes:
- `ends_on` must not fall before `starts_on`; both take a date or a moment, and a bare date \
covers its whole day.
"""

_ENDS_BEFORE_STARTS = (
    "outlook_list_events read nothing, because `ends_on` falls before `starts_on` and no calendar "
    + "holds a window that runs backwards. Both arguments include what they name — a date covers "
    + "its whole day — so one date in both lists that single day. Put the earlier bound in "
    + "`starts_on` and the later one in `ends_on`, then call again. Retrying with the same two "
    + "will fail identically."
)

_NOT_A_ZONE = (
    "outlook_list_events read nothing, because it cannot resolve the name in `time_zone`. This "
    + "argument takes an IANA zone name, such as `Europe/Zurich`, `America/New_York` or `UTC`. A "
    + "Windows zone name such as `W. Europe Standard Time` is not accepted here, and neither is a "
    + "city, a country, a numeric offset such as `+02:00` or a daylight abbreviation such as "
    + "`CEST` or `PST`. `Etc/GMT+2` does resolve, and the sign of an `Etc/GMT` key runs the other "
    + "way, so that name is two hours BEHIND UTC rather than ahead. `UTC` is the default, so omit "
    + "the argument entirely when the question is not about a time of day. Retrying with the same "
    + "name will fail identically."
)

_NOT_A_CALENDAR_HANDLE = (
    "outlook_list_events read nothing, because `calendar_ref` is not a calendar handle. One shape "
    + "addresses a calendar, outlook:///calendars/{id}, exactly as outlook_list_calendars reported "
    + "it in `uri`. A calendar's name, an owner's email address, an event handle and a bare id are "
    + "none of them calendar handles. Call outlook_list_calendars to see which calendars this "
    + "mailbox reaches and to take the handle of the one that is meant, or omit `calendar_ref` for "
    + "the user's own primary calendar. Retrying with the same value will fail identically."
)


class EventWindow(BaseModel):
    """The time range this call asked Microsoft for, exactly as it went on the wire."""

    starts_at: str = Field(
        description=(
            "The first instant of the window, ISO-8601 with an offset: midnight at the start of "
            + "`starts_on` in `time_zone`, the exact bound Microsoft was asked for."
        )
    )
    ends_at: str = Field(
        description=(
            "The last instant of the window, ISO-8601 with an offset. It is midnight at the start "
            + "of the day AFTER `ends_on`, which is what makes the whole of `ends_on` fall inside "
            + "the window. An event starting exactly at this instant belongs to the next window."
        )
    )
    time_zone: str = Field(
        description=(
            "The zone both bounds carry and the zone every row's `iso` is stated in, as the caller "
            + "named it. Quote it beside any time this answer is reported in."
        )
    )


class CalendarEvents(BaseModel):
    """One calendar, the window that was asked for, and the occurrences inside it."""

    calendar: CalendarSummary = Field(
        description=(
            "The calendar these rows came from, read before them. `owner` names whose calendar "
            + "it is; `can_view_private_items` says whether its private items are legible here. "
            + "`is_mine` is null in this answer because this call reads no `/me` — call "
            + "outlook_list_calendars for that. When `can_edit` and `can_view_private_items` are "
            + "both false, rows arrive stripped: `subject` holds the display form of `show_as`, "
            + "`preview`, `location` and `attendee_count` come back empty or zero, and "
            + "`organizer` names the signed-in user regardless of who organized it. Report only "
            + "the time, `show_as`, and `cancelled` for a row of that shape, and say the rest "
            + "was not readable."
        )
    )
    window: EventWindow = Field(
        description=(
            "The exact range Microsoft was asked for. Report it whenever the answer is used to "
            + "say what somebody has on: a window in the wrong zone answers a different question "
            + "correctly."
        )
    )
    events: list[EventSummary] = Field(
        description=(
            "The occurrences inside the window, earliest start first. One row per date of a "
            + "recurring series, never the series itself: `in_series` set on several rows with "
            + "the same subject means one meeting repeating, not several meetings. A canceled "
            + "event is listed with `cancelled` set rather than omitted. On a calendar the "
            + "signed-in user does not own, a row whose `sensitivity` is `private` or "
            + "`confidential` is the owner's business — report only that something is on then, "
            + "never its subject or `preview`. Pass a row's `uri` to outlook_read_event for the "
            + "full body and attendee list. Empty means nothing matched in this window; read "
            + "`capped` before treating that as nothing being on."
        )
    )
    capped: bool = Field(
        description=(
            "True when this call stopped with more of the window still on offer, either because "
            + "`limit` filled up or because `owner_response` discarded rows before reaching it — "
            + "`cancelled` and `subject_contains` never cause this, since a row they exclude "
            + "never reaches the call. Raise `limit` or narrow the window to get more. False "
            + "means everything in it that matched already came back, however few rows that is, "
            + "so an empty list with `capped` false is the answer that nothing is on."
        )
    )


async def list_events(
    client: GraphServiceClient,
    *,
    starts_on: date | datetime,
    ends_on: date | datetime,
    time_zone: str = DEFAULT_TIME_ZONE,
    calendar_ref: str | None = None,
    subject_contains: str | None = None,
    cancelled: bool | None = None,
    owner_response: OwnerResponse | None = None,
    limit: int,
) -> CalendarEvents:
    assert 1 <= limit <= MAX_RESULTS, f"limit must be within 1..{MAX_RESULTS}, got {limit}"
    zone = zone_named(time_zone)
    if zone is None:
        raise ToolError(_NOT_A_ZONE)
    if runs_backwards(starts_on, ends_on, zone=zone):
        raise ToolError(_ENDS_BEFORE_STARTS)
    named = _calendar_named(calendar_ref)
    opens, closes = window_bounds(starts_on, ends_on, zone=zone)
    narrowed = _filter_for(subject_contains=subject_contains, cancelled=cancelled)

    with graph_errors(TOOL_NAME):
        calendar = await calendar_of(client, calendar_id=named)
        calendar_id = calendar.id
        assert calendar_id is not None, "Graph answered a calendar read with a calendar with no id"
        headers = _headers()
        with graph_step(STEP_EVENTS):
            first_page = await client.me.calendars.by_calendar_id(calendar_id).calendar_view.get(
                request_configuration=RequestConfiguration[_EventsQuery](
                    query_parameters=_EventsQuery(
                        start_date_time=opens,
                        end_date_time=closes,
                        filter=narrowed,
                        select=list(SUMMARY_FIELDS),
                        top=limit,
                        orderby=[_EARLIEST_FIRST],
                    ),
                    headers=headers,
                )
            )
            assert first_page is not None, "Graph answered a calendar view with no collection"
            collected = await collect_pages(
                first_page,
                client,
                limit=limit,
                matches=_matching(owner_response=owner_response),
                headers=headers,
            )

    return CalendarEvents(
        calendar=CalendarSummary.from_calendar(calendar, signed_in=None),
        window=EventWindow(starts_at=opens, ends_at=closes, time_zone=time_zone),
        events=[
            EventSummary.from_event(event, calendar_id=calendar_id, zone=zone)
            for event in collected.items
        ],
        capped=collected.capped,
    )


def _calendar_named(calendar_ref: str | None) -> str | None:
    if calendar_ref is None:
        return None
    handle = calendar_handle(calendar_ref)
    if handle is None:
        raise ToolError(_NOT_A_CALENDAR_HANDLE)
    return handle.calendar_id


def _filter_for(*, subject_contains: str | None, cancelled: bool | None) -> str | None:
    """The `$filter` this call sends, or None when neither server-side narrowing was asked for.

    Both forms are live-verified against `calendarView` beside `$orderby=start/dateTime`, each sent
    once with a value present in the window and once with one that cannot match — which is what
    separates a filter Graph evaluates from one it drops in silence.
    """
    terms: list[str] = []
    if cancelled is not None:
        terms.append(f"isCancelled eq {'true' if cancelled else 'false'}")
    if subject_contains is not None:
        terms.append(f"contains(subject,'{odata_literal(subject_contains)}')")
    if not terms:
        return None
    return " and ".join(terms)


def _matching(*, owner_response: OwnerResponse | None) -> Callable[[Event], bool] | None:
    """The one narrowing this tool still applies in process, or None when it was not asked for."""
    if owner_response is None:
        return None

    def keeps(event: Event) -> bool:
        return _owner_answered(event, owner_response)

    return keeps


def _owner_answered(event: Event, owner_response: OwnerResponse) -> bool:
    """Whether the calendar owner's answer is the one asked for, compared in process.

    `responseStatus/response` IS filterable on `calendarView` alone, but a live probe on 2026-09-10
    found a nested path 500s once conjoined with any other property, in both orders and
    parenthesised.
    """
    status = event.response_status
    if status is None or status.response is None:
        return False
    return spelled(status.response) == owner_response


def _headers() -> HeadersCollection:
    """Built per request: kiota's `RequestConfiguration.headers` defaults to one collection shared
    process-wide, and `collect_pages` needs this same collection or page two arrives as `RestId`s.
    """
    headers = HeadersCollection()
    headers.add(*_PREFER_IMMUTABLE_IDS)
    return headers


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="List Calendar Events",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def outlook_list_events(
        starts_on: Annotated[
            date | datetime,
            Field(
                description=(
                    "Where the window opens, inclusive. A date (`2026-03-02`) opens at that "
                    + "day's midnight in `time_zone` and covers the whole day; a moment "
                    + "(`2026-03-02T13:00:00`) opens partway through one. A moment with no "
                    + "offset is read in `time_zone`; one carrying its own offset keeps it. For "
                    + "anything about what is coming up, this is today."
                )
            ),
        ],
        ends_on: Annotated[
            date | datetime,
            Field(
                description=(
                    "Where the window closes, inclusive, in the same shapes as `starts_on`. A "
                    + "date covers the whole of that day, so the same date in both bounds lists "
                    + "that one day; a moment closes at the second named, and an occurrence "
                    + "starting exactly then belongs to the next window. A window much wider "
                    + "than `limit` returns only its earliest events, not a summary of the whole "
                    + "span — `capped` says when that happened; ask one window at a time for a "
                    + "long stretch."
                )
            ),
        ],
        time_zone: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "Which zone the window and every reported time are stated in, as an IANA name "
                    + "such as `Europe/Zurich`, `America/New_York` or `UTC`. Pass the user's own "
                    + "zone whenever the question is about a time of day: the default answers in "
                    + "UTC, which reports the right meetings at the wrong hours. A Windows zone "
                    + "name such as `W. Europe Standard Time` is refused here. "
                    + "`Etc/GMT+2` is a real key that means two hours BEHIND UTC, so name a place "
                    + "such as `Europe/Berlin` instead."
                ),
            ),
        ] = DEFAULT_TIME_ZONE,
        calendar_ref: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "Which calendar to list, as the `uri` of an outlook_list_calendars result: "
                    + "`outlook:///calendars/{id}`. Omit it for the signed-in user's own primary "
                    + "calendar. Pass it for a calendar somebody shared, which "
                    + "outlook_list_calendars lists as a row named after its owner."
                ),
            ),
        ] = None,
        subject_contains: Annotated[
            str | None,
            Field(
                min_length=MIN_FRAGMENT_CHARACTERS,
                description=(
                    "Keep only events whose subject contains this text, as a substring rather "
                    + "than a word search: `pricing` matches `Quarterly pricing review` and also "
                    + "`Repricing`, and a two-word fragment misses a subject that spells those "
                    + "words apart. Applied together with `cancelled` and `owner_response`, a "
                    + "row must satisfy all of them."
                ),
            ),
        ] = None,
        cancelled: Annotated[
            bool | None,
            Field(
                description=(
                    "Narrow by whether the occurrence was called off. Omitting it lists both: a "
                    + "cancelled event stays on the calendar until somebody removes it, so "
                    + "hiding it by default would misreport a day that had a meeting until it "
                    + "was called off this morning. `false` drops cancelled rows — useful over a "
                    + "wide window, where cancelled clutter in the earliest rows would otherwise "
                    + "spend `limit` before reaching live ones. `true` returns only the "
                    + "cancelled rows."
                )
            ),
        ] = None,
        owner_response: Annotated[
            OwnerResponse | None,
            Field(
                description=(
                    "Keep only events the calendar's OWNER answered this way: `accepted`, "
                    + "`tentativelyAccepted`, `declined`, or `notResponded` — `show_as` does not "
                    + "answer this, since a busy block is not an acceptance. Without "
                    + "`calendar_ref` the owner is the signed-in user, so `accepted` reads as "
                    + "meetings said yes to and `notResponded` as invitations still owed an "
                    + "answer; on a shared calendar it is that owner's answer, never the "
                    + "signed-in user's. A row with none of these four recorded is dropped. Use "
                    + "`owner_is_organizer` for meetings the owner called, a different question "
                    + "this field does not answer."
                )
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_RESULTS,
                description=(
                    f"How many events to return, at most {MAX_RESULTS}. They are the earliest that "
                    + "many of the window. Paging happens inside the call, so this is the whole "
                    + "answer rather than a first page: raise it rather than calling again with "
                    + "the same arguments."
                ),
            ),
        ] = 25,
        client: GraphServiceClient = graph,
    ) -> CalendarEvents:
        return await list_events(
            client,
            starts_on=starts_on,
            ends_on=ends_on,
            time_zone=time_zone,
            calendar_ref=calendar_ref,
            subject_contains=subject_contains,
            cancelled=cancelled,
            owner_response=owner_response,
            limit=limit,
        )
