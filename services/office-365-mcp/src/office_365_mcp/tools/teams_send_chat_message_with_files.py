from collections.abc import Mapping, Sequence
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.chat_message import ChatMessage
from msgraph.generated.models.chat_message_importance import ChatMessageImportance
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.files import attachable_files, attachment_handles
from office_365_mcp.shared.handles import CHAT_PERMISSION, MessageHandle
from office_365_mcp.shared.messages import (
    ATTACHMENTS_FIELD,
    CHAT_ID_FIELD,
    CHAT_IMPORTANCE_FIELD,
    CHAT_SEND,
    CHAT_SUBJECT_FIELD,
    MENTIONS_FIELD,
    MESSAGE_FIELD,
    ChatImportance,
    Mention,
    TeamsMessage,
    mentioned_members,
    outgoing_message,
    send_binding,
    send_question,
)
from office_365_mcp.shared.seam import (
    WRITE_ADDITIVE,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "teams_send_chat_message_with_files"

STEP_SEND = "send_chat_message"

GRAPH_PERMISSIONS: tuple[str, ...] = ("ChatMessage.Send", "Files.Read.All", CHAT_PERMISSION)

CHANGE_SHOWN_BY: tuple[str, ...] = ("teams_list_chat_messages",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "chat_id": "19:release@thread.v2",
    "message": "Here is the plan.",
    "attachments": ["sharepoint:///files/b%21SYNTHETICDRIVE0000/01SYNTHETICFILE0000"],
}

_DESCRIPTION = """\
Sends one message as the signed-in user to an existing Teams chat. The message attaches one or \
more files that are already in SharePoint. The message can @mention people. The mentions come \
first, in the order given, and the text of `message` follows them. The files come after the \
text. This tool uploads nothing and changes no sharing setting of a file. This tool sends the \
message immediately, and nothing here can recall it. teams_send_chat_message sends a message with \
no file. teams_send_channel_message_with_files is the tool for a channel.

Notes:
- This tool asks the user to agree before it sends anything, every time. This tool sends \
nothing unless the user agrees.
- The question shows the Microsoft Entra object id of each person in `mentions`. This tool reads \
the members of the chat. The question and the message show the name that Microsoft 365 gives each \
member. If a person in `mentions` is not a member of the chat, this tool sends nothing.
- If a call times out, do not call this tool again first. Before you call again, make sure that \
teams_list_chat_messages does not already show the message.
"""


async def send_chat_message_with_files(
    client: GraphServiceClient,
    *,
    chat_id: str,
    message: str,
    attachments: Sequence[str],
    confirm: Confirm,
    mentions: Sequence[Mention] = (),
    importance: ChatImportance | None = None,
    subject: str | None = None,
) -> TeamsMessage | InputRequiredResult:
    assert attachments, "the schema lets no call through without a file to attach"
    handles = attachment_handles(attachments)
    if isinstance(handles, str):
        raise ToolError(f"{CHAT_SEND.nothing_sent} {handles}")
    sent: ChatMessage | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME):
        members = await mentioned_members(client, chat_id, mentions)
        files = () if isinstance(members, str) else await attachable_files(client, handles)
        if isinstance(members, str):
            refused = members
        elif isinstance(files, str):
            refused = f"{CHAT_SEND.nothing_sent} {files}"
        else:
            question = send_question(
                CHAT_SEND,
                message,
                f"to chat {chat_id!r}",
                members,
                subject=subject,
                importance=importance,
                files=files,
            )
            about = send_binding(
                (chat_id,), message, members, subject=subject, importance=importance, files=handles
            )
            with not_graph():
                answer = await confirm(question, about)
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
            if refused is None and asked is None:
                with graph_step(STEP_SEND):
                    sent = await client.chats.by_chat_id(chat_id).messages.post(
                        outgoing_message(
                            message,
                            mentions=members,
                            importance=None
                            if importance is None
                            else ChatMessageImportance(importance),
                            subject=subject,
                            attachments=files,
                        ),
                        request_configuration=RequestConfiguration[QueryParameters](
                            options=no_retry()
                        ),
                    )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert sent is not None, "a send that nothing refused answered with no message"
    assert sent.id is not None, "Graph accepted a chat message post but returned no id"
    return TeamsMessage.from_message(sent, handle=MessageHandle(sent.id, chat_id=chat_id))


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(
        ctx,
        agree=CHAT_SEND.agree,
        decline=CHAT_SEND.decline,
        nothing_happened=CHAT_SEND.nothing_sent,
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Send a Teams Chat Message with Files",
        description=_DESCRIPTION,
        annotations=WRITE_ADDITIVE,
    )
    async def teams_send_chat_message_with_files(
        chat_id: Annotated[str, Field(min_length=1, description=CHAT_ID_FIELD)],
        message: Annotated[str, Field(min_length=1, description=MESSAGE_FIELD)],
        attachments: Annotated[list[str], Field(min_length=1, description=ATTACHMENTS_FIELD)],
        mentions: Annotated[list[Mention], Field(default=[], description=MENTIONS_FIELD)],
        ctx: Context,
        importance: Annotated[
            ChatImportance | None, Field(description=CHAT_IMPORTANCE_FIELD)
        ] = None,
        subject: Annotated[str | None, Field(min_length=1, description=CHAT_SUBJECT_FIELD)] = None,
        client: GraphServiceClient = graph,
    ) -> TeamsMessage | InputRequiredResult:
        return await send_chat_message_with_files(
            client,
            chat_id=chat_id,
            message=message,
            attachments=attachments,
            confirm=a_person_agrees(ctx),
            mentions=mentions,
            importance=importance,
            subject=subject,
        )
