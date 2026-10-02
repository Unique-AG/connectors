from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.chats.item.messages.item.set_reaction import (
    set_reaction_post_request_body as _chat_set,
)
from msgraph.generated.chats.item.messages.item.unset_reaction import (
    unset_reaction_post_request_body as _chat_unset,
)
from msgraph.generated.teams.item.channels.item.messages.item.replies.item.set_reaction import (
    set_reaction_post_request_body as _reply_set,
)
from msgraph.generated.teams.item.channels.item.messages.item.replies.item.unset_reaction import (
    unset_reaction_post_request_body as _reply_unset,
)
from msgraph.generated.teams.item.channels.item.messages.item.set_reaction import (
    set_reaction_post_request_body as _channel_set,
)
from msgraph.generated.teams.item.channels.item.messages.item.unset_reaction import (
    unset_reaction_post_request_body as _channel_unset,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, no_retry, not_graph
from office_365_mcp.shared.calendar import confirmation_id_for
from office_365_mcp.shared.handles import MessageHandle, message_handle, not_a_message_handle
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE,
    Confirm,
    graph_client_for_caller,
    narrowed_to,
    person_confirms,
)

TOOL_NAME = "teams_react_to_message"

STEP_REACT = "react_to_message"

_CHAT_SEND = "ChatMessage.Send"
_CHANNEL_SEND = "ChannelMessage.Send"

GRAPH_PERMISSIONS: tuple[str, ...] = (_CHAT_SEND, _CHANNEL_SEND)

GRAPH_CALL_NARROWS_TO: tuple[str, ...] = (_CHAT_SEND,)

CHANGE_SHOWN_BY: tuple[str, ...] = (
    "teams_read_message",
    "teams_list_chat_messages",
    "teams_browse_channel",
    "teams_list_message_replies",
)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000",
    "reaction": "\U0001f44d",
}

_NOTHING_CHANGED = "No reaction was changed."
_EVERYONE_SEES_IT = "Everyone in the conversation can see this change."

_DESCRIPTION = """\
Adds or removes one reaction on one Teams message, as the signed-in user. The message can be a \
chat message, a channel post, or a reply to a channel post. Everyone in the conversation can see \
the change. teams_list_chat_messages and teams_read_message show the reactions of a message.

Notes:
- This tool asks the user to agree before it changes a reaction, every time. This tool changes \
nothing unless the user agrees.
- If a call times out, do not call this tool again first. Before you call again, make sure that \
the conversation does not already show the change.
"""

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not find this message, and no reaction was changed. The handle is well "
    + "formed, so the argument is not the problem. Graph answers a deleted message and a message "
    + "that the signed-in user cannot see with the same 404. A search hit that is a channel reply "
    + "can carry a handle that does not address the reply. teams_browse_channel and "
    + "teams_list_message_replies give the handle of a reply. If you call this tool again with "
    + "this handle, the call will fail the same way."
)


class ChangedReaction(BaseModel):
    uri: str = Field(
        description=(
            "The handle of the message that this call changed. For a chat message, "
            + "teams_list_chat_messages shows the reactions that the message has now."
        )
    )
    reaction: str = Field(
        description=(
            "The reaction that this call sent, exactly as the call received it. Microsoft 365 "
            + "answers a reaction change with no content, so every field of this answer repeats "
            + "the request."
        )
    )
    removed: bool = Field(
        description=(
            "True when this call removed the reaction from the message. False when this call "
            + "added the reaction to the message."
        )
    )


async def react_to_message(
    client: GraphServiceClient,
    *,
    handle: MessageHandle,
    reaction: str,
    remove: bool,
    confirm: Confirm,
) -> ChangedReaction | InputRequiredResult:
    with graph_errors(TOOL_NAME, step=STEP_REACT):
        with not_graph():
            answer = await confirm(
                _question(handle, reaction, remove=remove),
                confirmation_id_for(handle.uri, reaction, repr(remove)),
            )
        asked = answer if isinstance(answer, InputRequiredResult) else None
        refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            await _react(client, handle, reaction=reaction, remove=remove)

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    return ChangedReaction(uri=handle.uri, reaction=reaction, removed=remove)


