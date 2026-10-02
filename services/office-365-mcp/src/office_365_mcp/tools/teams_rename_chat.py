from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import InputRequiredResult
from msgraph.generated.models.chat import Chat
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, not_graph
from office_365_mcp.shared.calendar import confirmation_id_for
from office_365_mcp.shared.messages import (
    CHAT_TOPIC_MAX_CHARACTERS,
    CHAT_TOPIC_PATTERN,
    EVERYONE_SEES_IT,
)
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "teams_rename_chat"

STEP = "rename_chat"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Chat.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "chat_id": "19:release@thread.v2",
    "topic": "Release planning",
}

_RENAME = "rename"
_DO_NOT_RENAME = "do not rename"
_NOTHING_RENAMED = "Nothing was renamed."

_DESCRIPTION = """\
Changes the topic of one Teams group chat, as the signed-in user. The topic is the title of the \
chat. Microsoft 365 lets this tool rename a group chat only, not a one-to-one chat or a meeting \
chat. teams_list_chats gives the `chat_id`, the `chat_type`, and the current `topic`. Everyone in \
the conversation can see the change.

Notes:
- This tool asks the user to agree before it renames a chat, every time. This tool renames \
nothing unless the user agrees.
- This call is safe to repeat after a timeout.
"""


class RenamedChat(BaseModel):
    chat_id: str = Field(
        description=(
            "The id of the chat that this call renamed, as Microsoft 365 reported it after the "
            + "change. It is the same `chat_id` that teams_list_chats reports."
        )
    )
    topic: str | None = Field(
        description=(
            "The topic of the chat, as Microsoft 365 reported it after the change. The value is "
            + "null when Microsoft 365 reported no topic."
        )
    )


async def rename_chat(
    client: GraphServiceClient, *, chat_id: str, topic: str, confirm: Confirm
) -> RenamedChat | InputRequiredResult:
    renamed: Chat | None = None
    with graph_errors(TOOL_NAME, step=STEP):
        with not_graph():
            answer = await confirm(_question(chat_id, topic), _about(chat_id, topic))
        asked = answer if isinstance(answer, InputRequiredResult) else None
        refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            renamed = await client.chats.by_chat_id(chat_id).patch(Chat(topic=topic))

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert renamed is not None, "Graph answered a chat rename with no chat"
    assert renamed.id is not None, "Graph answered a chat rename with a chat that has no id"
    return RenamedChat(chat_id=renamed.id, topic=renamed.topic)


def _question(chat_id: str, topic: str) -> str:
    return f"Rename the chat {chat_id!r} to {topic!r}? {EVERYONE_SEES_IT}"


def _about(chat_id: str, topic: str) -> str:
    return confirmation_id_for(chat_id, topic)


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(
        ctx, agree=_RENAME, decline=_DO_NOT_RENAME, nothing_happened=_NOTHING_RENAMED
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Rename a Teams Chat",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE_IDEMPOTENT,
    )
    async def teams_rename_chat(
        chat_id: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The chat to rename, as the `chat_id` that teams_list_chats reported, for "
                    + "example `19:...@thread.v2`. It is not a `teams:///` handle."
                ),
            ),
        ],
        topic: Annotated[
            str,
            Field(
                min_length=1,
                max_length=CHAT_TOPIC_MAX_CHARACTERS,
                pattern=CHAT_TOPIC_PATTERN,
                description=(
                    "The new topic of the chat, as the user writes it. The topic can have at most "
                    + f"{CHAT_TOPIC_MAX_CHARACTERS} characters, and it must not contain a colon "
                    + "(:). The `topic` of the answer is what Microsoft stored. Read it from the "
                    + "answer, not from this argument."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> RenamedChat | InputRequiredResult:
        return await rename_chat(client, chat_id=chat_id, topic=topic, confirm=a_person_agrees(ctx))
