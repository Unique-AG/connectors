from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.aad_user_conversation_member import AadUserConversationMember
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.calendar import confirmation_id_for
from office_365_mcp.shared.handles import CHAT_PERMISSION
from office_365_mcp.shared.identity import Person, person_in_question, user_bind
from office_365_mcp.shared.messages import EVERYONE_SEES_IT, chat_in_question
from office_365_mcp.shared.seam import (
    WRITE_ADDITIVE,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "teams_add_chat_member"

STEP = "add_chat_member"

GRAPH_PERMISSIONS: tuple[str, ...] = ("ChatMember.ReadWrite", CHAT_PERMISSION)

CHANGE_SHOWN_BY: tuple[str, ...] = ("teams_list_chat_members",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "chat_id": "19:release@thread.v2",
    "member": {"user_id": "00000000-0000-4000-8000-000000000002", "name": "Grace Hopper"},
}

_OWNER = "owner"
_VISIBLE_HISTORY = "visibleHistoryStartDateTime"
_ALL_HISTORY = "0001-01-01T00:00:00Z"

_AGREE = "add"
_DECLINE = "do not add"
_NOTHING_ADDED = "Nobody was added."
_ALL_HISTORY_SHOWN = "The new member will see all earlier messages of the chat."
_NO_HISTORY_SHOWN = "The new member will not see the earlier messages of the chat."

_DESCRIPTION = """\
Adds one person to an existing Teams chat, as the signed-in user. The chat is the `chat_id` that \
teams_list_chats or teams_create_chat reported. The new member gets the `owner` role. Everyone in \
the conversation can see the change. teams_remove_chat_member is the sibling tool that removes a \
member.

Notes:
- This tool asks the user to agree before it adds a member, every time. This tool adds nobody \
unless the user agrees.
- The question shows the Microsoft Entra object id of the person in `member`. The `name` in the \
question is only a label.
- If a call times out, do not call this tool again first. Before you call again, make sure that \
teams_list_chat_members does not already show the member.
- Microsoft Teams keeps the members of a `oneOnOne` chat fixed, and refuses an addition to it. \
Teams accepts at most 4 additions a minute to one chat.
"""


class AddedChatMember(BaseModel):
    chat_id: str = Field(
        description="The chat that this call added the person to, exactly as the call received it."
    )
    user_id: str = Field(
        description=(
            "The Microsoft Entra object id of the person that this call added. Microsoft 365 "
            + "answers an addition with no member, so every field of this answer repeats the "
            + "request. teams_list_chat_members shows the `membership_id` of the new member."
        )
    )
    shared_history: bool = Field(
        description=(
            "The value is true when this call let the new member see all earlier messages of the "
            + "chat. The value is false when the new member sees only the messages after the "
            + "addition."
        )
    )


async def add_chat_member(
    client: GraphServiceClient,
    *,
    chat_id: str,
    member: Person,
    share_history: bool,
    confirm: Confirm,
) -> AddedChatMember | InputRequiredResult:
    with graph_errors(TOOL_NAME):
        chat = await chat_in_question(client, chat_id)
        with not_graph():
            answer = await confirm(
                _question(member, chat, share_history=share_history),
                _about(chat_id, member.user_id, share_history=share_history),
            )
        asked = answer if isinstance(answer, InputRequiredResult) else None
        refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with graph_step(STEP):
                _ = await client.chats.by_chat_id(chat_id).members.post(
                    _member(member.user_id, share_history=share_history),
                    request_configuration=RequestConfiguration[QueryParameters](options=no_retry()),
                )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    return AddedChatMember(chat_id=chat_id, user_id=member.user_id, shared_history=share_history)


def _member(user_id: str, *, share_history: bool) -> AadUserConversationMember:
    history = {_VISIBLE_HISTORY: _ALL_HISTORY} if share_history else {}
    return AadUserConversationMember(
        roles=[_OWNER], additional_data={**user_bind(user_id), **history}
    )


def _question(member: Person, chat: str, *, share_history: bool) -> str:
    history = _ALL_HISTORY_SHOWN if share_history else _NO_HISTORY_SHOWN
    person = person_in_question(member.user_id, member.name)
    return f"Add {person} to {chat}? {history} {EVERYONE_SEES_IT}"


def _about(chat_id: str, user_id: str, *, share_history: bool) -> str:
    return confirmation_id_for(chat_id, user_id, repr(share_history))


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_AGREE, decline=_DECLINE, nothing_happened=_NOTHING_ADDED)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Add a Teams Chat Member",
        description=_DESCRIPTION,
        annotations=WRITE_ADDITIVE,
    )
    async def teams_add_chat_member(
        chat_id: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The chat to add the person to, as the `chat_id` that teams_list_chats or "
                    + "teams_create_chat reported, for example `19:...@thread.v2`. It is not a "
                    + "`teams:///` handle."
                ),
            ),
        ],
        member: Annotated[
            Person,
            Field(
                description=(
                    "The person to add to the chat. This tool adds the person as an owner, and "
                    + "Microsoft accepts no in-tenant guest as an owner."
                ),
            ),
        ],
        ctx: Context,
        share_history: Annotated[
            bool,
            Field(
                description=(
                    "Set this parameter to true to let the new member see all earlier messages "
                    + "of the chat. The default, false, lets the new member see only the messages "
                    + "after the addition."
                ),
            ),
        ] = False,
        client: GraphServiceClient = graph,
    ) -> AddedChatMember | InputRequiredResult:
        return await add_chat_member(
            client,
            chat_id=chat_id,
            member=member,
            share_history=share_history,
            confirm=a_person_agrees(ctx),
        )
