import dataclasses
from collections.abc import Mapping, Sequence
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import InputRequiredResult
from msgraph.generated.models.chat_message import ChatMessage
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step, not_graph
from office_365_mcp.shared import identity
from office_365_mcp.shared.calendar import confirmation_id_for
from office_365_mcp.shared.handles import (
    CHANNEL_PERMISSION,
    MessageHandle,
    message_handle,
    not_a_message_handle,
)
from office_365_mcp.shared.messages import (
    EVERYONE_SEES_IT,
    Mention,
    TeamsMessage,
    get_message,
    mention_fields,
    message_in_question,
    not_the_sender,
    outgoing_message,
    sent_by,
)
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Confirm,
    graph_client_for_caller,
    narrowed_to,
    person_confirms,
)

TOOL_NAME = "teams_edit_message"

STEP_EDIT = "edit_message"

_CHAT_READ_WRITE = "Chat.ReadWrite"
_CHANNEL_READ_WRITE = "ChannelMessage.ReadWrite"

GRAPH_PERMISSIONS: tuple[str, ...] = (
    _CHAT_READ_WRITE,
    _CHANNEL_READ_WRITE,
    identity.GRAPH_PERMISSION,
    CHANNEL_PERMISSION,
)

_CHAT_PERMISSIONS: tuple[str, ...] = (_CHAT_READ_WRITE, identity.GRAPH_PERMISSION)
_CHANNEL_PERMISSIONS: tuple[str, ...] = (
    _CHANNEL_READ_WRITE,
    CHANNEL_PERMISSION,
    identity.GRAPH_PERMISSION,
)

GRAPH_CALL_NARROWS_TO: tuple[str, ...] = _CHAT_PERMISSIONS

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000",
    "message": "Ship it Monday.",
}

_AGREE = "edit"
_DECLINE = "do not edit"
_NOTHING_CHANGED = "No message was changed."
_REFUSED = (
    f"{_NOTHING_CHANGED} If you call this tool again with this handle, the call will fail the same "
    + "way."
)

_ALREADY_DELETED = f"This message is deleted, and a deleted message cannot be changed. {_REFUSED}"

_NOT_THE_SENDER = not_the_sender("changes", tail=_REFUSED)

_DESCRIPTION = """\
Replaces the text of one Teams message, as the signed-in user. The message can be a chat \
message, a channel post, or a reply to a channel post. The message must be one that the \
signed-in user sent. Everyone in the conversation can see the change. teams_send_chat_message \
and teams_send_channel_message send a new message, and teams_delete_message removes one.

Notes:
- This tool asks the user to agree before it changes a message, every time. This tool changes \
nothing unless the user agrees.
- The new text replaces all of the old text. A mention stays in the message only if `mentions` \
gives it again. This tool sends no file and no card, so the change can remove a file or a card \
from the message.
"""

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
            "The handle of the message that this call changed. teams_list_chat_messages shows the "
            + "new text of a chat message, and teams_browse_channel shows the new text of a "
            + "channel message. The `last_edited_at` of the message shows when the message was "
            + "last changed."
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
    asked: InputRequiredResult | None = None
    with graph_errors(TOOL_NAME):
        found = await get_message(client, handle)
        assert found is not None, "Graph answered a message read with no message"
        current = TeamsMessage.from_message(found, handle=handle)
        refused = _ALREADY_DELETED if current.deleted_at is not None else None
        if refused is None and not sent_by(current, await identity.signed_in_user(client)):
            refused = _NOT_THE_SENDER
        if refused is None:
            with not_graph():
                answer = await confirm(
                    _question(current, message, mentions), _about(handle, message, mentions)
                )
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with graph_step(STEP_EDIT):
                await _edit(client, handle, _new_body(message, mentions))

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    return EditedMessage(uri=handle.uri, text=message, mentions=list(mentions))


def _question(current: TeamsMessage, message: str, mentions: Sequence[Mention]) -> str:
    named = ", ".join(repr(cut_for_a_question(mention.name)) for mention in mentions)
    mentioned = f" It mentions {named}." if mentions else ""
    attached = ", ".join(
        repr(cut_for_a_question(attachment.name)) if attachment.name else "an attachment"
        for attachment in current.attachments
    )
    removed = f" The change can remove {attached} from the message." if attached else ""
    return (
        f"Replace the text of {message_in_question(current)} with {cut_for_a_question(message)!r}?"
        + f"{mentioned}{removed} {EVERYONE_SEES_IT}"
    )


def _about(handle: MessageHandle, message: str, mentions: Sequence[Mention]) -> str:
    return confirmation_id_for(handle.uri, message, *mention_fields(mentions))


def _permissions(handle: MessageHandle) -> tuple[str, ...]:
    return _CHAT_PERMISSIONS if handle.chat_id is not None else _CHANNEL_PERMISSIONS


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
                    + "teams_list_chat_messages, teams_browse_channel, or "
                    + "teams_list_message_replies result. Copy the handle word for word."
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
            raise ToolError(not_a_message_handle(TOOL_NAME, _NOTHING_CHANGED))
        await narrowed_to(ctx, *_permissions(handle))
        return await edit_message(
            client,
            handle=handle,
            message=message,
            confirm=a_person_agrees(ctx),
            mentions=mentions,
        )
