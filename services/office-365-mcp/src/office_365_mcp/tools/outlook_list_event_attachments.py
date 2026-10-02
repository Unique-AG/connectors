from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.attachment import Attachment
from msgraph.generated.users.item.calendars.item.events.item.attachments.attachments_request_builder import (  # noqa: E501
    AttachmentsRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import MAX_SCANNED_ITEMS, collect_pages, graph_errors
from office_365_mcp.shared.attachments import ATTACHMENT_FIELDS, AttachmentSummary
from office_365_mcp.shared.handles import EventAttachmentHandle, EventHandle, event_handle
from office_365_mcp.shared.immutable_ids import immutable_id_headers
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "outlook_list_event_attachments"

STEP_ATTACHMENTS = "event_attachments"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Calendars.Read", "Calendars.Read.Shared")

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "outlook:///events/AAMkSYNTHETIC-cal-0001%3D/AAMkAGI2SYNTHETIC-immutable-0001%3D"
}

_AttachmentsQuery = AttachmentsRequestBuilder.AttachmentsRequestBuilderGetQueryParameters

_DESCRIPTION = """\
Lists the attachments of one event in the signed-in user's mailbox, given the `uri` of an \
outlook_list_events row. outlook_read_event reads the event itself. Its `has_attachments` value \
says if the event has any attachment.

Notes:
- This tool returns no bytes. To get the file of a row, give its `uri` to \
outlook_read_event_attachment.
- The list also holds inline images. The `is_inline` value of each row tells them apart.
- outlook_read_event_attachment returns only the kind `file`. It refuses the kinds `item` and \
`reference`.
"""

_BAD_HANDLE = (
    "outlook_list_event_attachments takes the `uri` of an event, and this is not one. Take the "
    + "`uri` of a row that outlook_list_events returned, and copy it word for word. An event "
    + "handle looks like "
    + "outlook:///events/AAMkSYNTHETIC-cal-0001%3D/AAMkAGI2SYNTHETIC-immutable-0001%3D. "
    + "A subject line, a calendar handle, a message handle, and an Outlook web link are not "
    + "event handles. An attachment handle belongs to outlook_read_event_attachment. If you "
    + "call this tool again with the same arguments, the call will fail the same way."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return this event. The handle is well formed, so this is not a bad "
    + "argument. Graph gives one 404 for an event that was deleted or moved. It also gives that "
    + "404 for an event that never existed and for an event that this user cannot see. This "
    + "tool cannot tell which one it is. Report that this tool failed to list the attachments. "
    + "Do not report that the meeting was canceled. Find the event again with "
    + "outlook_list_events. Then list its attachments again with the new `uri`. If you call "
    + "this tool again with the same arguments, the call will fail the same way."
)


class EventAttachments(BaseModel):
    attachments: list[AttachmentSummary] = Field(
        description=(
            "One row for each attachment of the event, in the order that Microsoft 365 returns "
            "them. The list is empty when the event has no attachment."
        )
    )
    capped: bool = Field(
        description=(
            "True when the listing stopped early and more attachments remain. False means that "
            "the list holds every attachment of the event."
        )
    )


async def list_event_attachments(client: GraphServiceClient, *, uri: str) -> EventAttachments:
    handle = event_handle(uri)
    if handle is None:
        raise ToolError(_BAD_HANDLE)

    headers = immutable_id_headers()
    with graph_errors(TOOL_NAME, step=STEP_ATTACHMENTS):
        first_page = await (
            client.me.calendars.by_calendar_id(handle.calendar_id)
            .events.by_event_id(handle.event_id)
            .attachments.get(
                request_configuration=RequestConfiguration[_AttachmentsQuery](
                    query_parameters=_AttachmentsQuery(select=list(ATTACHMENT_FIELDS)),
                    headers=headers,
                )
            )
        )
        assert first_page is not None, "Graph answered an attachment listing with no collection"
        collected = await collect_pages(
            first_page, client, limit=MAX_SCANNED_ITEMS, headers=headers
        )

    return EventAttachments(
        attachments=[_row(attachment, handle) for attachment in collected.items],
        capped=collected.capped,
    )


def _row(attachment: Attachment, handle: EventHandle) -> AttachmentSummary:
    assert attachment.id is not None, "Graph answered an attachment with no id"
    return AttachmentSummary.from_attachment(
        attachment,
        uri=EventAttachmentHandle(handle.calendar_id, handle.event_id, attachment.id).uri,
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="List Event Attachments",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def outlook_list_event_attachments(
        uri: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The event handle (`uri`) from a row of outlook_list_events, word for word. "
                    "An attachment handle is not an event handle."
                ),
            ),
        ],
        client: GraphServiceClient = graph,
    ) -> EventAttachments:
        return await list_event_attachments(client, uri=uri)
