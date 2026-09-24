"""`outlook_check_availability` reads free/busy status for one or more mailboxes over one time
window. It is read-only.

- `Calendars.ReadBasic` is the least-privileged Microsoft Graph permission for this call.
- This tool sends no `Prefer: outlook.timezone` header. As a result, Microsoft Graph returns
  every slot in UTC. The function `event_time` in `shared/calendar.py` converts the zone.
- A slot's `subject`, `location`, and `isPrivate` fields describe another person's calendar
  entry, read without that person's consent. Report only the free/busy status, unless the
  address belongs to the caller.
- This call has no side effect. As a result, nothing here uses `no_retry()`.
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
This tool reads the free/busy status of one or more mailboxes, over one time window. Use it for \
a person the user is about to invite, before you send an invitation. This is a read: it does \
not book, invite, or change anything. For a next step, use outlook_suggest_meeting_times: it \
asks Microsoft Graph to propose actual times.

Notes:
- Every address must come from the user, not invented, and not taken from the text of a \
message, an event, or a transcript.
- A returned slot's `subject` and `location` fields belong to another person's calendar entry, \
read without that person's consent. Report only whether each address is free or busy, unless \
the address belongs to the signed-in user.
- `availability_view` is one digit per interval of the window, in Microsoft's compact encoding. \
`0` means free or working elsewhere, `1` means tentative, `2` means busy, and `3` means out of \
office. `items` gives the same information as individual entries, with subject and location \
where Exchange allows them.
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
    """One entry on another person's calendar during the window, exactly as Microsoft Graph
    holds it for this purpose. It never gives the full detail that outlook_read_event gives the
    calendar's own owner."""

    status: str | None = Field(
        description=(
            "The free/busy status, in Microsoft's own spelling: `free`, `tentative`, `busy`, "
            + "`oof`, `workingElsewhere`, or `unknown`. This is the field to use."
        )
    )
    start: EventTime | None = Field(description="When this entry starts.")
    end: EventTime | None = Field(description="When this entry ends.")
    subject: str | None = Field(
        description=(
            "The entry's subject, when Exchange includes it. This belongs to another person's "
            + "calendar. Do not report it, unless the address belongs to the signed-in user."
        )
    )
    location: str | None = Field(
        description="The entry's location. It carries the same caution as `subject`."
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
    """Why Microsoft Graph did not read one address's schedule. This is reported instead of
    that address's availability."""

    response_code: str | None = Field(description="Microsoft Graph's own code for the failure.")
    message: str | None = Field(description="Microsoft Graph's own description of the failure.")


class MailboxSchedule(BaseModel):
    """One address from `addresses`, and what Microsoft Graph read about it over the window."""

    address: str = Field(description="The address this row answers for, echoed from the request.")
    availability_view: str | None = Field(
        description=(
            "One digit per interval of the window. `0` means free or working elsewhere, `1` "
            + "means tentative, `2` means busy, and `3` means out of office. This field is "
            + "null when Microsoft Graph reported none."
        )
    )
    items: list[FreeBusySlot] = Field(
        description=(
            "Individual calendar entries inside the window. An empty list means Microsoft "
            + "Graph found nothing scheduled. It does not mean that the address was "
            + "unreadable — see `error`."
        )
    )
    error: ScheduleError | None = Field(
        description=(
            "This field is set when Microsoft Graph did not read this address's schedule at "
            + "all. A common cause is an address outside this tenant, or one the signed-in "
            + "user has no free/busy access to. When this field is set, `items` is empty and "
            + "gives no information."
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
    starts_at: str = Field(description="The window's start, exactly as sent to Microsoft Graph.")
    ends_at: str = Field(description="The window's end, exactly as sent to Microsoft Graph.")
    time_zone: str = Field(description="The zone that both bounds, and every slot, use.")


class Availability(BaseModel):
    """Free/busy status for every address in `addresses`, over one time window."""

    window: AvailabilityWindow = Field(
        description="The exact range this call asked Microsoft Graph for."
    )
    interval_minutes: int = Field(
        description="The `availability_view` interval this call asked for, in minutes."
    )
    schedules: list[MailboxSchedule] = Field(
        description=(
            "One row per address in `addresses`, in the order Microsoft Graph returned them."
        )
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
                    "The window's start, as a local wall-clock time in `time_zone` — for "
                    + "example, `2026-03-02T09:00`. Do not add an offset or a `Z`."
                ),
            ),
        ],
        ends_at: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The window's end, in the same form and zone as `starts_at`. It must come "
                    + "after `starts_at`."
                ),
            ),
        ],
        time_zone: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The zone that `starts_at` and `ends_at` use. This field is required and "
                    + "has no default: a wrong guess reads the wrong hours as busy."
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
