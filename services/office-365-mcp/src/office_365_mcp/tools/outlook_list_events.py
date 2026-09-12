"""`outlook_list_events` — one calendar's occurrences over a window, never a recurrence rule.

`GET /me/events` returns series masters, not occurrences: "To get expanded event instances, you can
get the calendar view" (https://learn.microsoft.com/en-us/graph/api/user-list-events). So this tool
reads `calendarView`, whose required `startDateTime`/`endDateTime` carry their own offset and
"aren't impacted by the value of the Prefer: outlook.timezone header"; with no offset they are UTC
(https://learn.microsoft.com/en-us/graph/api/calendar-list-calendarview). That header is not sent,
so rows arrive in UTC and `zoneinfo` converts them. Graph puts no calendar id on a `calendarView`
row, so the calendar is read first and supplies half of every handle minted here.

`calendarView` does accept a `$filter` on a FLAT property, against what its own page suggests by
naming only "some of" the OData parameters and no filterable property at all
(https://learn.microsoft.com/en-us/graph/api/calendar-list-calendarview). `cancelled` and
`subject_contains` are therefore server-side, both live-verified. A NESTED path is the exception:
`responseStatus/response` answers correctly alone and returns 500 as soon as it is conjoined with
another property, so `owner_response` stays a predicate over the rows. There is no attendee filter
at any spelling, which is why no argument here asks about one.
"""

from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

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
    spelled,
    window_bounds,
    zone_named,
)
from office_365_mcp.shared.handles import calendar_handle
from office_365_mcp.shared.odata import odata_literal
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller
from office_365_mcp.shared.window import closes_at, opens_at, runs_backwards

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
List what is on ONE calendar between two dates, earliest start first. This reads Microsoft's \
calendar view, so a recurring series arrives as one row per occurrence inside the window: a weekly \
stand-up over three weeks is three rows, each with its own date and its own handle. `starts_on` \
and `ends_on` each take a date or a moment: a date covers that whole day, a moment opens or closes \
partway through one, and a moment with no offset is read in `time_zone`. Each row states its time \
three \
ways: Graph's own wall-clock text, Graph's own zone name, and `iso`, the same instant in \
`time_zone`. `time_zone` defaults to UTC and takes an IANA name such as `Europe/Zurich`. A wrong \
zone does not fail here. It answers the right meetings at the wrong hours. So pass the user's own \
zone for any question about a time of day, and quote `iso` rather than `local`, the wall-clock \
text, except on a row whose `all_day` is true, where `iso` is a UTC midnight moved into \
`time_zone`, so in a zone west of UTC it names the day before. Take the date of an all-day row \
from `local`. \
Without `calendar_ref` this lists the signed-in user's own primary calendar. Pass `calendar_ref`, \
the `uri` of an outlook_list_calendars row, for a calendar somebody shared. For "my next pricing \
review", pass `subject_contains="pricing"` and set `starts_on` to today: the rows are in start \
order, so the earliest match is the first one. If nothing matched and `capped` is false, that \
window holds no such row, so widen `ends_on` and ask again. This tool never picks a row for the \
user. Report the matches and \
let the user choose which one is meant. `owner_response` is the answer of the person who OWNS the \
calendar, so on a shared calendar it is that person's answer and never the signed-in user's. On a \
calendar the user does not own, a row whose `sensitivity` is `private` or `confidential` is the \
owner's private business: say that something is on at that time, and do not relay its subject or \
its preview. One calendar whose `can_edit` and `can_view_private_items` were both false returned \
stripped rows: `subject` holding the display form of its own `show_as` (`Tentative` for \
`tentative`), an empty `preview` and `location`, `attendee_count` 0, and `organizer` naming the \
signed-in user on every row, all with `sensitivity` still `normal`. The two flags alone do not \
say a row was stripped. On a calendar whose `can_edit` and `can_view_private_items` are both \
false, a row of that shape has no readable subject, preview, location or attendee count: report \
its time, its `show_as` and its `cancelled` flag, and say the rest was not readable. A canceled \
event stays in a calendar until somebody \
removes it, so this tool lists those rows with `cancelled` true rather than hiding them. Read that \
field before telling anybody a meeting is on, or pass `cancelled=false` to drop them — worth doing \
over a wide window, where cancelled rows otherwise spend `limit`. Pass \
`owner_response="accepted"` for "the meetings I said yes to" and `"notResponded"` for the \
invitations still owed an answer. Pass a row's `uri` to outlook_read_event for the full body and \
the attendee list.\
"""

