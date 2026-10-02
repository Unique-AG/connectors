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
from office_365_mcp.shared.handles import MessageHandle
from office_365_mcp.shared.messages import (
    ATTACHMENTS_FIELD,
    CHANNEL_ID_FIELD,
    CHANNEL_IMPORTANCE_FIELD,
    CHANNEL_POST,
    CHANNEL_SUBJECT_FIELD,
    MENTIONS_FIELD,
    MESSAGE_FIELD,
    REPLY_TO_ID_FIELD,
    TEAM_ID_FIELD,
    ChannelImportance,
    Mention,
    TeamsMessage,
    outgoing_message,
    send_binding,
    send_question,
    subject_on_a_reply,
)
from office_365_mcp.shared.seam import (
    WRITE_ADDITIVE,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "teams_send_channel_message_with_files"

STEP_SEND = "send_channel_message"
STEP_REPLY = "reply_channel_message"

GRAPH_PERMISSIONS: tuple[str, ...] = ("ChannelMessage.Send", "Files.Read.All")

CHANGE_SHOWN_BY: tuple[str, ...] = ("teams_browse_channel",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "team_id": "2b7c9d10-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
    "channel_id": "19:general@thread.tacv2",
    "message": "Ship it.",
    "attachments": ["sharepoint:///files/b%21SYNTHETICDRIVE0000/01SYNTHETICFILE0000"],
}

_DESCRIPTION = """\
Posts one new message as the signed-in user to an existing channel of a Teams team. The message \
attaches one or more files that are already in SharePoint. With `reply_to_id`, this tool replies \
in the thread of an existing post. The message can @mention people. The mentions come first, in \
the order given, and the text of `message` follows them. The files come after the text. This tool \
uploads nothing and changes no sharing setting of a file. This tool posts the message \
immediately, and nothing here can recall it. teams_send_channel_message posts a message with no \
file. teams_send_chat_message_with_files is the tool for a chat.

Notes:
- This tool asks the user to agree before it posts anything, every time. This tool posts \
nothing unless the user agrees.
- If a call times out, do not call this tool again first. Before you call again, make sure that \
the channel does not already show the message.
"""


async def send_channel_message_with_files(
    client: GraphServiceClient,
    *,
    team_id: str,
    channel_id: str,
    message: str,
    attachments: Sequence[str],
    confirm: Confirm,
    mentions: Sequence[Mention] = (),
    subject: str | None = None,
    importance: ChannelImportance | None = None,
    reply_to_id: str | None = None,
) -> TeamsMessage | InputRequiredResult:
    assert attachments, "the schema lets no call through without a file to attach"
    if subject is not None and reply_to_id is not None:
        raise ToolError(subject_on_a_reply(TOOL_NAME))
    handles = attachment_handles(attachments)
    if isinstance(handles, str):
        raise ToolError(f"{CHANNEL_POST.nothing_sent} {handles}")
    about = send_binding(
        (team_id, channel_id, repr(reply_to_id)),
        message,
        mentions,
        subject=subject,
        importance=importance,
        files=handles,
    )
    sent: ChatMessage | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME):
        files = await attachable_files(client, handles)
        if isinstance(files, str):
            refused = f"{CHANNEL_POST.nothing_sent} {files}"
        else:
            where = "to" if reply_to_id is None else f"as a reply to post {reply_to_id!r} in"
            question = send_question(
                CHANNEL_POST,
                message,
                f"{where} channel {channel_id!r} in team {team_id!r}",
                mentions,
                subject=subject,
                importance=importance,
                files=files,
            )
            with not_graph():
                answer = await confirm(question, about)
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
            if refused is None and asked is None:
                outgoing = outgoing_message(
                    message,
                    mentions=mentions,
                    importance=None if importance is None else ChatMessageImportance(importance),
                    subject=subject,
                    attachments=files,
                )
                messages = (
                    client.teams.by_team_id(team_id).channels.by_channel_id(channel_id).messages
                )
                configuration = RequestConfiguration[QueryParameters](options=no_retry())
                if reply_to_id is None:
                    with graph_step(STEP_SEND):
                        sent = await messages.post(outgoing, request_configuration=configuration)
                else:
                    with graph_step(STEP_REPLY):
                        sent = await messages.by_chat_message_id(reply_to_id).replies.post(
                            outgoing, request_configuration=configuration
                        )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert sent is not None, "a post that nothing refused answered with no message"
    assert sent.id is not None, "Graph accepted a channel message post but returned no id"
    return TeamsMessage.from_message(
        sent,
        handle=MessageHandle(
            sent.id, team_id=team_id, channel_id=channel_id, reply_to_id=reply_to_id
        ),
    )


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(
        ctx,
        agree=CHANNEL_POST.agree,
        decline=CHANNEL_POST.decline,
        nothing_happened=CHANNEL_POST.nothing_sent,
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Send a Teams Channel Message with Files",
        description=_DESCRIPTION,
        annotations=WRITE_ADDITIVE,
    )
    async def teams_send_channel_message_with_files(
        team_id: Annotated[str, Field(min_length=1, description=TEAM_ID_FIELD)],
        channel_id: Annotated[str, Field(min_length=1, description=CHANNEL_ID_FIELD)],
        message: Annotated[str, Field(min_length=1, description=MESSAGE_FIELD)],
        attachments: Annotated[list[str], Field(min_length=1, description=ATTACHMENTS_FIELD)],
        mentions: Annotated[list[Mention], Field(default=[], description=MENTIONS_FIELD)],
        ctx: Context,
        subject: Annotated[
            str | None, Field(min_length=1, description=CHANNEL_SUBJECT_FIELD)
        ] = None,
        importance: Annotated[
            ChannelImportance | None, Field(description=CHANNEL_IMPORTANCE_FIELD)
        ] = None,
        reply_to_id: Annotated[
            str | None, Field(min_length=1, description=REPLY_TO_ID_FIELD)
        ] = None,
        client: GraphServiceClient = graph,
    ) -> TeamsMessage | InputRequiredResult:
        return await send_channel_message_with_files(
            client,
            team_id=team_id,
            channel_id=channel_id,
            message=message,
            attachments=attachments,
            confirm=a_person_agrees(ctx),
            mentions=mentions,
            subject=subject,
            importance=importance,
            reply_to_id=reply_to_id,
        )
