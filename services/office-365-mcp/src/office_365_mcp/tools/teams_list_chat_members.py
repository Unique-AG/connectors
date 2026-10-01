from collections.abc import Mapping
from typing import Annotated, Self

import httpx
from fastmcp import FastMCP
from msgraph.generated.models.aad_user_conversation_member import AadUserConversationMember
from msgraph.generated.models.conversation_member import ConversationMember
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors
from office_365_mcp.shared.handles import CHAT_PERMISSION
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "teams_list_chat_members"

STEP = "chat_members"

GRAPH_PERMISSIONS: tuple[str, ...] = (CHAT_PERMISSION,)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"chat_id": "19:release@thread.v2"}

_DESCRIPTION = """\
Lists the members of one Teams chat of the signed-in user, by the `chat_id` that teams_list_chats \
reported. Each row names one member with a `user_id`, a `display_name`, an `email`, and `roles`. \
teams_list_chats is the sibling tool that lists the chats. That tool shows members only for \
unnamed chats.

Notes:
- This tool reads one page of members. If `more_members` is true, the chat has members that this \
list does not show. Calling it again returns the same members.
- A member without a Microsoft Entra account, such as an anonymous guest, has a null `user_id` and \
a null `email`.\
"""


class ChatMembership(BaseModel):
    membership_id: str = Field(
        description=(
            "The id that Microsoft uses for this membership in this chat. This id is opaque, so "
            + "copy it as it is and never parse it. It is not the member's `user_id`."
        )
    )
    user_id: str | None = Field(
        description=(
            "The member's Microsoft Entra object id. It is the same id as `user_id` in get_me and "
            + "in a message mention. Null for a member without a Microsoft Entra account, such as "
            + "an anonymous guest."
        )
    )
    display_name: str | None = Field(
        description=(
            "The member's display name as Teams shows it. Null if Microsoft gives none. Two "
            + "members can share one name, so match a person by `user_id`."
        )
    )
    email: str | None = Field(
        description=(
            "The member's email address. Null for a member without a Microsoft Entra account, "
            + "and null when Microsoft gives no address."
        )
    )
    roles: list[str] = Field(
        description=(
            "The roles that Microsoft records for this member. `owner` marks an owner of the "
            + "chat. Microsoft also records `owner` for an external member from another tenant. "
            + "`guest` marks an in-tenant guest. An empty list means an ordinary member."
        )
    )

    @classmethod
    def from_conversation_member(cls, member: ConversationMember) -> Self:
        assert member.id is not None, "Graph returned a chat member with no id"
        entra = member if isinstance(member, AadUserConversationMember) else None
        return cls(
            membership_id=member.id,
            user_id=entra.user_id if entra is not None else None,
            display_name=member.display_name,
            email=entra.email if entra is not None else None,
            roles=member.roles or [],
        )


class ChatMembers(BaseModel):
    members: list[ChatMembership] = Field(
        description=(
            "The members of the chat, in the order that Microsoft returned them. Match the "
            + "signed-in user by `user_id` against get_me."
        )
    )
    more_members: bool = Field(
        description=(
            "True when Microsoft reported more members after this page. This call reads one page "
            + "only, so `members` is then incomplete. False means that `members` is the complete "
            + "list."
        )
    )


async def teams_list_chat_members(client: GraphServiceClient, *, chat_id: str) -> ChatMembers:
    with graph_errors(TOOL_NAME, step=STEP):
        page = await client.chats.by_chat_id(chat_id).members.get()
        assert page is not None, "Graph answered a chat member listing with no collection"

    return ChatMembers(
        members=[ChatMembership.from_conversation_member(member) for member in page.value or []],
        more_members=bool(page.odata_next_link),
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="List a Chat's Members",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def list_chat_members(
        chat_id: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The chat whose members to list, as the `chat_id` that teams_list_chats "
                    + "reported, for example `19:...@thread.v2`. It is not a `teams:///` handle."
                ),
            ),
        ],
        client: GraphServiceClient = graph,
    ) -> ChatMembers:
        return await teams_list_chat_members(client, chat_id=chat_id)
