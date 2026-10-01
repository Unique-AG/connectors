from collections.abc import Mapping
from contextlib import suppress
from typing import Annotated, Literal

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from mcp.types import InputRequiredResult
from msgraph.generated.models.calendar import Calendar
from msgraph.generated.models.calendar_permission import CalendarPermission
from msgraph.generated.users.item.calendars.item.calendar_item_request_builder import (
    CalendarItemRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import GraphNotFound, graph_errors, graph_step, not_graph
from office_365_mcp.shared.calendar import confirmation_id_for
from office_365_mcp.shared.handles import CalendarHandle, calendar_permission_handle
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "outlook_unshare_calendar"

STEP_PERMISSION = "calendar_permission"
STEP_CALENDAR = "calendar"
STEP_UNSHARE = "unshare_calendar"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Calendars.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "share_ref": (
        "outlook:///calendarpermissions/AAMkSYNTHETIC-cal-0001%3D/"
        + "RXhjaGFuZ2VQdWJsaXNoZWRVc2VyLlNZTlRIRVRJQw%3D%3D"
    ),
}

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return the share that this call named, and nothing was removed. The "
    + "handle is well formed. A person or an earlier call of this tool probably removed the "
    + "share, or deleted the calendar. Call outlook_list_calendar_shares again. If the share is "
    + "not in that result, it is already gone and nothing is left to remove. If you call this "
    + "tool again with the same arguments, the call will fail the same way."
)

_CALENDAR_FIELDS: tuple[str, ...] = ("id", "name")

_CalendarQuery = CalendarItemRequestBuilder.CalendarItemRequestBuilderGetQueryParameters

_AGREE = "stop sharing"
_DECLINE = "keep the share"
_NOTHING_REMOVED = "The share was not removed."
_NO_ADDRESS = "a person whose address Microsoft did not report"

_DESCRIPTION = """\
Stops one share of a calendar of the signed-in user. The other person then loses the access \
that the share gave. This tool can also remove a delegate. outlook_list_calendar_shares lists \
the shares of a calendar and their handles. outlook_share_calendar adds a share.

Notes:
- This tool always asks the user to agree, and the question names the calendar, the person and \
the role.
- This tool refuses the `My Organization` row, and any other share that Microsoft marks as not \
removable.
- This call is safe to repeat after a timeout. A second call finds no share and reports that.
"""

_NOT_A_SHARE_HANDLE = (
    "outlook_unshare_calendar takes a share handle in `share_ref`: "
    + "outlook:///calendarpermissions/{calendar_id}/{id}, exactly as "
    + "outlook_list_calendar_shares reported it in `uri`. A calendar handle is not a share "
    + "handle. An email address is not a share handle. Nothing was removed. If you call this tool "
    + "again with this value, the call will fail the same way."
)

_NOT_REMOVABLE = (
    "Microsoft 365 marks this share as not removable, so outlook_unshare_calendar did not remove "
    + "it. The `My Organization` row is always like this, because it sets what the whole "
    + "organization can see. Nothing was removed. If you call this tool again with this handle, "
    + "the call will fail the same way."
)


class UnsharedCalendar(BaseModel):
    uri: str = Field(
        description=(
            "The share handle that this call was given, echoed back. The share that this handle "
            + "named is gone, so do not pass this handle to another tool."
        )
    )
    calendar_uri: str = Field(
        description=(
            "The handle of the calendar that the share was on. Pass it to "
            + "outlook_list_calendar_shares to see who can still see the calendar."
        )
    )
    address: str | None = Field(
        description=(
            "The SMTP address of the person who lost the share, as Microsoft 365 reported it "
            + "immediately before the removal. The value is null when Microsoft 365 reported none."
        )
    )
    removed: Literal[True] = Field(
        description=(
            "Always true, because this tool answers only when the share is gone. It is also true "
            + "when the share was there at the start of this call, but Graph then found no share "
            + "to remove."
        )
    )


async def unshare_calendar(
    client: GraphServiceClient, *, share_ref: str, confirm: Confirm
) -> UnsharedCalendar | InputRequiredResult:
    handle = calendar_permission_handle(share_ref)
    if handle is None:
        raise ToolError(_NOT_A_SHARE_HANDLE)

    target = client.me.calendars.by_calendar_id(handle.calendar_id)
    share = target.calendar_permissions.by_calendar_permission_id(handle.permission_id)
    calendar = CalendarHandle(handle.calendar_id)
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME):
        with graph_step(STEP_PERMISSION):
            permission = await share.get()
        assert permission is not None, "Graph answered a calendar permission read with nothing"
        if permission.is_removable is False:
            refused = _NOT_REMOVABLE
        if refused is None:
            with graph_step(STEP_CALENDAR):
                calendar_read = await target.get(
                    request_configuration=RequestConfiguration[_CalendarQuery](
                        query_parameters=_CalendarQuery(select=list(_CALENDAR_FIELDS))
                    )
                )
            assert calendar_read is not None, "Graph answered a calendar read with no calendar"
            with not_graph():
                answer = await confirm(
                    _question(calendar, calendar_read, permission),
                    confirmation_id_for(handle.uri, TOOL_NAME),
                )
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with suppress(GraphNotFound), graph_step(STEP_UNSHARE):
                await share.delete()

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    person = permission.email_address
    return UnsharedCalendar(
        uri=handle.uri,
        calendar_uri=calendar.uri,
        address=None if person is None else person.address,
        removed=True,
    )


def _question(
    calendar: CalendarHandle, calendar_read: Calendar, permission: CalendarPermission
) -> str:
    title = cut_for_a_question(calendar_read.name or calendar.uri)
    person = permission.email_address
    who = None if person is None else person.address or person.name
    held = (
        "Microsoft did not report the role of this person."
        if permission.role is None
        else f"This person has the role {str.__str__(permission.role)} on it now."
    )
    return (
        f"Stop sharing the calendar {title!r} with {who or _NO_ADDRESS}? {held} This person then "
        + "loses the access that the share gives."
    )


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_AGREE, decline=_DECLINE, nothing_happened=_NOTHING_REMOVED)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Stop Sharing a Calendar",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE_IDEMPOTENT,
    )
    async def outlook_unshare_calendar(
        share_ref: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The share to stop, as the `uri` of an outlook_list_calendar_shares row, "
                    + "copied word for word. The shape is "
                    + "outlook:///calendarpermissions/{calendar_id}/{id}. A calendar handle and an "
                    + "email address are not share handles."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> UnsharedCalendar | InputRequiredResult:
        return await unshare_calendar(client, share_ref=share_ref, confirm=a_person_agrees(ctx))