_ENDS_BEFORE_STARTS = (
    "outlook_list_events read nothing, because `ends_on` falls before `starts_on` and no calendar "
    + "holds a window that runs backwards. Both arguments include what they name — a date covers "
    + "its whole day — so one date in both lists that single day. Put the earlier bound in "
    + "`starts_on` and the later one in `ends_on`, then call again. Retrying with the same two "
    + "will fail identically."
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
            + "when nothing in it matched the narrowing arguments this call passed. Read `capped` "
            + "before reporting an empty list as nothing being on."
        )
    )
    capped: bool = Field(
        description=(
            "True when this call stopped with more of the window still on offer. Either `limit` "
            + "filled up, or the internal scan ran out while `owner_response` discarded rows. "
            + "`cancelled` and `subject_contains` cannot cause it: Microsoft applies those two "
            + "inside the query, so a row they exclude never reaches this call and never spends "
            + "`limit`. A higher `limit` or a narrower window returns more. False means the "
            + "window itself ran out, so what came back is everything in it that matched, "
            + "however few rows that is. So an empty list with `capped` false is the answer that "
            + "nothing is on."
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
    if _days_covered(starts_on, ends_on, zone=zone) > MAX_WINDOW_DAYS:
        raise ToolError(_WINDOW_TOO_WIDE)
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


def _days_covered(starts_on: date | datetime, ends_on: date | datetime, *, zone: ZoneInfo) -> int:
    """How many days the window spans, rounded up, for the width guard alone.

    Measured between the resolved instants because Python refuses to subtract a date from a moment,
    and rounded UP so the 1st to the 1st keeps the one inclusive day it has always counted as.
    """
    span = closes_at(ends_on, zone=zone) - opens_at(starts_on, zone=zone)
    return -(-span // timedelta(days=1))


def _filter_for(*, subject_contains: str | None, cancelled: bool | None) -> str | None:
    """The `$filter` this call sends, or None when neither server-side narrowing was asked for.

    Both forms are live-verified against `calendarView` beside `$orderby=start/dateTime`, each sent
    once with a value present in the window and once with one that cannot match — which is what
    separates a filter Graph evaluates from one it drops in silence. `owner_response` is absent on
    purpose: see `_owner_answered`.
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
    found a nested path 500s as soon as it is conjoined with any other property — in both orders
    and parenthesised — so sending it beside `cancelled` or `subject_contains` would crash the very
    combination a caller most wants. Compared through `spelled`, which is how
    `EventSummary.owner_response` is built, so the argument and the field cannot drift apart.
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
                    "Where the window opens, inclusive. Two shapes: a date, `2026-03-02`, which "
                    + "opens at that day's midnight in `time_zone` and covers the whole day; or a "
                    + 'moment, `2026-03-02T13:00:00`, to open partway through one — for "what is '
                    + 'on this afternoon". A moment with no offset is read in `time_zone`, not in '
                    + "UTC, because that argument is what says which zone the caller means; a "
                    + "moment carrying its own offset keeps it. For anything about what is coming "
                    + "up, this is today."
                )
            ),
        ],
        ends_on: Annotated[
            date | datetime,
            Field(
                description=(
                    "Where the window closes, inclusive, in the same two shapes `starts_on` "
                    + "takes. A date covers the whole of that day, so the same date in both "
                    + "arguments lists that one day; a moment closes at the second it names, and "
                    + "an occurrence starting exactly then belongs to the next window. The window "
                    + f"covers at most {MAX_WINDOW_DAYS} days, because a calendar view expands "
                    + "every recurring series into one row per occurrence."
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
        subject_contains: Annotated[
            str | None,
            Field(
                min_length=MIN_FRAGMENT_CHARACTERS,
                description=(
                    "Keep only the events whose subject contains this text, compared without "
                    + "regard to case, as a substring. Microsoft applies it inside the query "
                    + "rather than this connector applying it to the rows that came back, so it "
                    + "narrows the window itself: a fragment matching two meetings of a busy month "
                    + "returns those two, and cannot exhaust the call before `limit` fills. The "
                    + "comparison ignores case, which is Microsoft's own behaviour here and was "
                    + "verified against the live service. It is "
                    + "a substring and not a word search, so `pricing` keeps `Quarterly pricing "
                    + "review` and also a `Repricing` nobody meant, and a two-word fragment misses "
                    + "any subject that spells those words apart. Beside `cancelled` or "
                    + "`owner_response` it narrows further: a row has to satisfy all of them."
                ),
            ),
        ] = None,
        cancelled: Annotated[
            bool | None,
            Field(
                description=(
                    "Narrow by whether the occurrence was called off. Omitting this argument, "
                    + "which is the usual call, lists BOTH — a cancelled event stays in the "
                    + "calendar until somebody removes it, and hiding it by default would answer "
                    + '"nothing is on" for a day that had a meeting until this morning. `false` '
                    + 'DROPS the cancelled rows, which is what "what is actually happening on '
                    + "Thursday\" asks for and is the argument's main use: over a wide window the "
                    + "earliest rows can be all cancelled clutter, and `limit` is spent on them. "
                    + '`true` returns only the cancelled ones, for "did anything get called '
                    + 'off". Microsoft applies this inside the query, so a dropped row never '
                    + "reaches this call and never spends `limit`. The two sides partition the "
                    + "window exactly: every occurrence Microsoft returns states this flag, so no "
                    + "row falls outside both."
                )
            ),
        ] = None,
        owner_response: Annotated[
            OwnerResponse | None,
            Field(
                description=(
                    "Keep only the events the calendar's OWNER answered this way: `accepted`, "
                    + "`tentativelyAccepted`, `declined` or `notResponded`. This is the field "
                    + 'that answers "only my accepted meetings" — `show_as` does not, because a '
                    + "busy block is not an acceptance. Without `calendar_ref` the owner is the "
                    + 'signed-in user, which is most calls, so `accepted` reads as "meetings I '
                    + 'said yes to" and `notResponded` as "invitations I still owe an answer '
                    + "to\". On a calendar somebody shared, it is THAT person's answer and never "
                    + "the signed-in user's. Unlike `cancelled` and `subject_contains`, this "
                    + "one is applied to the rows this call read rather than inside Microsoft's "
                    + "query, so on a busy calendar a rare answer can exhaust the call before "
                    + "`limit` fills: `capped` says when that happened. A row Microsoft recorded "
                    + "none of these four answers on is dropped. Use "
                    + '`owner_is_organizer` on the rows for "meetings the owner called", which '
                    + "is a different question and has no value here."
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
