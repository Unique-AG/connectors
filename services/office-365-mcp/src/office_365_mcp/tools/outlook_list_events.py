"""`outlook_list_events` — one calendar's occurrences over a date window, never a recurrence rule.

"What is on next week" is a question about occurrences, and only one Graph collection answers it.
`GET /me/events` "contains single instance meetings and series masters", and Microsoft points
elsewhere for the rest: "To get expanded event instances, you can get the calendar view"
(https://learn.microsoft.com/en-us/graph/api/user-list-events). A series master carries a
`recurrence` rule and one start date, so a listing built on `/events` reports a weekly meeting as
one row in the week it was created and as nothing at all in the week somebody asked about.
`calendarView` reports "the occurrences, exceptions and single instances of events in a calendar
view defined by a time range" (https://learn.microsoft.com/en-us/graph/api/calendar-list-calendarview),
which is this tool's whole promise. `startDateTime` and `endDateTime` are required there, so a
window is not an optional narrowing of this call. It is the call.

**The two window bounds carry their own offset, and no header changes that.** "The values of
startDateTime and endDateTime are interpreted using the timezone offset specified in the value and
aren't impacted by the value of the Prefer: outlook.timezone header if present. If no timezone
offset is included in the value, it is interpreted as UTC"
(https://learn.microsoft.com/en-us/graph/api/calendar-list-calendarview). So `shared.calendar`
renders both bounds with the offset of the zone the caller named, and midnight in Zurich asks for a
different eight days than midnight in UTC.

**This tool sends no `Prefer: outlook.timezone`, on purpose.** Microsoft documents the other side
of that: "If not specified, those time values are returned in UTC" (same page). Every row therefore
arrives in UTC and `shared.calendar.event_time` converts it with `zoneinfo`, beside Graph's own two
verbatim values. That header moves the conversion into Exchange, where a zone name it rejects
fails the whole request instead of costing one field.

**Two Graph calls, and the calendar is read first.** An event id is only meaningful beside the
calendar it was read from, and Graph puts no calendar id on a `calendarView` row. So the calendar
read supplies both halves of every handle this tool mints, and the envelope that says whose
calendar was listed and whether the user can see private items in it. That read is
`shared.calendar.calendar_of`, which two other tools share, and the listing that follows always
addresses `/me/calendars/{id}/calendarView` with the id it returned.

**`Prefer: IdType="ImmutableId"` on the listing.** The ids it mints become handles, and a handle
built from a `RestId` dies the moment Outlook files the event elsewhere. `outlook_read_event` sends
the same preference on the way in, so the two agree about which id space a handle is spelled in.
The collection is built per request: kiota's `RequestConfiguration.headers` default is one object
shared process-wide, so a preference set once leaks onto every other Graph call and still fails to
reach page two. This tool hands that same collection to `collect_pages`.

**`with_person` and `subject_contains` are predicates over the rows, never `$filter`.** Microsoft
documents no `$filter` over `attendees`, and the ordering this tool promises is `$orderby` on
`start/dateTime`, which Microsoft's own samples use. A filter composed against undocumented support
answers `200 OK` and the wrong rows. So both fragments run through `collect_pages(matches=...)`,
which is also why a narrow fragment over a busy calendar reports `capped`: the scan ran out before
`limit` filled.
"""

from collections.abc import Callable, Mapping
from datetime import date
from typing import Annotated

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
    MAX_WINDOW_DAYS,
    SUMMARY_FIELDS,
    CalendarSummary,
    EventSummary,
    calendar_of,
    person_matches,
    subject_matches,
    window_bounds,
    zone_named,
)
from office_365_mcp.shared.handles import calendar_handle
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "outlook_list_events"

STEP_EVENTS = "calendar_events"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Calendars.Read", "Calendars.Read.Shared")

# One week of the signed-in user's own primary calendar: the default call, and the one that reaches
# Graph with no handle from a previous response.
GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"starts_on": "2026-03-02", "ends_on": "2026-03-08"}

# The default 404 advice says to check that the id came from a tool response, verbatim. A calendar
# handle is this connector's own, so that advice sends a model looking for a typing mistake that
# cannot be there.
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

# UTC and nothing cleverer. A guess at the user's own zone reads as a fact about their calendar,
# and an hour is exactly the size of mistake nobody notices.
DEFAULT_TIME_ZONE = "UTC"

# One or two characters match most of a calendar, so a fragment shorter than this filters nothing
# while reading as a filter that worked.
MIN_FRAGMENT_CHARACTERS = 2

# Microsoft's own samples order a calendar view on this, and it is the order this tool promises: a
# window read from its start.
_EARLIEST_FIRST = "start/dateTime"

_PREFER_IMMUTABLE_IDS = ("Prefer", 'IdType="ImmutableId"')

