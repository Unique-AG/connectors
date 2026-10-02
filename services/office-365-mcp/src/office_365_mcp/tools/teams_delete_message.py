from collections.abc import Mapping
from typing import Annotated, Literal

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.user import User
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry, not_graph
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
    TeamsMessage,
    get_message,
    message_in_question,
    not_the_sender,
    sent_by,
)
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE,
    Confirm,
    graph_client_for_caller,
    narrowed_to,
    person_confirms,
)

TOOL_NAME = "teams_delete_message"

STEP_DELETE = "delete_message"

_CHAT_WRITE = "Chat.ReadWrite"
_CHANNEL_WRITE = "ChannelMessage.ReadWrite"

GRAPH_PERMISSIONS: tuple[str, ...] = (
    _CHAT_WRITE,
    _CHANNEL_WRITE,
    identity.GRAPH_PERMISSION,
    CHANNEL_PERMISSION,
)

_CHAT_PERMISSIONS: tuple[str, ...] = (_CHAT_WRITE, identity.GRAPH_PERMISSION)
_CHANNEL_PERMISSIONS: tuple[str, ...] = (
    _CHANNEL_WRITE,
    CHANNEL_PERMISSION,
    identity.GRAPH_PERMISSION,
)

GRAPH_CALL_NARROWS_TO: tuple[str, ...] = _CHAT_PERMISSIONS

CHANGE_SHOWN_BY: tuple[str, ...] = (
    "teams_read_message",
    "teams_list_chat_messages",
    "teams_browse_channel",
    "teams_list_message_replies",
)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000",
}

_AGREE = "delete"
_DECLINE = "do not delete"
_NOTHING_DELETED = "No message was deleted."
_REFUSED = (
    f"{_NOTHING_DELETED} If you call this tool again with the same arguments, the call will fail "
    + "the same way."
)

_ALREADY_DELETED = f"This message is already deleted. {_REFUSED}"

_NOT_THE_SENDER = not_the_sender("deletes", tail=_REFUSED)

_DESCRIPTION = """\
Deletes one Teams message as the signed-in user. The message can be a chat message, a channel \
post, or a reply to a channel post. The message must be one that the signed-in user sent. This \
is a soft delete. Teams shows the message as deleted. Everyone in the conversation can see the \
change. teams_edit_message replaces the text of a message instead.

Notes:
- This tool asks the user to agree before it deletes a message, every time. This tool deletes \
nothing unless the user agrees.
- Microsoft Graph has an operation that undoes a soft delete (undoSoftDelete). This connector \
does not offer that operation.
- If a call times out, do not call this tool again first. Before you call again, make sure that \
the conversation does not already show the change.
"""

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not find this message, and no message was deleted. The handle is well "
    + "formed, so the argument is not the problem. Graph gives the same 404 for a deleted message "
    + "and for a message that the signed-in user cannot see. A search hit that is a channel reply "
    + "can carry a handle that does not address the reply. teams_browse_channel and "
    + "teams_list_message_replies give the handle of a reply. If you call this tool again with "
    + "the same arguments, the call will fail the same way."
)


class DeletedMessage(BaseModel):
    uri: str = Field(
        description=(
            "The handle of the message that this call deleted, exactly as the call received it. "
            + "After this call, a list of messages shows this message with a `deleted_at` time, "
            + "or does not show it."
        )
    )
    deleted: Literal[True] = Field(
        description=(
            "Always true, because this tool answers only after Microsoft 365 accepts the deletion. "
            + "Microsoft 365 answers a deletion with no content, so this answer repeats the "
            + "request."
        )
    )


async def delete_message(
    client: GraphServiceClient, *, handle: MessageHandle, confirm: Confirm
) -> DeletedMessage | InputRequiredResult:
    asked: InputRequiredResult | None = None
    with graph_errors(TOOL_NAME):
        found = await get_message(client, handle)
        assert found is not None, "Graph answered a message read with no message"
        current = TeamsMessage.from_message(found, handle=handle)
        if current.deleted_at is not None:
            refused = _ALREADY_DELETED
        else:
            user = await identity.signed_in_user(client)
            refused = None if sent_by(current, user) else _NOT_THE_SENDER
            if refused is None:
                with not_graph():
                    answer = await confirm(_question(current), _about(handle))
                asked = answer if isinstance(answer, InputRequiredResult) else None
                refused = answer if isinstance(answer, str) else None
            if refused is None and asked is None:
                await _soft_delete(client, handle, user)

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    return DeletedMessage(uri=handle.uri, deleted=True)


def _question(current: TeamsMessage) -> str:
    return f"Delete {message_in_question(current)}? {EVERYONE_SEES_IT}"


def _about(handle: MessageHandle) -> str:
    return confirmation_id_for(handle.uri)


def _permissions(handle: MessageHandle) -> tuple[str, ...]:
    return _CHAT_PERMISSIONS if handle.chat_id is not None else _CHANNEL_PERMISSIONS


async def _soft_delete(client: GraphServiceClient, handle: MessageHandle, user: User) -> None:
    once = RequestConfiguration[QueryParameters](options=no_retry())
    if handle.chat_id is not None:
        user_id = user.id
        assert user_id is not None, "signed_in_user answers only a user that has an id"
        chat = client.users.by_user_id(user_id).chats.by_chat_id(handle.chat_id)
        with graph_step(STEP_DELETE):
            await chat.messages.by_chat_message_id(handle.message_id).soft_delete.post(
                request_configuration=once
            )
        return
    assert handle.team_id is not None and handle.channel_id is not None, (
        "a handle addresses either a chat or a team channel"
    )
    messages = (
        client.teams.by_team_id(handle.team_id).channels.by_channel_id(handle.channel_id).messages
    )
    target = (
        messages.by_chat_message_id(handle.message_id)
        if handle.reply_to_id is None
        else messages.by_chat_message_id(handle.reply_to_id).replies.by_chat_message_id1(
            handle.message_id
        )
    )
    with graph_step(STEP_DELETE):
        await target.soft_delete.post(request_configuration=once)


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_AGREE, decline=_DECLINE, nothing_happened=_NOTHING_DELETED)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Delete a Teams Message",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE,
    )
    async def teams_delete_message(
        uri: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The message to delete, as the `uri` handle from a "
                    + "teams_list_chat_messages, teams_browse_channel, or "
                    + "teams_list_message_replies result. Copy the handle word for word."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> DeletedMessage | InputRequiredResult:
        handle = message_handle(uri)
        if handle is None:
            raise ToolError(not_a_message_handle(TOOL_NAME, _NOTHING_DELETED))
        await narrowed_to(ctx, *_permissions(handle))
        return await delete_message(client, handle=handle, confirm=a_person_agrees(ctx))
