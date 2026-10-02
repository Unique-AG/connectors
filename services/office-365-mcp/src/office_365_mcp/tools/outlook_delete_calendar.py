from collections.abc import Mapping
from contextlib import suppress
from typing import Annotated, Literal

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from mcp.types import InputRequiredResult
from msgraph.generated.models.calendar import Calendar
from msgraph.generated.models.user import User
from msgraph.generated.users.item.calendars.item.calendar_item_request_builder import (
    CalendarItemRequestBuilder,
)
from msgraph.generated.users.item.calendars.item.events.events_request_builder import (
    EventsRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import GraphNotFound, graph_errors, graph_step, not_graph
from office_365_mcp.shared import identity
from office_365_mcp.shared.calendar import CalendarSummary, confirmation_id_for
from office_365_mcp.shared.handles import CalendarHandle, calendar_handle
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "outlook_delete_calendar"

STEP_CALENDAR = "calendar"
STEP_EVENTS = "calendar_events"
STEP_DELETE = "delete_calendar"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Calendars.ReadWrite", identity.GRAPH_PERMISSION)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "calendar_ref": "outlook:///calendars/AAMkSYNTHETIC-cal-0001%3D",
}

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return the calendar that this call named, and nothing was deleted. "
    + "The handle is well formed. A person or an earlier call of this tool probably deleted the "
    + "calendar. Call outlook_list_calendars again. If the calendar is not in that result, it is "
    + "already gone and nothing is left to delete. If you call this tool again with the same "
    + "arguments, the call will fail the same way."
)

_CALENDAR_FIELDS: tuple[str, ...] = ("id", "name", "owner", "isDefaultCalendar", "isRemovable")

_CalendarQuery = CalendarItemRequestBuilder.CalendarItemRequestBuilderGetQueryParameters
_EventsQuery = EventsRequestBuilder.EventsRequestBuilderGetQueryParameters

_AGREE = "delete"
_DECLINE = "keep the calendar"
_NOTHING_DELETED = "The calendar was not deleted."

_DESCRIPTION = """\
Deletes one calendar that the signed-in user owns, when that calendar holds no event. \
outlook_list_calendars lists the calendars and their handles. This tool always asks the user to \
agree, and the question names the calendar.

Notes:
- No event is lost, because this tool refuses a calendar that holds an event. It also refuses \
the default calendar, a calendar that another person owns, and a calendar that Microsoft marks \
as not removable.
- Microsoft does not document whether a deleted calendar can be restored.
- This call is safe to repeat after a timeout. A second call finds no calendar and reports that.
"""

_NOT_A_CALENDAR_HANDLE = (
    "outlook_delete_calendar takes a calendar handle in `calendar_ref`: "
    + "outlook:///calendars/{id}, exactly as outlook_list_calendars reported it in `uri`. "
    + "A calendar name is not a handle. An event handle is not a calendar handle. Nothing was "
    + "deleted. If you call this tool again with the same arguments, the call will fail the same "
    + "way."
)

_THE_DEFAULT_CALENDAR = (
    "That handle names the default calendar of the mailbox. Microsoft Graph deletes only a "
    + "calendar other than the default calendar. Nothing was deleted. If you call this tool "
    + "again with the same arguments, the call will fail the same way."
)

_NOT_REMOVABLE = (
    "Microsoft 365 marks this calendar as not removable from the mailbox, so "
    + "outlook_delete_calendar did not delete it. Nothing was deleted. If you call this tool "
    + "again with the same arguments, the call will fail the same way."
)

_NOT_THE_OWNER = (
    "Microsoft 365 does not report the signed-in user as the owner of this calendar. Another "
    + "person owns it and shares it with the user, or this connector cannot tell who owns it. "
    + "This tool deletes only a calendar that the signed-in user owns. Nothing was deleted. If "
    + "you call this tool again with the same arguments, the call will fail the same way."
)

