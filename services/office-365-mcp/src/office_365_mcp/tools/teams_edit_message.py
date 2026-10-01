import dataclasses
import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import InputRequiredResult
from msgraph.generated.models.chat_message import ChatMessage
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, not_graph
from office_365_mcp.shared.handles import MessageHandle, message_handle
from office_365_mcp.shared.messages import Mention, outgoing_message
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Confirm,
    graph_client_for_caller,
    narrowed_to,
    person_confirms,
)

TOOL_NAME = "teams_edit_message"

STEP = "edit_message"

_CHAT_READ_WRITE = "Chat.ReadWrite"
_CHANNEL_READ_WRITE = "ChannelMessage.ReadWrite"

GRAPH_PERMISSIONS: tuple[str, ...] = (_CHAT_READ_WRITE, _CHANNEL_READ_WRITE)

GRAPH_CALL_NARROWS_TO: tuple[str, ...] = (_CHAT_READ_WRITE,)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000",
    "message": "Ship it Monday.",
}

_AGREE = "edit"
_DECLINE = "do not edit"
_NOTHING_CHANGED = "No message was changed."
_EVERYONE_SEES_IT = "Everyone in the conversation can see this change."

_DESCRIPTION = """\
Replaces the text of one Teams message, as the signed-in user. The message can be a chat \
message, a channel post, or a reply to a channel post. Everyone in the conversation can see the \
change. teams_send_chat_message and teams_send_channel_message send a new message, and \
teams_delete_message removes one.

Notes:
- This tool asks the user to agree before it changes a message, every time. This tool changes \
nothing unless the user agrees.
- The new text replaces all of the old text. A mention stays in the message only if `mentions` \
gives it again. This tool sends no file and no card, so the change can remove a file or a card \
from the message.
"""

_BAD_HANDLE = """\
teams_edit_message takes the `uri` handle of a Teams message from another Teams tool, and this \
value is not one. A message handle has one of exactly three shapes:
  teams:///chats/{chat_id}/messages/{message_id}
  teams:///teams/{team_id}/channels/{channel_id}/messages/{message_id}
  teams:///teams/{team_id}/channels/{channel_id}/messages/{root_id}/replies/{reply_id}
The ids are percent-encoded, for example \
teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000. Copy the `uri` of a tool result \
word for word. No message was changed. If you call this tool again with this value, the call \
will fail the same way."""

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not find this message, and no message was changed. The handle is well "
    + "formed, so the argument is not the problem. Graph answers a deleted message and a message "
    + "that the signed-in user cannot see with the same 404. A search hit that is a channel reply "
    + "can carry a handle that does not address the reply. teams_browse_channel and "
    + "teams_list_message_replies give the handle of a reply. If you call this tool again with "
    + "this handle, the call will fail the same way."
)


class EditedMessage(BaseModel):
    uri: str = Field(
        description=(
            "The handle of the message that this call changed. Pass this handle to "
            + "teams_read_message to see the new text. Its `last_edited_at` shows when the "
            + "message was last changed."
        )
    )
    text: str = Field(
        description=(
            "The new text that this call sent, exactly as the call received it. Microsoft 365 "
            + "answers this change with no content, so every field of this answer repeats the "
            + "request."
        )
    )
    mentions: list[Mention] = Field(
        description=(
            "The people that this call mentioned in the new text, in the order given. An empty "
            + "list means that this call sent no mention."
        )
    )


async def edit_message(
    client: GraphServiceClient,
    *,
    handle: MessageHandle,
    message: str,
    confirm: Confirm,
    mentions: Sequence[Mention] = (),
) -> EditedMessage | InputRequiredResult:
    with graph_errors(TOOL_NAME, step=STEP):
        with not_graph():
            answer = await confirm(
                _question(handle, message, mentions), _about(handle, message, mentions)
            )
        asked = answer if isinstance(answer, InputRequiredResult) else None
        refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            await _edit(client, handle, _new_body(message, mentions))

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    return EditedMessage(uri=handle.uri, text=message, mentions=list(mentions))


def _question(handle: MessageHandle, message: str, mentions: Sequence[Mention]) -> str:
    named = ", ".join(repr(cut_for_a_question(mention.name)) for mention in mentions)
    mentioned = f" It mentions {named}." if mentions else ""
    return (
        f"Replace the text of the Teams message {handle.uri} with "
        + f"{cut_for_a_question(message)!r}?{mentioned} {_EVERYONE_SEES_IT}"
    )


def _about(handle: MessageHandle, message: str, mentions: Sequence[Mention]) -> str:
    mentioned = [[mention.user_id, mention.name] for mention in mentions]
    return hashlib.sha256(json.dumps([handle.uri, message, mentioned]).encode()).hexdigest()


def _permission(handle: MessageHandle) -> str:
    return _CHAT_READ_WRITE if handle.chat_id is not None else _CHANNEL_READ_WRITE


def _new_body(message: str, mentions: Sequence[Mention]) -> ChatMessage:
    outgoing = outgoing_message(message, mentions=mentions)
    return dataclasses.replace(outgoing, mentions=outgoing.mentions or [])


async def _edit(client: GraphServiceClient, handle: MessageHandle, body: ChatMessage) -> None:
    if handle.chat_id is not None:
        _ = (
            await client.chats.by_chat_id(handle.chat_id)
            .messages.by_chat_message_id(handle.message_id)
            .patch(body)
        )
        return
    assert handle.team_id is not None and handle.channel_id is not None, (
        "a handle addresses either a chat or a team channel"
    )
    messages = (
        client.teams.by_team_id(handle.team_id).channels.by_channel_id(handle.channel_id).messages
    )
    if handle.reply_to_id is not None:
        _ = (
            await messages.by_chat_message_id(handle.reply_to_id)
            .replies.by_chat_message_id1(handle.message_id)
            .patch(body)
        )
        return
    _ = await messages.by_chat_message_id(handle.message_id).patch(body)


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_AGREE, decline=_DECLINE, nothing_happened=_NOTHING_CHANGED)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Edit a Teams Message",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE_IDEMPOTENT,
    )
    async def teams_edit_message(
        uri: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The message to change, as the `uri` handle from a "
                    + "teams_list_chat_messages, teams_browse_channel, teams_list_message_replies, "
                    + "teams_search_messages, or teams_read_message result. Copy the handle word "
                    + "for word."
                ),
            ),
        ],
        message: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The new text of the message, as plain text. Give the complete text that the "
                    + "message must show after the change."
                ),
            ),
        ],
        mentions: Annotated[
            list[Mention],
            Field(
                default=[],
                description=(
                    "The people to @mention in the new text, one entry for each person. This tool "
                    + "writes the mention markup itself, so `message` stays plain text. The "
                    + "mentions come first, in the order given. An empty list sends the new text "
                    + "with no mention."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> EditedMessage | InputRequiredResult:
        handle = message_handle(uri)
        if handle is None:
            raise ToolError(_BAD_HANDLE)
        await narrowed_to(ctx, _permission(handle))
        return await edit_message(
            client,
            handle=handle,
            message=message,
            confirm=a_person_agrees(ctx),
            mentions=mentions,
        )