def _question(handle: MessageHandle, reaction: str, *, remove: bool) -> str:
    shown = cut_for_a_question(reaction)
    change = f"Remove the reaction {shown!r} from" if remove else f"Add the reaction {shown!r} to"
    return f"{change} the Teams message {handle.uri}? {_EVERYONE_SEES_IT}"


def _permission(handle: MessageHandle) -> str:
    return _CHAT_SEND if handle.chat_id is not None else _CHANNEL_SEND


async def _react(
    client: GraphServiceClient, handle: MessageHandle, *, reaction: str, remove: bool
) -> None:
    once = RequestConfiguration[QueryParameters](options=no_retry())
    if handle.chat_id is not None:
        chat = client.chats.by_chat_id(handle.chat_id).messages.by_chat_message_id(
            handle.message_id
        )
        if remove:
            await chat.unset_reaction.post(
                _chat_unset.UnsetReactionPostRequestBody(reaction_type=reaction),
                request_configuration=once,
            )
        else:
            await chat.set_reaction.post(
                _chat_set.SetReactionPostRequestBody(reaction_type=reaction),
                request_configuration=once,
            )
        return
    assert handle.team_id is not None and handle.channel_id is not None, (
        "a handle addresses either a chat or a team channel"
    )
    messages = (
        client.teams.by_team_id(handle.team_id).channels.by_channel_id(handle.channel_id).messages
    )
    if handle.reply_to_id is not None:
        reply = messages.by_chat_message_id(handle.reply_to_id).replies.by_chat_message_id1(
            handle.message_id
        )
        if remove:
            await reply.unset_reaction.post(
                _reply_unset.UnsetReactionPostRequestBody(reaction_type=reaction),
                request_configuration=once,
            )
        else:
            await reply.set_reaction.post(
                _reply_set.SetReactionPostRequestBody(reaction_type=reaction),
                request_configuration=once,
            )
        return
    post = messages.by_chat_message_id(handle.message_id)
    if remove:
        await post.unset_reaction.post(
            _channel_unset.UnsetReactionPostRequestBody(reaction_type=reaction),
            request_configuration=once,
        )
    else:
        await post.set_reaction.post(
            _channel_set.SetReactionPostRequestBody(reaction_type=reaction),
            request_configuration=once,
        )


def a_person_agrees(ctx: Context, *, remove: bool) -> Confirm:
    agree = "remove" if remove else "add"
    return person_confirms(
        ctx, agree=agree, decline=f"do not {agree}", nothing_happened=_NOTHING_CHANGED
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="React to a Teams Message",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE,
    )
    async def teams_react_to_message(
        uri: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The message to react to, as the `uri` handle from a "
                    + "teams_list_chat_messages, teams_browse_channel, teams_list_message_replies, "
                    + "teams_search_messages, or teams_read_message result. Copy the handle word "
                    + "for word."
                ),
            ),
        ],
        reaction: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The reaction, as one emoji, for example \U0001f44d. Microsoft 365 takes the "
                    + "reaction as unicode text. To remove a reaction, give the same emoji that "
                    + "was added."
                ),
            ),
        ],
        ctx: Context,
        remove: Annotated[
            bool,
            Field(
                description=(
                    "Set this parameter to true to remove the reaction from the message. The "
                    + "default, false, adds the reaction to the message."
                ),
            ),
        ] = False,
        client: GraphServiceClient = graph,
    ) -> ChangedReaction | InputRequiredResult:
        handle = message_handle(uri)
        if handle is None:
            raise ToolError(not_a_message_handle(TOOL_NAME, _NOTHING_CHANGED))
        await narrowed_to(ctx, _permission(handle))
        return await react_to_message(
            client,
            handle=handle,
            reaction=reaction,
            remove=remove,
            confirm=a_person_agrees(ctx, remove=remove),
        )