_EventsQuery = CalendarViewRequestBuilder.CalendarViewRequestBuilderGetQueryParameters

_DESCRIPTION = """\
List what is on ONE calendar between two dates, earliest start first. This reads Microsoft's \
calendar view, so a recurring series arrives as one row per occurrence inside the window: a weekly \
stand-up over three weeks is three rows, each with its own date and its own handle. `starts_on` \
and `ends_on` are dates, and both of those days are covered whole. Each row states its time three \
ways: Graph's own wall-clock text, Graph's own zone name, and `iso`, the same instant in \
`time_zone`. `time_zone` defaults to UTC and takes an IANA name such as `Europe/Zurich`. A wrong \
zone does not fail here. It answers the right meetings at the wrong hours. So pass the user's own \
zone for any question about a time of day, and quote `iso` rather than `local`, the wall-clock \
text, except on a row whose `all_day` is true, where `iso` is a UTC midnight moved into \
`time_zone`, so in a zone west of UTC it names the day before. Take the date of an all-day row \
from `local`. \
Without `calendar_ref` this lists the signed-in user's own primary calendar. Pass `calendar_ref`, \
the `uri` of an outlook_list_calendars row, for a calendar somebody shared. For "my next meeting \
with Dana", pass `with_person` and set `starts_on` to today: the rows are in start order, so the \
earliest match is the first one. If nothing matched and `capped` is false, that window is empty, \
so widen `ends_on` and ask again. This tool never picks a row for the user. Report the matches and \
let the user choose which one is meant. `owner_response` is the answer of the person who OWNS the \
calendar, so on a shared calendar it is that person's answer and never the signed-in user's. On a \
calendar the user does not own, a row whose `sensitivity` is `private` or `confidential` is the \
owner's private business: say that something is on at that time, and do not relay its subject or \
its preview. A canceled event stays in a calendar until somebody removes it, so this tool flags \
those rows with `cancelled` rather than hiding them. Read that field before telling anybody a \
meeting is on. Pass a row's `uri` to outlook_read_event for the full body and the attendee list.\
"""

_ENDS_BEFORE_STARTS = (
    "outlook_list_events read nothing, because `ends_on` falls before `starts_on` and no calendar "
    + "holds a window that runs backwards. Both arguments are dates, and both days are covered "
    + "whole, so one date in both lists that single day. Put the earlier date in `starts_on` and "
    + "the later one in `ends_on`, then call again. Retrying with the same two dates will fail "
    + "identically."
)

_WINDOW_TOO_WIDE = (
    "outlook_list_events read nothing, because the window between `starts_on` and `ends_on` is "
    + f"wider than {MAX_WINDOW_DAYS} days. A calendar view expands every recurring series into one "
    + "row per occurrence, so a year of a daily stand-up is hundreds of rows of the same meeting "
    + f"and answers no question. Ask for {MAX_WINDOW_DAYS} days or fewer. If the question really "
    + "is about a whole year, ask one window at a time and say which window each answer covers. "
    + "Retrying with the same two dates will fail identically."
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
            "The first instant of the window, ISO-8601 with an offset. It is midnight at the "
            + "start of `starts_on` in `time_zone`. Graph reads the offset in this value and "
            + "nothing else, so this is the bound that was really asked for."
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
            "The calendar these rows came from, read before them. `owner` says whose calendar it "
            + "is and `can_view_private_items` says whether its private items are legible here. "
            + "`is_mine` is null in this answer: this tool reads no `/me`, so it cannot tell "
            + "whether the owner is the signed-in user. Read `owner` instead, or call "
            + "outlook_list_calendars, which does answer it."
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
            + "recurring series, never the series itself, so `in_series` set on several rows with "
            + "the same subject is one meeting repeating and not several meetings. A canceled "
            + "event is listed with `cancelled` set. Empty when nothing is on in this window, or "
            + "when nothing in it matched `with_person` or `subject_contains`."
        )
    )
    capped: bool = Field(
        description=(
            "True when this call stopped with more of the window still on offer. Either `limit` "
            + "filled up, or the internal scan limit ran out while `with_person` or "
            + "`subject_contains` discarded rows. A higher `limit`, a narrower window or a longer "
            + "fragment returns more. False means the window itself ran out, so what came back is "
            + "everything in it, however few rows that is. So an empty list with `capped` false is "
            + "the answer that nothing is on."
        )
    )


