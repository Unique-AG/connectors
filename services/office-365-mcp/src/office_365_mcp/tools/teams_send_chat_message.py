"""`teams_send_chat_message` — the first write this connector puts on a Teams chat.

Posts one plain-text message to a chat that already exists
(https://learn.microsoft.com/en-us/graph/api/chat-post-messages). This route cannot create a
chat, so `chat_id` has to be one teams_list_chats already reported — there is no other way to
come by one.

**`ChatMessage.Send` is the permission this call needs, and Graph's own docs disagree with
themselves about it.** The per-route reference this tool actually calls, `chat-post-messages`,
names `ChatMessage.Send` as least privileged for `POST /chats/{chat-id}/messages`, with
`Chat.ReadWrite` and `Group.ReadWrite.All` as the higher-privileged alternatives. The permissions
reference (https://learn.microsoft.com/en-us/graph/permissions-reference) agrees: `ChatMessage.Send`
is "Send user chat messages... on behalf of the signed-in user," delegated only,
`AdminConsentRequired: No`. The COMBINED "Send chatMessage in a channel or a chat" page
(`chatmessage-post`) is not the page this tool cites. That combined page instead lists
`ChannelMessage.Send` under its own "Permissions for chat" heading. This heading is the same
table as its "Permissions for channel" heading, character for character. That is a copy-paste in
Microsoft's docs, not a second valid answer. `teams_send_channel_message.py` needs
`ChannelMessage.Send` for the channel route. This tool's own route needs `ChatMessage.Send`
instead, confirmed by both of the sources above.

**`no_retry()` is what stops one message becoming two, three, or four.** The SDK retries `POST`
on 429, 503, and 504 up to three times by default (`GRAPH_MAX_RETRIES`). Graph publishes no
idempotency key for a chat message send. An unguarded retry after a lost response posts the same
words again, under the signed-in user's own name. Those people already read the words once.
`tests/graph_client/test_client.py::TestANonIdempotentCallIsNotRetried` proves the default this
overrides.

**`chat_id` is the opaque id `teams_list_chats` already reports, never a `teams:///` handle.**
Graph's send route reads it as a raw chat id (`19:...@thread.v2`), the same string
`teams_read_message.py` reads off a `MessageHandle.chat_id`. No handle family in
`shared/handles.py` addresses a chat by itself. Only a message, a meeting, or a transcript
*inside* one has a handle. So there is nothing to mint here. An invented `teams:///chats/{id}`
wrapper adds a second, competing spelling for an id that every other Teams tool already takes
bare.

**A person approves before anything goes out, every time.** There is no draft to review first:
the confirmation question IS the review. `person_confirms` (`shared/seam.py`) is the one seam
this connector puts a question through, on either protocol era. This tool asks nothing of Graph
until that answer comes back `agree`.
"""

from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.body_type import BodyType
from msgraph.generated.models.chat_message import ChatMessage
from msgraph.generated.models.item_body import ItemBody
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import graph_errors, no_retry, not_graph
from office_365_mcp.shared.handles import MessageHandle
from office_365_mcp.shared.messages import TeamsMessage
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    WRITE_ADDITIVE,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "teams_send_chat_message"

STEP_SEND = "send_chat_message"

# See the module docstring: the combined "Send chatMessage in a channel or a chat" reference page
# names `ChannelMessage.Send` here too. It copies its channel table into its chat section. The
# per-route page (`chat-post-messages`) and the permissions reference both name `ChatMessage.Send`
# instead, and that is the one this tool declares.
GRAPH_PERMISSIONS: tuple[str, ...] = ("ChatMessage.Send",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "chat_id": "19:release@thread.v2",
    "message": "Ship it.",
}

_AGREE = "send"
_DECLINE = "do not send"
_NOTHING_SENT = "Nothing was sent."
_CANNOT_BE_RECALLED = "This cannot be recalled once sent."

_DESCRIPTION = """\
This tool posts one plain-text message to an existing Teams chat — a one-to-one or a group chat \
— under the signed-in user's own name. It cannot create a chat, and it cannot add anyone to one.

Notes:
- `chat_id` is the id teams_list_chats reported for the chat, copied verbatim. A chat topic, a \
member's name, and a Teams web link are not this id, and none of them can be turned into one.
- This tool asks the user to approve the message before it sends it, every time, and it sends \
nothing unless they agree.
- A send cannot be undone. This connector has no way to edit, delete, or recall a message once \
Microsoft accepts it.
- The message goes out as plain text. Teams renders no markdown from it, and it does not turn a \
URL in it into a clickable link.\
"""


async def send_chat_message(
    client: GraphServiceClient, *, chat_id: str, message: str, confirm: Confirm
) -> TeamsMessage | InputRequiredResult:
    """Put `message` to a person, then post it to the chat `chat_id` addresses.

    `confirm` has no default: the question this mints is the whole of what a person reviews
    before a send that nothing here can take back. An `InputRequiredResult` is that question,
    returned unsent for a client with no back-channel to answer and re-call.
    """
    question = _question(message)
    sent: ChatMessage | None = None
    asked: InputRequiredResult | None = None
    with graph_errors(TOOL_NAME, step=STEP_SEND):
        with not_graph():
            answer = await confirm(question, question)
        asked = answer if isinstance(answer, InputRequiredResult) else None
        refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            sent = await client.chats.by_chat_id(chat_id).messages.post(
                _posted(message), request_configuration=_send_request()
            )

    # Decided inside the block, raised outside it: `graph_errors` reads an escaping `ToolError` as
    # a Graph failure, and a person saying no is not one.
    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert sent is not None, "a send that nothing refused answered with no message"
    assert sent.id is not None, "Graph accepted a chat message post but returned no id"
    return TeamsMessage.from_message(sent, handle=MessageHandle(sent.id, chat_id=chat_id))


def _question(message: str) -> str:
    return f"Send {cut_for_a_question(message)!r} to this chat now? {_CANNOT_BE_RECALLED}"


def _posted(message: str) -> ChatMessage:
    return ChatMessage(body=ItemBody(content=message, content_type=BodyType.Text))


def _send_request() -> RequestConfiguration[QueryParameters]:
    """`no_retry()` is what stops one message becoming two, three, or four posts. See the module
    docstring."""
    return RequestConfiguration[QueryParameters](options=no_retry())


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_AGREE, decline=_DECLINE, nothing_happened=_NOTHING_SENT)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Send a Teams Chat Message",
        description=_DESCRIPTION,
        annotations=WRITE_ADDITIVE,
    )
    async def teams_send_chat_message(
        chat_id: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The chat to post to, exactly as teams_list_chats reported its `chat_id`. "
                    + "This id is opaque — copy it rather than constructing it."
                ),
            ),
        ],
        message: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The message to send, as plain text. Teams applies no formatting to it: no "
                    + "markdown, no rendered links, no line-break markup beyond the newlines "
                    + "already in the string."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> TeamsMessage | InputRequiredResult:
        return await send_chat_message(
            client, chat_id=chat_id, message=message, confirm=a_person_agrees(ctx)
        )
