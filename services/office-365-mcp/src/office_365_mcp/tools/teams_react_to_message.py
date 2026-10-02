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
from msgraph.generated.teams.item.channels.item.channel_item_request_builder import (
    ChannelItemRequestBuilder as ChannelRequestBuilder,
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
from msgraph.generated.teams.item.team_item_request_builder import (
    TeamItemRequestBuilder as TeamRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.calendar import confirmation_id_for
from office_365_mcp.shared.handles import (
    CHAT_PERMISSION,
    MessageHandle,
    message_handle,
    not_a_message_handle,
)
from office_365_mcp.shared.messages import (
    EVERYONE_SEES_IT,
    TeamsMessage,
    get_message,
    message_in_question,
)
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE,
    Confirm,
    graph_client_for_caller,
    narrowed_to,
    person_confirms,
)

TOOL_NAME = "teams_react_to_message"

STEP_CHANNEL = "channel"
STEP_TEAM = "team"
STEP_REACT = "react_to_message"

_CHAT_SEND = "ChatMessage.Send"
_CHANNEL_SEND = "ChannelMessage.Send"
_READ_CHANNEL = "Channel.ReadBasic.All"
_READ_TEAM = "Team.ReadBasic.All"

_CHAT_PERMISSIONS: tuple[str, ...] = (_CHAT_SEND, CHAT_PERMISSION)
_CHANNEL_PERMISSIONS: tuple[str, ...] = (_CHANNEL_SEND, _READ_CHANNEL, _READ_TEAM)

GRAPH_PERMISSIONS: tuple[str, ...] = (
    _CHAT_SEND,
    _CHANNEL_SEND,
    CHAT_PERMISSION,
    _READ_CHANNEL,
    _READ_TEAM,
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
    "reaction": "\U0001f44d",
}

_NOTHING_CHANGED = "No reaction was changed."

_ALREADY_DELETED = (
    f"This message is already deleted. {_NOTHING_CHANGED} If you call this tool again with this "
    + "handle, the call will fail the same way."
)

_DESCRIPTION = """\
Adds or removes one reaction on one Teams message, as the signed-in user. The message can be a \
chat message, a channel post, or a reply to a channel post. Everyone in the conversation can see \
the change. teams_list_chat_messages shows the reactions of a chat message.

Notes:
- This tool asks the user to agree before it changes a reaction, every time. This tool changes \
nothing unless the user agrees.
- For a chat message, the question names the sender and the text. For a channel post or a reply, \
the question names only the channel and the team.
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

type _ChannelQuery = ChannelRequestBuilder.ChannelItemRequestBuilderGetQueryParameters
type _TeamQuery = TeamRequestBuilder.TeamItemRequestBuilderGetQueryParameters


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
    asked: InputRequiredResult | None = None
    with graph_errors(TOOL_NAME):
        target = await _target(client, handle)
        refused = _ALREADY_DELETED if target is None else None
        if target is not None:
            with not_graph():
                answer = await confirm(
                    _question(target, reaction, remove=remove),
                    confirmation_id_for(handle.uri, reaction, repr(remove)),
                )
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with graph_step(STEP_REACT):
                await _react(client, handle, reaction=reaction, remove=remove)

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    return ChangedReaction(uri=handle.uri, reaction=reaction, removed=remove)


async def _target(client: GraphServiceClient, handle: MessageHandle) -> str | None:
    if handle.chat_id is None:
        return await _channel_target(client, handle)
    found = await get_message(client, handle)
    assert found is not None, "Graph answered a message read with no message"
    message = TeamsMessage.from_message(found, handle=handle)
    if message.deleted_at is not None:
        return None
    return message_in_question(message)


async def _channel_target(client: GraphServiceClient, handle: MessageHandle) -> str:
    assert handle.team_id is not None and handle.channel_id is not None, (
        "a handle addresses either a chat or a team channel"
    )
    team = client.teams.by_team_id(handle.team_id)
    with graph_step(STEP_CHANNEL):
        channel = await team.channels.by_channel_id(handle.channel_id).get(
            request_configuration=RequestConfiguration[_ChannelQuery](
                query_parameters=ChannelRequestBuilder.ChannelItemRequestBuilderGetQueryParameters(
                    select=["displayName"]
                )
            )
        )
    with graph_step(STEP_TEAM):
        found_team = await team.get(
            request_configuration=RequestConfiguration[_TeamQuery](
                query_parameters=TeamRequestBuilder.TeamItemRequestBuilderGetQueryParameters(
                    select=["displayName"]
                )
            )
        )
    channel_name = (channel.display_name if channel is not None else None) or handle.channel_id
    team_name = (found_team.display_name if found_team is not None else None) or handle.team_id
    kind = "a reply" if handle.reply_to_id is not None else "a post"
    return (
        f"{kind} in the channel {cut_for_a_question(channel_name)!r} of the team "
        + f"{cut_for_a_question(team_name)!r}"
    )


def _question(target: str, reaction: str, *, remove: bool) -> str:
    shown = cut_for_a_question(reaction)
    change = f"Remove the reaction {shown!r} from" if remove else f"Add the reaction {shown!r} to"
    return f"{change} {target}? {EVERYONE_SEES_IT}"


def _permissions(handle: MessageHandle) -> tuple[str, ...]:
    return _CHAT_PERMISSIONS if handle.chat_id is not None else _CHANNEL_PERMISSIONS


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
                    "The message to react to, as the `uri` of a teams_list_chat_messages row, or "
                    + "the `uri` of a message from another Teams tool. Copy the handle word for "
                    + "word."
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
        await narrowed_to(ctx, *_permissions(handle))
        return await react_to_message(
            client,
            handle=handle,
            reaction=reaction,
            remove=remove,
            confirm=a_person_agrees(ctx, remove=remove),
        )