_HOLDS_AN_EVENT = (
    "This calendar holds at least one event, so outlook_delete_calendar did not delete it. This "
    + "tool deletes only an empty calendar, so that no event is lost. Nothing was deleted. Tell "
    + "the user to move or cancel the events of this calendar first, for example in Outlook. "
    + "Then the user can ask again."
)


class DeletedCalendar(BaseModel):
    uri: str = Field(
        description=(
            "The handle that this call was given, echoed back. The calendar that this handle "
            + "named is deleted, so do not pass this handle to another tool."
        )
    )
    name: str | None = Field(
        description=(
            "The name of the calendar, as Microsoft 365 reported it immediately before the "
            + "delete. The value is null when Microsoft 365 reported no name."
        )
    )
    deleted: Literal[True] = Field(
        description=(
            "Always true, because this tool answers only when the calendar is gone. It is also "
            + "true when the calendar was there at the start of this call, but Graph then found "
            + "no calendar to delete."
        )
    )


async def delete_calendar(
    client: GraphServiceClient, *, calendar_ref: str, confirm: Confirm
) -> DeletedCalendar | InputRequiredResult:
    handle = calendar_handle(calendar_ref)
    if handle is None:
        raise ToolError(_NOT_A_CALENDAR_HANDLE)

    asked: InputRequiredResult | None = None
    with graph_errors(TOOL_NAME):
        calendar = await _calendar(client, handle.calendar_id)
        refused = _refusal(calendar, await identity.signed_in_user(client))
        if refused is None and await _holds_an_event(client, handle.calendar_id):
            refused = _HOLDS_AN_EVENT
        if refused is None:
            with not_graph():
                answer = await confirm(
                    _question(handle, calendar), confirmation_id_for(handle.uri, TOOL_NAME)
                )
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with suppress(GraphNotFound), graph_step(STEP_DELETE):
                await client.me.calendars.by_calendar_id(handle.calendar_id).delete()

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    return DeletedCalendar(uri=handle.uri, name=calendar.name, deleted=True)


async def _calendar(client: GraphServiceClient, calendar_id: str) -> Calendar:
    with graph_step(STEP_CALENDAR):
        found = await client.me.calendars.by_calendar_id(calendar_id).get(
            request_configuration=RequestConfiguration[_CalendarQuery](
                query_parameters=_CalendarQuery(select=list(_CALENDAR_FIELDS))
            )
        )
    assert found is not None, "Graph answered a calendar read with no calendar"
    return found


async def _holds_an_event(client: GraphServiceClient, calendar_id: str) -> bool:
    with graph_step(STEP_EVENTS):
        page = await client.me.calendars.by_calendar_id(calendar_id).events.get(
            request_configuration=RequestConfiguration[_EventsQuery](
                query_parameters=_EventsQuery(select=["id"], top=1)
            )
        )
    assert page is not None, "Graph answered an event listing with no collection"
    return bool(page.value) or page.odata_next_link is not None


def _refusal(calendar: Calendar, user: User) -> str | None:
    if calendar.is_default_calendar:
        return _THE_DEFAULT_CALENDAR
    if calendar.is_removable is False:
        return _NOT_REMOVABLE
    if CalendarSummary.from_calendar(calendar, signed_in=user).is_mine is not True:
        return _NOT_THE_OWNER
    return None


def _question(handle: CalendarHandle, calendar: Calendar) -> str:
    named = cut_for_a_question(calendar.name or handle.uri)
    return (
        f"Delete the calendar {named!r}? This calendar holds no event. Microsoft does not "
        + "document whether a deleted calendar can be restored."
    )


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_AGREE, decline=_DECLINE, nothing_happened=_NOTHING_DELETED)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Delete a Calendar",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE_IDEMPOTENT,
    )
    async def outlook_delete_calendar(
        calendar_ref: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The calendar to delete, as the `uri` of an outlook_list_calendars row, "
                    + "copied word for word. The shape is outlook:///calendars/{id}. A calendar "
                    + "name and an event handle are not calendar handles."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> DeletedCalendar | InputRequiredResult:
        return await delete_calendar(
            client, calendar_ref=calendar_ref, confirm=a_person_agrees(ctx)
        )
