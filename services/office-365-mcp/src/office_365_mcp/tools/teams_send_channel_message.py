"""`teams_send_channel_message` — the first write this connector puts on a Teams channel.

Posts one plain-text message to a channel that already exists
(https://learn.microsoft.com/en-us/graph/api/channel-post-messages). This route cannot create a
channel, and it cannot reply to an existing post. A reply uses a different route
(`.../messages/{message-id}/replies`) that this connector does not call. `team_id` and
`channel_id` have to be ones teams_list_my_teams and teams_list_channels already reported: there
is no other route to either.

**`ChannelMessage.Send` is the permission this call needs.** The per-route reference this tool
calls, `channel-post-messages`, names it least privileged for
`POST /teams/{team-id}/channels/{channel-id}/messages`, with `Group.ReadWrite.All` as the only
higher-privileged alternative. The permissions reference
(https://learn.microsoft.com/en-us/graph/permissions-reference) agrees: `ChannelMessage.Send` is
"Send channel messages... on behalf of the signed-in user," delegated only,
`AdminConsentRequired: No`. This is the one Teams route in this connector where two Graph
reference pages agree. Both the COMBINED "Send chatMessage in a channel or a chat" page
(`chatmessage-post`) and the per-route page name the same permission here. See
`teams_send_chat_message.py`'s module docstring for the route where they do not agree.

**`no_retry()` is what stops one message becoming two, three, or four.** The SDK retries `POST`
on 429, 503, and 504 up to three times by default (`GRAPH_MAX_RETRIES`). Graph publishes no
idempotency key for a channel message send. An unguarded retry after a lost response posts the
same words again, under the signed-in user's own name. That channel already saw the words once.
A channel post is also more durable than a chat message. It has its own `webUrl`, and it can be
searched, quoted, and replied to by anyone in the team.

**`team_id` and `channel_id` are the opaque ids `teams_list_my_teams` and `teams_list_channels`
already report, never a `teams:///` handle.** Graph's send route reads them as the same two raw
ids `teams_browse_channel.py` already takes bare. No handle family in `shared/handles.py`
addresses a channel by itself — only a message inside one — so there is nothing to mint here.

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

TOOL_NAME = "teams_send_channel_message"

STEP_SEND = "send_channel_message"

# See the module docstring: unlike the chat route, both Graph reference pages agree that this one
# needs `ChannelMessage.Send`.
GRAPH_PERMISSIONS: tuple[str, ...] = ("ChannelMessage.Send",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "team_id": "2b7c9d10-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
    "channel_id": "19:general@thread.tacv2",
    "message": "Ship it.",
}

_AGREE = "post"
_DECLINE = "do not post"
_NOTHING_SENT = "Nothing was posted."
_CANNOT_BE_RECALLED = "This cannot be recalled once posted."

_DESCRIPTION = """\
This tool posts one plain-text message to an existing Teams channel, under the signed-in user's \
own name. It cannot create a channel, and it cannot reply to an existing post — it always starts \
a new one.

Notes:
- `team_id` and `channel_id` are the ids teams_list_my_teams and teams_list_channels reported, \
copied verbatim. A team name, a channel name, and a Teams web link are not these ids, and none of \
them can be turned into one. A `channel_id` alone does not address a channel — always pass it \
with its `team_id`.
- This tool asks the user to approve the message before it posts it, every time, and it posts \
nothing unless they agree.
- A post cannot be undone. This connector has no way to edit, delete, or recall a message once \
Microsoft accepts it. Everyone in the channel can already read it.
- The message goes out as plain text. Teams renders no markdown from it, and it does not turn a \
URL in it into a clickable link.\
"""


async def send_channel_message(
    client: GraphServiceClient, *, team_id: str, channel_id: str, message: str, confirm: Confirm
) -> TeamsMessage | InputRequiredResult:
    """Put `message` to a person, then post it to the channel `team_id`/`channel_id` address.

    `confirm` has no default: the question this mints is the whole of what a person reviews
    before a post that nothing here can take back. An `InputRequiredResult` is that question,
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
            sent = await (
                client.teams.by_team_id(team_id)
                .channels.by_channel_id(channel_id)
                .messages.post(_posted(message), request_configuration=_send_request())
            )

    # Decided inside the block, raised outside it: `graph_errors` reads an escaping `ToolError` as
    # a Graph failure, and a person saying no is not one.
    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert sent is not None, "a post that nothing refused answered with no message"
    assert sent.id is not None, "Graph accepted a channel message post but returned no id"
    return TeamsMessage.from_message(
        sent, handle=MessageHandle(sent.id, team_id=team_id, channel_id=channel_id)
    )


def _question(message: str) -> str:
    return f"Post {cut_for_a_question(message)!r} to this channel now? {_CANNOT_BE_RECALLED}"


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
        title="Send a Teams Channel Message",
        description=_DESCRIPTION,
        annotations=WRITE_ADDITIVE,
    )
    async def teams_send_channel_message(
        team_id: Annotated[
            str,
            Field(
                min_length=1,
                description="The team the channel is in, exactly as teams_list_my_teams reported.",
            ),
        ],
        channel_id: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The channel to post to, exactly as teams_list_channels reported it. This "
                    + "id is opaque — copy it rather than constructing it. Always pass it with "
                    + "its `team_id`."
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
        return await send_channel_message(
            client,
            team_id=team_id,
            channel_id=channel_id,
            message=message,
            confirm=a_person_agrees(ctx),
        )
