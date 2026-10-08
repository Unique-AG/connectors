from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Annotated, Literal, Self

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.aad_user_conversation_member import AadUserConversationMember
from msgraph.generated.models.chat import Chat
from msgraph.generated.models.chat_type import ChatType
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared import identity
from office_365_mcp.shared.calendar import confirmation_id_for
from office_365_mcp.shared.identity import Person, person_in_question, user_bind
from office_365_mcp.shared.meetings import distinct_people, named_people
from office_365_mcp.shared.messages import CHAT_TOPIC_MAX_CHARACTERS, CHAT_TOPIC_PATTERN
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    WRITE_ADDITIVE,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "teams_create_chat"

STEP_CREATE = "create_chat"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Chat.Create", identity.GRAPH_PERMISSION)

CHANGE_SHOWN_BY: tuple[str, ...] = ("teams_list_chats",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "chat_type": "oneOnOne",
    "members": [{"user_id": "00000000-0000-4000-8000-000000000002", "name": "Grace Hopper"}],
}

type NewChatKind = Literal["oneOnOne", "group"]

_MEMBER = "#microsoft.graph.aadUserConversationMember"
_OWNER = "owner"

_CREATE = "create"
_DO_NOT_CREATE = "do not create"
_NOTHING_CREATED = "No chat was created."

_FAILS_THE_SAME_WAY = (
    "If you call this tool again with the same arguments, the call will fail the same way."
)

_DESCRIPTION = """\
Creates one Teams chat for the signed-in user with the people in `members`: a one-to-one chat \
with one other person, or a group chat. This tool adds the signed-in user to the chat, and it \
posts no message. teams_list_chats shows the new chat.

Notes:
- This tool asks the user to agree before it creates a chat, every time. This tool creates \
nothing unless the user agrees.
- The question shows the Microsoft Entra object id of each person in `members`. The `name` in the \
question is only a label.
- Only one one-to-one chat can exist between two people. If that chat exists already, Microsoft \
returns it and creates no new chat.
- If a call times out, do not call this tool again first. Before you call again, make sure that \
teams_list_chats does not already show the chat.
"""


def _not_one_other(count: int) -> str:
    return (
        f"teams_create_chat received {count} people for a one-to-one chat. A one-to-one chat "
        + "has exactly one other person. Do not include the signed-in user, because this tool "
        + "adds that user itself. For more people, set `chat_type` to `group`. "
        + f"{_NOTHING_CREATED} {_FAILS_THE_SAME_WAY}"
    )


_A_TOPIC_ON_ONE_TO_ONE = (
    "teams_create_chat received a `topic` for a one-to-one chat. Microsoft allows a topic only on "
    + "a group chat. To keep a one-to-one chat, call again without `topic`. To use a topic, set "
    + f"`chat_type` to `group`. {_NOTHING_CREATED} {_FAILS_THE_SAME_WAY}"
)

_NOBODY_ELSE = (
    "teams_create_chat received only the signed-in user in `members`. A chat needs at least one "
    + "other person. This tool adds the signed-in user itself. "
    + f"{_NOTHING_CREATED} {_FAILS_THE_SAME_WAY}"
)


class CreatedChat(BaseModel):
    chat_id: str = Field(
        description=(
            "The id that Graph gives to the chat, for example `19:...@thread.v2`. Pass this id as "
            + "`chat_id` to a tool that sends chat messages. Pass this id also to "
            + "teams_list_chat_members to see who is in the chat."
        )
    )
    chat_type: str = Field(
        description=(
            "The kind of chat that Microsoft stored, `oneOnOne` or `group`. This value comes from "
            + "the response, not from the arguments. If Graph gives a chat type that this "
            + "connector does not know, the value is `unknown`."
        )
    )
    topic: str | None = Field(
        description=(
            "The topic of the chat, as Microsoft stored it. This value comes from the response. "
            + "The value is null for a one-to-one chat and for a group chat with no topic."
        )
    )
    created_at: datetime | None = Field(
        description=(
            "When Microsoft created the chat. If the chat is one-to-one and this time is before "
            + "this call, the chat existed already. Then this call created nothing new. The value "
            + "is null when Graph gives no time."
        )
    )

    @classmethod
    def from_chat(cls, chat: Chat) -> Self:
        assert chat.id is not None, "Graph created a chat and returned no id"
        return cls(
            chat_id=chat.id,
            chat_type=chat.chat_type if chat.chat_type is not None else "unknown",
            topic=chat.topic,
            created_at=chat.created_date_time,
        )


