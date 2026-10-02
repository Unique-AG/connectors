from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors
from office_365_mcp.shared.attachments import AttachmentSummary, message_attachments
from office_365_mcp.shared.handles import mail_message_handle
from office_365_mcp.shared.seam import MAILBOX_FIELD, READ_ONLY, graph_client_for_caller

TOOL_NAME = "outlook_list_attachments"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Mail.Read", "Mail.Read.Shared")

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "outlook:///messages/AAMkAGI2SYNTHETIC-immutable-0001%3D"
}

_DESCRIPTION = """\
Lists the attachments of one message, in the signed-in user's own mailbox or, with `mailbox`, a \
shared or delegated one. To find the message first, use outlook_search_mail or outlook_list_mail.

Notes:
- This tool returns no bytes. To get the file of a row, give its `uri` to \
outlook_read_attachment.
- The list also holds inline images, for example a logo in a signature. The `is_inline` value \
of each row tells them apart.
- outlook_read_attachment returns only the kind `file`. It refuses the kinds `item` and \
`reference`.
"""

_BAD_HANDLE = (
    "outlook_list_attachments takes the `uri` of a message, and this is not one. Take the `uri` "
    + "of a message that outlook_search_mail or outlook_list_mail returned, and copy it word for "
    + "word. A message handle looks like outlook:///messages/AAMkAGI2SYNTHETIC-immutable-0001%3D. "
    + "A subject line, an email address, and an Outlook web link are not message handles. An "
    + "attachment handle belongs to outlook_read_attachment. If you call this tool again with "
    + "the same arguments, the call will fail the same way."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return this message. The handle is well formed, so this is not a bad "
    + "argument. Graph gives one 404 for a message that was deleted, a message that never "
    + "existed, and a message that this user cannot see. This tool cannot tell which one it is. "
    + "Find the message again with outlook_search_mail or outlook_list_mail. Then list its "
    + "attachments again with the new `uri`. If you call this tool again with the same "
    + "arguments, the call will fail the same way."
)


class MessageAttachments(BaseModel):
    attachments: list[AttachmentSummary] = Field(
        description=(
            "One row for each attachment of the message, in the order that Microsoft 365 returns "
            "them. The list is empty when the message has no attachment."
        )
    )
    capped: bool = Field(
        description=(
            "True when the listing stopped early and more attachments remain. False means that "
            "the list holds every attachment of the message."
        )
    )


async def list_attachments(
    client: GraphServiceClient, *, uri: str, mailbox: str | None = None
) -> MessageAttachments:
    handle = mail_message_handle(uri)
    if handle is None:
        raise ToolError(_BAD_HANDLE)

    with graph_errors(TOOL_NAME):
        found = await message_attachments(client, handle=handle, mailbox=mailbox)

    return MessageAttachments(attachments=found.items, capped=found.capped)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="List Mail Attachments",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def outlook_list_attachments(
        uri: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The message handle (`uri`) from a result of outlook_search_mail, "
                    "outlook_list_mail, or outlook_read_thread, word for word. An attachment "
                    "handle is not a message handle."
                ),
            ),
        ],
        mailbox: Annotated[str | None, Field(min_length=1, description=MAILBOX_FIELD)] = None,
        client: GraphServiceClient = graph,
    ) -> MessageAttachments:
        return await list_attachments(client, uri=uri, mailbox=mailbox)
