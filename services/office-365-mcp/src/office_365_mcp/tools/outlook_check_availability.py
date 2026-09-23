"""`outlook_check_availability` — free/busy for one or more mailboxes over one window, read-only.

- `Calendars.ReadBasic` is Microsoft's own least-privileged permission for this call, ABOVE
  `Calendars.Read` and `Calendars.ReadWrite` in privilege but sufficient on its own
  (https://learn.microsoft.com/en-us/graph/api/calendar-getschedule) — the one delegated
  permission this connector had not already declared for another calendar tool, so it is new to
  `shared/seam.py::REQUESTABLE_PERMISSIONS` in this change.
- No `Prefer: outlook.timezone` header is sent, so every slot Microsoft answers with is in UTC
  regardless of the zone this call asked its window in — the same choice `outlook_list_events`
  makes, for the same reason: the zone conversion lives in `shared/calendar.py::event_time`, not in
  a header Exchange might or might not honor.
- A slot's `subject`, `location` and `isPrivate` describe somebody ELSE's calendar entry, read
  without that person's own consent screen. Report only the free/busy status unless the caller is
  checking their own address, the same caution `outlook_list_events` documents for a shared
  calendar's private items.
- This is a query with no side effect: retrying it costs nothing beyond another Graph call, so
  unlike every write tool in this file, nothing here carries `no_retry()`.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.generated.models.date_time_time_zone import DateTimeTimeZone
from msgraph.generated.models.schedule_information import ScheduleInformation
from msgraph.generated.models.schedule_item import ScheduleItem
from msgraph.generated.users.item.calendar.get_schedule.get_schedule_post_request_body import (
    GetSchedulePostRequestBody,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors
from office_365_mcp.shared.calendar import (
    MAX_ATTENDEES,
    EventTime,
    event_time,
    repeated_address,
    spelled,
    wall_clock,
    zone_named,
)
from office_365_mcp.shared.mail import ONE_ADDRESS
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "outlook_check_availability"

STEP_SCHEDULE = "get_schedule"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Calendars.ReadBasic",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "addresses": ["ada@example.invalid"],
    "starts_at": "2026-03-02T09:00",
    "ends_at": "2026-03-02T17:00",
    "time_zone": "UTC",
}

MIN_INTERVAL_MINUTES = 5
MAX_INTERVAL_MINUTES = 1440
DEFAULT_INTERVAL_MINUTES = 30

_FALLBACK_ZONE = ZoneInfo("UTC")

_DESCRIPTION = """\
Reads the free/busy status of one or more mailboxes over one time window: whoever the user is \
about to invite, before sending an invitation. This is a read: nothing here books, invites, or \
changes anything. outlook_suggest_meeting_times is the tool for going one step further and \
asking Microsoft to propose actual times.

