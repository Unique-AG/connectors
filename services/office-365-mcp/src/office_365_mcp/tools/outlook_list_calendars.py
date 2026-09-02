"""`outlook_list_calendars` — every calendar this mailbox reaches, and the handle for each one.

**One request answers "whose calendars can I see", and Graph offers no narrower shape.** Microsoft:
"Get all the user's calendars (`/calendars` navigation property), get the calendars from the
default calendar group or from a specific calendar group"
(https://learn.microsoft.com/en-us/graph/api/user-list-calendars). This tool asks for all of them.
The calendar-group routes split the same set by a folder the user arranged, which answers a
question nobody here asks.

**A calendar another person delegated is a plain row of this listing, named after that person.**
Microsoft's walkthrough signs in as Adele, who holds Alex' delegated calendar, calls
`GET /me/calendars`, and reports that the response "includes the response code HTTP 200, Adele's
own primary calendar, and a copy of the calendar delegated by Alex in Adele's mailbox", where
"**canEdit** is true since as delegate, Adele has write access to non-private events in the
delegated calendar" and "**owner** is `Alex Wilber` indicating it is Alex' calendar"
(https://learn.microsoft.com/en-us/graph/outlook-create-event-in-shared-delegated-calendar). The
row's `name` in that sample is the string `Alex Wilber`. So the name of a delegated calendar is a
person, and the primary calendar of the signed-in user is called `Calendar`.

**Nothing in the row says "this one is shared", so this connector derives it.** `calendar` in v1.0
publishes no `isSharedWithMe` property (https://learn.microsoft.com/en-us/graph/api/resources/
calendar). `owner` is the only property that separates a delegated row from an own one, and
`canEdit` is true on both. That is why this tool reads `GET /me` first: `is_mine` is the owner
address compared against the signed-in user's `mail` and `userPrincipalName`, and a comparison
needs both of those values. Without the `/me` read the answer carries no `is_mine` at all.

**`Calendars.Read` alone hides the rows that matter here.** Microsoft's delegated walkthrough says
of this exact call: "Use the least privileged delegated permission, `Calendars.Read.Shared`". So
this tool declares that permission beside `Calendars.Read`, and a tenant that consents to only the
first one gets an inventory of the user's own calendars and no delegated one. Microsoft's own least
privileged permission for the route is `Calendars.ReadBasic`. This tool does not use it, because
every other calendar tool of this connector needs `Calendars.Read`, and a second permission on the
consent screen that buys one listing is a worse trade than a shared one.
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

# `Calendars.Read` covers the user's own calendars. `Calendars.Read.Shared` is what Microsoft names
# as the least privileged permission for reading a delegated calendar, so without it the listing is
# short rather than refused. `User.Read` covers the `/me` read that `is_mine` is decided against.
GRAPH_PERMISSIONS: tuple[str, ...] = (
    "Calendars.Read",
    "Calendars.Read.Shared",
    identity.GRAPH_PERMISSION,
)

# No arguments at all is the only call this tool has. It reaches Graph without a handle from any
# earlier response, which is what makes it the entry point of the calendar surface.
GRAPH_CALL_EXAMPLE: Mapping[str, object] = {}

# A mailbox with more calendars than this is not one a model reads its way through. The walk stops
# and says so, rather than spending pages on a list nobody reads to the end.
MAX_CALENDARS = 200

# Bound rather than aliased with `type`. This name serves as the query parameters' constructor and
# also as `RequestConfiguration`'s type argument, and a `TypeAliasType` is not callable.
_CalendarsQuery = CalendarsRequestBuilder.CalendarsRequestBuilderGetQueryParameters

_DESCRIPTION = """\
List every calendar in the signed-in user's mailbox: their own, and every calendar another person \
shared or delegated to them. This is the inventory to read before naming anybody's calendar, \
because the `uri` of a row here is what outlook_list_events and outlook_create_event_on_behalf \
take as `calendar_ref`, and nothing else names a calendar. A calendar another person delegated \
arrives as a row named after THAT PERSON, with `is_mine` false and `can_edit` true, so a row \
called `Alex Wilber` is Alex's own primary calendar as this mailbox sees it. `is_mine` is this \
connector's own comparison of the owner's address against the signed-in user's two addresses, \
because Microsoft publishes no sharing flag on a calendar in v1.0: null there means unknown and \
never false. Read `can_edit` before offering to write to a calendar, because false means a create \
on it fails whatever else is right about it. Read `can_view_private_items` as well: false means an \
item the owner marked private arrives with its times and no subject and no preview, so an answer \
drawn from that calendar is thinner than it looks rather than complete. This tool returns no \
events. Use outlook_list_events for what sits on a calendar.\
"""


class Calendars(BaseModel):
    """Every calendar of one mailbox, own and delegated, in the order Microsoft returned them."""

    calendars: list[CalendarSummary] = Field(
        description=(
            "The calendars this mailbox reaches, in Graph's own order. That order is not a "
            + "ranking, and the primary calendar is not promised to be first: read `is_default` "
            + "instead. Empty means Graph reported no calendar at all, which does not happen for "
            + "a licensed mailbox and points at a permission the tenant left unconsented."
        )
    )
    capped: bool = Field(
        description=(
            f"True when this listing stopped at {MAX_CALENDARS} calendars with Graph still "
            + "offering more. So a calendar the user named is possibly missing from `calendars` "
            + "rather than absent from the mailbox. False whenever the listing ran out on its "
            + "own, however few calendars it held."
        )
    )


async def list_calendars(client: GraphServiceClient) -> Calendars:
    """Every calendar of the mailbox, each one judged against the signed-in user.

    The `/me` read comes first and its failure ends the call: an answer whose every `is_mine` is
    null says a delegated calendar and an own one are indistinguishable, which is the one question
    this tool exists to answer.
    """
    with graph_errors(TOOL_NAME):
        user = await identity.signed_in_user(client)
        with graph_step(STEP):
            # No request header travels with this call. Microsoft documents that container types
            # such as `calendar` do not support `Prefer: IdType="ImmutableId"`, and that their
            # regular ids "were already constant"
            # (https://learn.microsoft.com/en-us/graph/outlook-immutable-id).
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
