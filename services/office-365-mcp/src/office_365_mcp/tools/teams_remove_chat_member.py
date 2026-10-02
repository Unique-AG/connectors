from collections.abc import Mapping
from contextlib import suppress
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.aad_user_conversation_member import AadUserConversationMember
from msgraph.generated.models.conversation_member import ConversationMember
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import GraphNotFound, graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.calendar import confirmation_id_for
from office_365_mcp.shared.handles import CHAT_PERMISSION
from office_365_mcp.shared.messages import EVERYONE_SEES_IT
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "teams_remove_chat_member"

STEP_READ = "chat_member"
STEP = "remove_chat_member"

GRAPH_PERMISSIONS: tuple[str, ...] = ("ChatMember.ReadWrite", CHAT_PERMISSION)

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
_NO_NAME = "a member with no name"
_FAILS_THE_SAME_WAY = (
    "If you call this tool again with the same arguments, the call will fail the same way."
)

_NO_SUCH_MEMBER = (
    "Microsoft 365 has no member with this `membership_id` in this chat. "
    + f"{_NOTHING_REMOVED} Call teams_list_chat_members to see the current members of the chat. "
    + f"Copy the `membership_id` from that list. {_FAILS_THE_SAME_WAY}"
)

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
    member = client.chats.by_chat_id(chat_id).members.by_conversation_member_id(membership_id)
    found: ConversationMember | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME):
        with suppress(GraphNotFound), graph_step(STEP_READ):
            found = await member.get()
        if found is None:
            refused = _NO_SUCH_MEMBER
        else:
            with not_graph():
                answer = await confirm(_question(found), _about(chat_id, membership_id))
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
            if refused is None and asked is None:
                with graph_step(STEP):
                    await member.delete(
                        request_configuration=RequestConfiguration[QueryParameters](
                            options=no_retry()
                        )
                    )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    return RemovedChatMember(chat_id=chat_id, membership_id=membership_id)


def _question(member: ConversationMember) -> str:
    return f"Remove {_who(member)} from the Teams chat? {EVERYONE_SEES_IT}"


def _who(member: ConversationMember) -> str:
    name = repr(cut_for_a_question(member.display_name)) if member.display_name else None
    email = (member.email if isinstance(member, AadUserConversationMember) else None) or None
    if name is None:
        return email or _NO_NAME
    return name if email is None else f"{name} ({email})"


def _about(chat_id: str, membership_id: str) -> str:
    return confirmation_id_for(chat_id, membership_id)


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
