from collections.abc import Mapping
from typing import Annotated, Self, cast

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.generated.models.calendar_permission import CalendarPermission
from msgraph.generated.models.calendar_role_type import CalendarRoleType
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import MAX_SCANNED_ITEMS, collect_pages, graph_errors
from office_365_mcp.shared.handles import CalendarPermissionHandle, calendar_handle
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "outlook_list_calendar_shares"

STEP = "calendar_permissions"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Calendars.ReadBasic",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "calendar_ref": "outlook:///calendars/AAMkSYNTHETIC-cal-0001%3D",
}

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return the calendar that this call named, so this tool listed no "
    + "share. The handle is well formed. A person probably deleted the calendar, or its owner "
    + "stopped sharing it. Call outlook_list_calendars again. Then use the `uri` that it reports "
    + "now. If you call this tool again with the same arguments, the call will fail the same way."
)

_DESCRIPTION = """\
Lists the people who can see one calendar of the signed-in user, and the role of each person. \
outlook_list_calendars lists the calendars and their handles. outlook_share_calendar shares a \
calendar with a person, and outlook_unshare_calendar stops a share.

Notes:
- Microsoft lists the shares only for a calendar that the signed-in user owns. For a calendar \
that another person shares with the user, Microsoft returns an empty list.
- The row named `My Organization` sets what all people in the organization of the owner can \
see. It has no address, and Microsoft does not let anybody remove it.
- A delegate also receives meeting requests for the owner and can answer them. The role of a \
delegate row starts with `delegate`.
"""

_NOT_A_CALENDAR_HANDLE = (
    "outlook_list_calendar_shares takes a calendar handle in `calendar_ref`: "
    + "outlook:///calendars/{id}, exactly as outlook_list_calendars reported it in `uri`. "
    + "A calendar name is not a handle. An event handle is not a calendar handle. This tool read "
    + "nothing. If you call this tool again with this value, the call will fail the same way."
)


class CalendarShare(BaseModel):
    uri: str = Field(
        description=(
            "The handle of this share. Pass it as `share_ref` to outlook_unshare_calendar to stop "
            + "the share. The shape is outlook:///calendarpermissions/{calendar_id}/{id}."
        )
    )
    name: str | None = Field(
        description=(
            "The display name of the person, as Microsoft 365 reports it. The organization row "
            + "has the name `My Organization`. The value is null when Microsoft 365 reports no "
            + "name."
        )
    )
    address: str | None = Field(
        description=(
            "The SMTP address of the person who has this share. The value is null when "
            + "Microsoft 365 reports no address."
        )
    )
    role: str | None = Field(
        description=(
            "What this person can do with the calendar, as Microsoft names it: `freeBusyRead`, "
            + "`limitedRead`, `read`, `write`, `delegateWithoutPrivateEventAccess`, "
            + "`delegateWithPrivateEventAccess`, `custom`, or `none`. The value is null when "
            + "Microsoft reports no role."
        )
    )
    allowed_roles: list[str] = Field(
        description=(
            "The roles that Microsoft lets the owner give to this person on this calendar, with "
            + "the same names as `role`. The list is empty when Microsoft reports none."
        )
    )
    is_inside_organization: bool | None = Field(
        description=(
            "True when this person is in the same organization as the owner of the calendar. "
            + "False when the person is outside it. Null when Microsoft does not say."
        )
    )
    is_removable: bool | None = Field(
        description=(
            "True when outlook_unshare_calendar can stop this share. False when Microsoft does "
            + "not let anybody remove this row. Null when Microsoft does not say."
        )
    )

    @classmethod
    def from_permission(cls, permission: CalendarPermission, *, calendar_id: str) -> Self:
        assert permission.id is not None, "Graph listed a calendar permission with no id"
        person = permission.email_address
        return cls(
            uri=CalendarPermissionHandle(calendar_id, permission.id).uri,
            name=None if person is None else person.name,
            address=None if person is None else person.address,
            role=None if permission.role is None else str.__str__(permission.role),
            allowed_roles=[
                str.__str__(role)
                for role in cast("list[CalendarRoleType | None]", permission.allowed_roles or [])
                if role is not None
            ],
            is_inside_organization=permission.is_inside_organization,
            is_removable=permission.is_removable,
        )


class CalendarShares(BaseModel):
    shares: list[CalendarShare] = Field(
        description=(
            "The shares of the calendar, in the order that Graph returns them. The list is "
            + "empty when Microsoft reports no share for this calendar."
        )
    )
    capped: bool = Field(
        description=(
            "True when the listing stopped early and more shares remain. False means that the "
            + "list holds every share that Microsoft reported for this calendar."
        )
    )


async def list_calendar_shares(client: GraphServiceClient, *, calendar_ref: str) -> CalendarShares:
    handle = calendar_handle(calendar_ref)
    if handle is None:
        raise ToolError(_NOT_A_CALENDAR_HANDLE)

    with graph_errors(TOOL_NAME, step=STEP):
        permissions = client.me.calendars.by_calendar_id(handle.calendar_id).calendar_permissions
        first_page = await permissions.get()
        assert first_page is not None, "Graph answered a calendar permission listing with nothing"
        collected = await collect_pages(first_page, client, limit=MAX_SCANNED_ITEMS)

    return CalendarShares(
        shares=[
            CalendarShare.from_permission(permission, calendar_id=handle.calendar_id)
            for permission in collected.items
        ],
        capped=collected.capped,
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="List Calendar Shares",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def outlook_list_calendar_shares(
        calendar_ref: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The calendar whose shares to list, as the `uri` of an outlook_list_calendars "
                    + "row, copied word for word. The shape is outlook:///calendars/{id}. A "
                    + "calendar name and an event handle are not calendar handles."
                ),
            ),
        ],
        client: GraphServiceClient = graph,
    ) -> CalendarShares:
        return await list_calendar_shares(client, calendar_ref=calendar_ref)
