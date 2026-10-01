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
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, no_retry, not_graph
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "teams_remove_chat_member"

STEP = "remove_chat_member"

GRAPH_PERMISSIONS: tuple[str, ...] = ("ChatMember.ReadWrite",)

CHANGE_SHOWN_BY: tuple[str, ...] = ("teams_list_chat_members",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "chat_id": "19:release@thread.v2",
    "membership_id": (
        "MCMjU1lOVEhFVElDMCMjMTk6cmVsZWFzZUB0aHJlYWQudjIjIzAwMDAwMDAw"
        + "LTAwMDAtNDAwMC04MDAwLTAwMDAwMDAwMDAwMg=="
    ),
}

_AGREE = "remove"
_DECLINE = "do not remove"
_NOTHING_REMOVED = "Nobody was removed."
_EVERYONE_SEES_IT = "Everyone in the conversation can see this change."

_DESCRIPTION = """\
Removes one member from an existing Teams chat, as the signed-in user. The chat is the `chat_id` \
that teams_list_chats reported, and the member is a `membership_id` from teams_list_chat_members. \
Everyone in the conversation can see the change. teams_add_chat_member is the sibling tool that \
adds a member.

Notes:
- This tool asks the user to agree before it removes a member, every time. This tool removes \
nobody unless the user agrees.
- If a call times out, do not call this tool again first. Before you call again, make sure that \
teams_list_chat_members still shows the member.
- Microsoft Teams keeps the members of a `oneOnOne` chat fixed, and refuses a removal from it. \
Teams accepts at most 4 removals a minute from one chat.
"""


class RemovedChatMember(BaseModel):
    chat_id: str = Field(
        description=(
            "The chat that this call removed the member from, exactly as the call received it. "
            + "teams_list_chat_members shows the members that this chat has now."
        )
    )
    membership_id: str = Field(
        description=(
            "The membership that this call removed, exactly as the call received it. Microsoft "
            + "365 answers a removal with no content, so every field of this answer repeats the "
            + "request."
        )
    )


async def remove_chat_member(
    client: GraphServiceClient, *, chat_id: str, membership_id: str, confirm: Confirm
) -> RemovedChatMember | InputRequiredResult:
    with graph_errors(TOOL_NAME, step=STEP):
        with not_graph():
            answer = await confirm(
                _question(chat_id, membership_id), _about(chat_id, membership_id)
            )
        asked = answer if isinstance(answer, InputRequiredResult) else None
        refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            member = client.chats.by_chat_id(chat_id).members.by_conversation_member_id(
                membership_id
            )
            await member.delete(
                request_configuration=RequestConfiguration[QueryParameters](options=no_retry())
            )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    return RemovedChatMember(chat_id=chat_id, membership_id=membership_id)


def _question(chat_id: str, membership_id: str) -> str:
    return (
        f"Remove the member with the membership id {membership_id!r} from the Teams chat "
        + f"{chat_id!r}? {_EVERYONE_SEES_IT}"
    )


def _about(chat_id: str, membership_id: str) -> str:
    return hashlib.sha256(json.dumps([chat_id, membership_id]).encode()).hexdigest()


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_AGREE, decline=_DECLINE, nothing_happened=_NOTHING_REMOVED)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Remove a Teams Chat Member",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE,
    )
    async def teams_remove_chat_member(
        chat_id: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The chat to remove the member from, as the `chat_id` that teams_list_chats "
                    + "reported, for example `19:...@thread.v2`. It is not a `teams:///` handle."
                ),
            ),
        ],
        membership_id: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The membership to remove, as the `membership_id` of a teams_list_chat_members "
                    + "row for this chat. Copy it word for word. It is not the member's `user_id`."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> RemovedChatMember | InputRequiredResult:
        return await remove_chat_member(
            client, chat_id=chat_id, membership_id=membership_id, confirm=a_person_agrees(ctx)
        )