async def create_chat(
    client: GraphServiceClient,
    *,
    chat_type: NewChatKind,
    members: Sequence[Person],
    topic: str | None = None,
    confirm: Confirm,
) -> CreatedChat | InputRequiredResult:
    given = distinct_people(members)
    refused = _refusal(chat_type, given, topic)
    if refused is not None:
        raise ToolError(refused)

    created: Chat | None = None
    asked: InputRequiredResult | None = None
    with graph_errors(TOOL_NAME):
        user = await identity.signed_in_user(client)
        assert user.id is not None, "identity.signed_in_user returned a user with no id"
        others = tuple(one for one in given if one.user_id.casefold() != user.id.casefold())
        refused = None if others else _NOBODY_ELSE
        if refused is None:
            with not_graph():
                answer = await confirm(
                    _question(chat_type, others, topic),
                    _about(chat_type, [one.user_id for one in others], topic),
                )
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with graph_step(STEP_CREATE):
                created = await client.chats.post(
                    _new_chat(chat_type, (user.id, *(one.user_id for one in others)), topic),
                    request_configuration=RequestConfiguration[QueryParameters](options=no_retry()),
                )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert created is not None, "Graph answered a chat create with no chat"
    return CreatedChat.from_chat(created)


def _refusal(chat_type: NewChatKind, given: Sequence[Person], topic: str | None) -> str | None:
    if chat_type == "oneOnOne" and len(given) != 1:
        return _not_one_other(len(given))
    if chat_type == "oneOnOne" and topic is not None:
        return _A_TOPIC_ON_ONE_TO_ONE
    return None


def _question(chat_type: NewChatKind, others: Sequence[Person], topic: str | None) -> str:
    if chat_type == "oneOnOne":
        return (
            "Create a one-to-one Teams chat with "
            + f"{person_in_question(others[0].user_id, others[0].name)}?"
        )
    named = "" if topic is None else f" named {cut_for_a_question(topic)!r}"
    return f"Create a group Teams chat{named} with {named_people(others)}?"


def _about(chat_type: NewChatKind, others: Sequence[str], topic: str | None) -> str:
    return confirmation_id_for(chat_type, str(len(others)), *sorted(others), repr(topic))


def _new_chat(chat_type: NewChatKind, members: Sequence[str], topic: str | None) -> Chat:
    return Chat(
        chat_type=ChatType(chat_type),
        topic=topic,
        members=[
            AadUserConversationMember(
                odata_type=_MEMBER,
                roles=[_OWNER],
                additional_data=user_bind(member),
            )
            for member in members
        ],
    )


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(
        ctx, agree=_CREATE, decline=_DO_NOT_CREATE, nothing_happened=_NOTHING_CREATED
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Create a Teams Chat",
        description=_DESCRIPTION,
        annotations=WRITE_ADDITIVE,
    )
    async def teams_create_chat(
        chat_type: Annotated[
            NewChatKind,
            Field(
                description=(
                    "The kind of chat to create. `oneOnOne` is a chat with exactly one other "
                    + "person. Use `group` for a chat with more people, or for a chat with a "
                    + "topic."
                ),
            ),
        ],
        members: Annotated[
            list[Person],
            Field(
                min_length=1,
                description=(
                    "The other people in the chat, with one entry for each person. Do not include "
                    + "the signed-in user, because this tool adds that user itself. This tool adds "
                    + "every person as an owner, and Microsoft accepts no in-tenant guest as an "
                    + "owner."
                ),
            ),
        ],
        ctx: Context,
        topic: Annotated[
            str | None,
            Field(
                min_length=1,
                max_length=CHAT_TOPIC_MAX_CHARACTERS,
                pattern=CHAT_TOPIC_PATTERN,
                description=(
                    "The topic of a group chat. The topic can have at most "
                    + f"{CHAT_TOPIC_MAX_CHARACTERS} characters, and it must not contain a colon "
                    + "(:). Microsoft allows a topic only on a group chat, so leave this null for "
                    + "`oneOnOne`. With `group`, a null topic creates a group chat with no topic."
                ),
            ),
        ] = None,
        client: GraphServiceClient = graph,
    ) -> CreatedChat | InputRequiredResult:
        return await create_chat(
            client,
            chat_type=chat_type,
            members=members,
            topic=topic,
            confirm=a_person_agrees(ctx),
        )
