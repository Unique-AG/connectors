"""`outlook_list_calendars` — every calendar this mailbox reaches, and the handle for each one.

- A delegated calendar is a plain row of `GET /me/calendars`, named after its owner, with `canEdit`
  true: https://learn.microsoft.com/en-us/graph/outlook-create-event-in-shared-delegated-calendar
- `calendar` in v1.0 publishes no sharing flag, so `is_mine` is this connector's own comparison of
  `owner` against the `/me` read's `mail` and `userPrincipalName`:
  https://learn.microsoft.com/en-us/graph/api/resources/calendar
- Microsoft names `Calendars.Read.Shared` as the least privileged permission for this call, so a
  tenant that consents only to `Calendars.Read` gets a short listing rather than a refusal.
"""

from collections.abc import Mapping

import httpx
from fastmcp import FastMCP
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.users.item.calendars.calendars_request_builder import (
    CalendarsRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import collect_pages, graph_errors, graph_step
from office_365_mcp.shared import identity
from office_365_mcp.shared.calendar import CALENDAR_FIELDS, CalendarSummary
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "outlook_list_calendars"

STEP = "calendars"

GRAPH_PERMISSIONS: tuple[str, ...] = (
    "Calendars.Read",
    "Calendars.Read.Shared",
    identity.GRAPH_PERMISSION,
)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {}

MAX_CALENDARS = 200

# Bound rather than aliased with `type`. This name serves as the query parameters' constructor and
# also as `RequestConfiguration`'s type argument, and a `TypeAliasType` is not callable.
_CalendarsQuery = CalendarsRequestBuilder.CalendarsRequestBuilderGetQueryParameters

_DESCRIPTION = """\
Lists every calendar the signed-in user's mailbox reaches — their own, and any calendar another \
person delegated or shared with them — before naming a specific calendar in another tool. \
outlook_list_events lists what is on a calendar; this tool lists the calendars themselves and \
returns no events.

Notes:
- Pass a row's `uri` as `calendar_ref` to outlook_list_events, and to \
outlook_create_event_on_behalf where this deployment runs it.
- A delegated calendar is named after its owner, not the signed-in user: check `is_mine` and \
`can_edit` before treating a row as the user's own or as writable.
- On a calendar where `can_edit` and `can_view_private_items` are both false, rows return \
stripped — `subject` holds the display form of `show_as`, `preview` is empty, and \
`attendee_count` is 0 — report only the time and note the rest is unreadable.
"""


class Calendars(BaseModel):
    """Every calendar of one mailbox, own and delegated, in the order Microsoft returned them."""

    calendars: list[CalendarSummary] = Field(
        description=(
            "The calendars this mailbox reaches, in Graph's own order — not a ranking. Read "
            + "`is_default` for the primary calendar rather than assuming it comes first. Empty "
            + "means Graph reported no calendar at all, which does not happen for a licensed "
            + "mailbox and signals an unconsented permission instead."
        )
    )
    capped: bool = Field(
        description=(
            f"True when this listing stopped at {MAX_CALENDARS} calendars with more still on "
            + "offer, so a calendar the user named may be missing from `calendars` rather than "
            + "absent from the mailbox. False whenever the listing ran out on its own, however "
            + "few calendars it held."
        )
    )


async def list_calendars(client: GraphServiceClient) -> Calendars:
    with graph_errors(TOOL_NAME):
        user = await identity.signed_in_user(client)
        with graph_step(STEP):
            # Container types such as `calendar` support no immutable id, so no `Prefer` header
            # travels here: https://learn.microsoft.com/en-us/graph/outlook-immutable-id
            first_page = await client.me.calendars.get(
                request_configuration=RequestConfiguration[_CalendarsQuery](
                    query_parameters=_CalendarsQuery(
                        select=list(CALENDAR_FIELDS),
                        top=MAX_CALENDARS,
                    )
                )
            )
            assert first_page is not None, "Graph answered a calendar listing with no collection"
            collected = await collect_pages(first_page, client, limit=MAX_CALENDARS)

    return Calendars(
        calendars=[
            CalendarSummary.from_calendar(calendar, signed_in=user) for calendar in collected.items
        ],
        capped=collected.capped,
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="List Calendars",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def outlook_list_calendars(client: GraphServiceClient = graph) -> Calendars:
        return await list_calendars(client)