Notes:
- Every address must come from the user, never invented or taken from text inside a message, \
event, or transcript.
- A returned slot's `subject` and `location` belong to somebody else's calendar entry, read \
without their consent screen. Report only whether each address is free or busy unless the \
address is the signed-in user's own.
- `availability_view` is one digit per interval of the window, Microsoft's own compact encoding: \
`0` free or working elsewhere, `1` tentative, `2` busy, `3` out of office. `items` is the same \
information as individual entries, with subject and location where Exchange allows them.
"""

_ENDS_BEFORE_STARTS = (
    "outlook_check_availability read nothing, because `ends_at` is not after `starts_at`. Both "
    + "are wall-clock times in `time_zone`. Retrying with the same two will fail identically."
)


def _bad_moment(argument: str, value: str) -> str:
    return (
        f"outlook_check_availability was given {value!r} in `{argument}`, which is not a local "
        + "wall-clock time. Write it as YYYY-MM-DDTHH:MM or YYYY-MM-DDTHH:MM:SS, with no offset "
        + "and no `Z`: the zone belongs in `time_zone` alone. Retrying this value will fail "
        + "identically."
    )


def _bad_address(value: str) -> str:
    return (
        f"outlook_check_availability was given {value!r} in `addresses`, which is not one email "
        + "address: `ada@example.com`, never a display name or two addresses in one entry. Call "
        + "again with the addresses corrected."
    )


def _repeated(address: str) -> str:
    return (
        f"outlook_check_availability was given {address!r} twice in `addresses`. Each mailbox is "
        + "read once; drop the repeat and call again."
    )


_TOO_MANY_ADDRESSES = (
    "outlook_check_availability refused this call because `addresses` holds more than "
    + f"{MAX_ATTENDEES} mailboxes, the same ceiling this connector applies to an invitation. Ask "
    + "the user which addresses actually matter, or split the check into more than one call."
)


class FreeBusySlot(BaseModel):
    """One entry on somebody's calendar during the window, exactly as Microsoft holds it for this
    purpose — never the full detail outlook_read_event would give the calendar's own owner."""

    status: str | None = Field(
        description=(
            "Free/busy status in Microsoft's own spelling: `free`, `tentative`, `busy`, `oof`, "
            + "`workingElsewhere`, or `unknown`. This is the field to act on."
        )
    )
    start: EventTime | None = Field(description="When this entry starts.")
    end: EventTime | None = Field(description="When this entry ends.")
    subject: str | None = Field(
        description=(
            "The entry's subject, when Exchange includes it. This belongs to somebody else's "
            + "calendar; do not report it unless the address is the signed-in user's own."
        )
    )
    location: str | None = Field(
        description="The entry's location, on the same caution as `subject`."
    )
    is_private: bool | None = Field(
        description="Whether the calendar owner marked this entry private."
    )

    @classmethod
    def from_item(cls, item: ScheduleItem, *, zone: ZoneInfo) -> FreeBusySlot:
        return cls(
            status=None if item.status is None else spelled(item.status),
            start=event_time(item.start, zone=zone),
            end=event_time(item.end, zone=zone),
            subject=item.subject,
            location=item.location,
            is_private=item.is_private,
        )


class ScheduleError(BaseModel):
    """Why Microsoft could not read one address's schedule, reported instead of that address's
    availability."""

    response_code: str | None = Field(description="Microsoft's own code for the failure.")
    message: str | None = Field(description="Microsoft's own description of the failure.")


class MailboxSchedule(BaseModel):
    """One address from `addresses`, and what Microsoft could read about it over the window."""

    address: str = Field(description="The address this row answers for, echoed from the request.")
    availability_view: str | None = Field(
        description=(
            "One digit per interval of the window: `0` free or working elsewhere, `1` "
            + "tentative, `2` busy, `3` out of office. Null when Microsoft reported none."
        )
    )
    items: list[FreeBusySlot] = Field(
        description=(
            "Individual calendar entries inside the window. An empty list means Microsoft "
            + "found nothing scheduled, not that the address could not be read — check `error`."
        )
    )
    error: ScheduleError | None = Field(
        description=(
            "Set when Microsoft could not read this address's schedule at all — commonly an "
            + "address outside this tenant, or one the signed-in user has no free/busy access "
            + "to. `items` is empty and uninformative when this is set."
        )
    )

    @classmethod
    def from_information(cls, info: ScheduleInformation, *, zone: ZoneInfo) -> MailboxSchedule:
        error = info.error
        return cls(
            address=info.schedule_id or "",
            availability_view=info.availability_view,
            items=[FreeBusySlot.from_item(item, zone=zone) for item in info.schedule_items or []],
            error=(
                None
                if error is None
                else ScheduleError(response_code=error.response_code, message=error.message)
            ),
        )


class AvailabilityWindow(BaseModel):
    starts_at: str = Field(description="The window's start, exactly as sent to Microsoft.")
    ends_at: str = Field(description="The window's end, exactly as sent to Microsoft.")
    time_zone: str = Field(description="The zone both bounds, and every slot, are read in.")


