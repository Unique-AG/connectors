from collections.abc import Mapping
from typing import Self

import httpx
from fastmcp import FastMCP
from msgraph.generated.models.calendar import Calendar
from msgraph.generated.models.calendar_group import CalendarGroup
from msgraph.generated.models.user import User
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import (
    MAX_SCANNED_ITEMS,
    CollectedItems,
    collect_pages,
    graph_errors,
    graph_step,
)
from office_365_mcp.shared import identity
from office_365_mcp.shared.calendar import CalendarSummary
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "outlook_list_calendar_groups"

STEP_GROUPS = "calendar_groups"

STEP_CALENDARS = "calendars"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Calendars.ReadBasic", identity.GRAPH_PERMISSION)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {}

_DESCRIPTION = """\
Lists the calendar groups of the signed-in user, with the calendars in each group. \
outlook_list_calendars lists every calendar without the groups. This tool shows how the groups \
hold the calendars, and which of them the user owns.

Notes:
- Pass the `uri` of a calendar as `calendar_ref` to outlook_list_events.
"""


class CalendarGroupSummary(BaseModel):
    name: str | None = Field(
        description=(
            "The name of the calendar group, or null if Graph returned none. The `calendars` "
            + "list holds the calendars in this group."
        )
    )
    calendars: list[CalendarSummary] = Field(
        description=(
            "The calendars in this group, in the order that Graph returns them. An empty list "
            + "means that the group holds no calendar."
        )
    )

    @classmethod
    def from_group(
        cls, group: CalendarGroup, *, calendars: list[Calendar], signed_in: User
    ) -> Self:
        return cls(
            name=group.name,
            calendars=[
                CalendarSummary.from_calendar(calendar, signed_in=signed_in)
                for calendar in calendars
            ],
        )


class CalendarGroups(BaseModel):
    groups: list[CalendarGroupSummary] = Field(
        description=(
            "These are the calendar groups of the mailbox, in the order that Graph returns "
            + "them. An empty list means that Graph reported no calendar group at all."
        )
    )
    capped: bool = Field(
        description=(
            "True means that the listing stopped early, with more groups or more calendars still "
            + "available. A calendar that the user named can be missing. False means that the "
            + "listing read every group and every calendar."
        )
    )


async def list_calendar_groups(client: GraphServiceClient) -> CalendarGroups:
    with graph_errors(TOOL_NAME):
        user = await identity.signed_in_user(client)
        with graph_step(STEP_GROUPS):
            first_page = await client.me.calendar_groups.get()
            assert first_page is not None, (
                "Graph answered a calendar group listing with no collection"
            )
            groups = await collect_pages(first_page, client, limit=MAX_SCANNED_ITEMS)
        summaries: list[CalendarGroupSummary] = []
        capped = groups.capped
        for group in groups.items:
            calendars = await _calendars_in(client, group)
            capped = capped or calendars.capped
            summaries.append(
                CalendarGroupSummary.from_group(group, calendars=calendars.items, signed_in=user)
            )

    return CalendarGroups(groups=summaries, capped=capped)


async def _calendars_in(
    client: GraphServiceClient, group: CalendarGroup
) -> CollectedItems[Calendar]:
    assert group.id is not None, "Graph answered a calendar group listing with a group with no id"
    with graph_step(STEP_CALENDARS):
        first_page = await client.me.calendar_groups.by_calendar_group_id(group.id).calendars.get()
        assert first_page is not None, "Graph answered a group calendar listing with no collection"
        return await collect_pages(first_page, client, limit=MAX_SCANNED_ITEMS)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="List Calendar Groups",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def outlook_list_calendar_groups(client: GraphServiceClient = graph) -> CalendarGroups:
        return await list_calendar_groups(client)