async def list_events(
    client: GraphServiceClient,
    *,
    starts_on: date,
    ends_on: date,
    time_zone: str = DEFAULT_TIME_ZONE,
    calendar_ref: str | None = None,
    with_person: str | None = None,
    subject_contains: str | None = None,
    limit: int,
) -> CalendarEvents:
    """The occurrences of one calendar between two dates, and the window they answer."""
    assert 1 <= limit <= MAX_RESULTS, f"limit must be within 1..{MAX_RESULTS}, got {limit}"
    zone = zone_named(time_zone)
    if zone is None:
        raise ToolError(_NOT_A_ZONE)
    if ends_on < starts_on:
        raise ToolError(_ENDS_BEFORE_STARTS)
    if _days_covered(starts_on, ends_on) > MAX_WINDOW_DAYS:
        raise ToolError(_WINDOW_TOO_WIDE)
    named = _calendar_named(calendar_ref)
    opens, closes = window_bounds(starts_on, ends_on, zone=zone)

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
                matches=_matching(with_person=with_person, subject_contains=subject_contains),
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
    """The calendar id the handle addresses, or None for the mailbox's own primary calendar.

    None reaches `calendar_of` as "no calendar named", which is the same value an absent argument
    produces. A refused handle never gets that far.
    """
    if calendar_ref is None:
        return None
    handle = calendar_handle(calendar_ref)
    if handle is None:
        raise ToolError(_NOT_A_CALENDAR_HANDLE)
    return handle.calendar_id


def _days_covered(starts_on: date, ends_on: date) -> int:
    """How many whole days the window holds. Both dates are inside it, so one date in both is one
    day and not zero."""
    return (ends_on - starts_on).days + 1


def _matching(
    *, with_person: str | None, subject_contains: str | None
) -> Callable[[Event], bool] | None:
    """The predicate `collect_pages` applies to every row, or None when the caller named neither.

    Two fragments together narrow rather than widen: a row has to satisfy both. A caller who names
    a person and a subject asked one question about one meeting, not for two lists joined.
    """
    if with_person is None and subject_contains is None:
        return None

    def keeps(event: Event) -> bool:
        if with_person is not None and not person_matches(event, with_person):
            return False
        return subject_contains is None or subject_matches(event, subject_contains)

    return keeps


def _headers() -> HeadersCollection:
    """Built per request: kiota's `RequestConfiguration.headers` defaults to one collection shared
    by every configuration in the process. So a preference added to it leaks onto every Graph call,
    the calendar read of this same tool included. This tool hands the same collection to
    `collect_pages`, whose `PageIterator` otherwise starts from an empty one and fetches page two in
    the other id space."""
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
            date,
            Field(
                description=(
                    "The first day of the window, as YYYY-MM-DD, for example 2026-03-02. The whole "
                    + "of this day is inside the window, counted from its midnight in `time_zone`. "
                    + "For anything about what is coming up, this is today's date."
                )
            ),
        ],
        ends_on: Annotated[
            date,
            Field(
                description=(
                    "The last day of the window, as YYYY-MM-DD, for example 2026-03-08. The whole "
                    + "of this day is inside the window too, so the same date in both arguments "
                    + f"lists that one day. The window covers at most {MAX_WINDOW_DAYS} days, "
                    + "because a calendar view expands every recurring series into one row per "
                    + "occurrence."
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
                    + "UTC, which is the right meetings at the wrong hours for most of the world. "
                    + "A Windows zone name such as `W. Europe Standard Time` is refused here. "
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
                    + "outlook:///calendars/{id}. Omit it for the signed-in user's own primary "
                    + "calendar, which is what almost every question is about. Pass it for a "
                    + "calendar somebody shared, which outlook_list_calendars lists as a row named "
                    + "after its owner."
                ),
            ),
        ] = None,
        with_person: Annotated[
            str | None,
            Field(
                min_length=MIN_FRAGMENT_CHARACTERS,
                description=(
                    "Keep only the events that name this person, as an email address or as part of "
                    + "a name the user gave. It is compared without regard to case, as a "
                    + "substring, against the organizer and every attendee. So `dana` keeps an "
                    + "event Dana organized and one she was invited to, and it also keeps a "
                    + "`Danash` nobody meant. Use the full address when the user gave one. This "
                    + "runs over the rows this call read rather than inside Microsoft's query, so "
                    + "a rare person on a busy calendar can exhaust the call before `limit` fills: "
                    + "`capped` says when that happened."
                ),
            ),
        ] = None,
        subject_contains: Annotated[
            str | None,
            Field(
                min_length=MIN_FRAGMENT_CHARACTERS,
                description=(
                    "Keep only the events whose subject contains this text, compared without "
                    + "regard to case, as a substring. Beside `with_person` it narrows further: a "
                    + "row has to satisfy both. It runs over the rows this call read, on the same "
                    + "terms as `with_person`, so read `capped` before reporting that nothing "
                    + "matched."
                ),
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
            with_person=with_person,
            subject_contains=subject_contains,
            limit=limit,
        )
