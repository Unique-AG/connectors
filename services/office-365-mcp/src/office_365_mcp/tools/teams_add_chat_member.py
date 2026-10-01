import hashlib
import json
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

from office_365_mcp.graph_client import graph_errors, no_retry, not_graph
from office_365_mcp.shared.seam import (
    WRITE_ADDITIVE,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "teams_add_chat_member"

STEP = "add_chat_member"

GRAPH_PERMISSIONS: tuple[str, ...] = ("ChatMember.ReadWrite",)

CHANGE_SHOWN_BY: tuple[str, ...] = ("teams_list_chat_members",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "chat_id": "19:release@thread.v2",
    "user_id": "00000000-0000-4000-8000-000000000002",
}

_ENTRA_OBJECT_ID = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"

_OWNER = "owner"
_USER_BIND = "user@odata.bind"
_USERS = "https://graph.microsoft.com/v1.0/users/"
_VISIBLE_HISTORY = "visibleHistoryStartDateTime"
_ALL_HISTORY = "0001-01-01T00:00:00Z"

_AGREE = "add"
_DECLINE = "do not add"
_NOTHING_ADDED = "Nobody was added."
_EVERYONE_SEES_IT = "Everyone in the conversation can see this change."
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
            "True when this call let the new member see all earlier messages of the chat. False "
            + "when the new member sees only the messages that come after the addition."
        )
    )


async def add_chat_member(
    client: GraphServiceClient,
    *,
    chat_id: str,
    user_id: str,
    share_history: bool,
    confirm: Confirm,
) -> AddedChatMember | InputRequiredResult:
    with graph_errors(TOOL_NAME, step=STEP):
        with not_graph():
            answer = await confirm(
                _question(chat_id, user_id, share_history=share_history),
                _about(chat_id, user_id, share_history=share_history),
            )
        asked = answer if isinstance(answer, InputRequiredResult) else None
        refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            _ = await client.chats.by_chat_id(chat_id).members.post(
                _member(user_id, share_history=share_history),
                request_configuration=RequestConfiguration[QueryParameters](options=no_retry()),
            )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    return AddedChatMember(chat_id=chat_id, user_id=user_id, shared_history=share_history)


def _member(user_id: str, *, share_history: bool) -> AadUserConversationMember:
    bind = {_USER_BIND: f"{_USERS}{user_id}"}
    history = {_VISIBLE_HISTORY: _ALL_HISTORY} if share_history else {}
    return AadUserConversationMember(roles=[_OWNER], additional_data={**bind, **history})


def _question(chat_id: str, user_id: str, *, share_history: bool) -> str:
    history = _ALL_HISTORY_SHOWN if share_history else _NO_HISTORY_SHOWN
    return f"Add the user {user_id!r} to the Teams chat {chat_id!r}? {history} {_EVERYONE_SEES_IT}"


def _about(chat_id: str, user_id: str, *, share_history: bool) -> str:
    return hashlib.sha256(json.dumps([chat_id, user_id, share_history]).encode()).hexdigest()


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
        user_id: Annotated[
            str,
            Field(
                pattern=_ENTRA_OBJECT_ID,
                description=(
                    "The Microsoft Entra object id of the person to add, as a GUID. Copy it from "
                    + "the `user_id` of a teams_list_chat_members row, of a teams_list_chats "
                    + "member, or of a message `sender`. Never build it from a name or an email "
                    + "address."
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
                    + "that come after the addition."
                ),
            ),
        ] = False,
        client: GraphServiceClient = graph,
    ) -> AddedChatMember | InputRequiredResult:
        return await add_chat_member(
            client,
            chat_id=chat_id,
            user_id=user_id,
            share_history=share_history,
            confirm=a_person_agrees(ctx),
        )