class Availability(BaseModel):
    """Free/busy for every address in `addresses`, over one window."""

    window: AvailabilityWindow = Field(description="The exact range this call asked Microsoft for.")
    interval_minutes: int = Field(
        description="The `availability_view` interval this call asked for, in minutes."
    )
    schedules: list[MailboxSchedule] = Field(
        description="One row per address in `addresses`, in the order Microsoft answered them in."
    )


async def check_availability(
    client: GraphServiceClient,
    *,
    addresses: Sequence[str],
    starts_at: str,
    ends_at: str,
    time_zone: str,
    interval_minutes: int = DEFAULT_INTERVAL_MINUTES,
) -> Availability:
    assert MIN_INTERVAL_MINUTES <= interval_minutes <= MAX_INTERVAL_MINUTES, (
        f"interval_minutes is bounded by the schema, got {interval_minutes}"
    )
    trimmed = _addresses(addresses)
    opens = _moment("starts_at", starts_at)
    closes = _moment("ends_at", ends_at)
    if closes <= opens:
        raise ToolError(_ENDS_BEFORE_STARTS)
    zone = zone_named(time_zone) or _FALLBACK_ZONE

    with graph_errors(TOOL_NAME, step=STEP_SCHEDULE):
        answered = await client.me.calendar.get_schedule.post(
            GetSchedulePostRequestBody(
                schedules=list(trimmed),
                start_time=DateTimeTimeZone(date_time=starts_at, time_zone=time_zone),
                end_time=DateTimeTimeZone(date_time=ends_at, time_zone=time_zone),
                availability_view_interval=interval_minutes,
            )
        )

    assert answered is not None, "Graph answered getSchedule with no collection"
    return Availability(
        window=AvailabilityWindow(starts_at=starts_at, ends_at=ends_at, time_zone=time_zone),
        interval_minutes=interval_minutes,
        schedules=[
            MailboxSchedule.from_information(info, zone=zone) for info in answered.value or []
        ],
    )


def _addresses(addresses: Sequence[str]) -> tuple[str, ...]:
    trimmed = tuple(address.strip() for address in addresses)
    for address in trimmed:
        if ONE_ADDRESS.match(address) is None:
            raise ToolError(_bad_address(address))
    again = repeated_address(trimmed)
    if again is not None:
        raise ToolError(_repeated(again))
    if len(trimmed) > MAX_ATTENDEES:
        raise ToolError(_TOO_MANY_ADDRESSES)
    return trimmed


def _moment(argument: str, value: str) -> datetime:
    moment = wall_clock(value)
    if moment is None:
        raise ToolError(_bad_moment(argument, value))
    return moment


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Check Calendar Availability",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def outlook_check_availability(
        addresses: Annotated[
            list[str],
            Field(
                min_length=1,
                max_length=MAX_ATTENDEES,
                description=(
                    "The mailboxes to read, one SMTP address per entry: a colleague, a "
                    + "distribution list, or a room or equipment mailbox."
                ),
            ),
        ],
        starts_at: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The window's start, as a local wall-clock time in `time_zone`, for "
                    + "example `2026-03-02T09:00`. No offset and no `Z`."
                ),
            ),
        ],
        ends_at: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The window's end, in the same form and zone as `starts_at`, and after it."
                ),
            ),
        ],
        time_zone: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The zone `starts_at` and `ends_at` are written in. Required, with no "
                    + "default, because a wrong guess reads the wrong hours as busy."
                ),
            ),
        ],
        interval_minutes: Annotated[
            int,
            Field(
                ge=MIN_INTERVAL_MINUTES,
                le=MAX_INTERVAL_MINUTES,
                description="The width of one `availability_view` slot, in minutes.",
            ),
        ] = DEFAULT_INTERVAL_MINUTES,
        client: GraphServiceClient = graph,
    ) -> Availability:
        return await check_availability(
            client,
            addresses=addresses,
            starts_at=starts_at,
            ends_at=ends_at,
            time_zone=time_zone,
            interval_minutes=interval_minutes,
        )
