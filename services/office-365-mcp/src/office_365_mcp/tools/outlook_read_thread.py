"""`outlook_read_thread` — every message of one conversation that is in this mailbox.

**Microsoft publishes no thread endpoint for a personal mailbox.** `conversationThread` belongs to
Microsoft 365 Groups, not to mail. What a message carries is `conversationId`, and the only route
from it to the thread is `$filter=conversationId eq '…'` — which appears in no Microsoft document.
A grep of the whole of `microsoftgraph/microsoft-graph-docs-contrib` finds zero occurrences of it.
A Microsoft SDK maintainer confirmed it works, in
https://github.com/microsoftgraph/msgraph-sdk-dotnet/issues/757, and that is the whole of the
evidence.

**So this tool verifies the filter on every call, rather than trusting it once.**
`conversationId` is a selectable property of the filtered collection. So this tool can select the
property it filtered on, and check the answer. If Graph ignored the filter, the response is an
arbitrary slice of the mailbox carrying many different conversations. Then the anchor message is
unlikely to be in it. This tool asserts both, and a failure refuses rather than answers. That is
the difference between this undocumented filter and a dangerous one. Microsoft documents `$filter`
on `/attachments` as *ignored*, and nothing in that response reveals it.

**The anchor is a message handle, not a conversation id.** Three reasons exist, and the first is
the one that matters: the check above needs a message that must be present, and only an anchor
provides one. It also keeps this tool independent of how a caller found the message. An
80-character opaque id is a hallucination surface with nothing to validate it against. A handle,
by contrast, is this connector's own grammar.

**No `$orderby`.** Rule one of Microsoft's three is that every property in `$orderby` must also
appear in `$filter`, so `$orderby=receivedDateTime desc` beside `$filter=conversationId eq …`
answers `InefficientFilter`. This tool sorts the messages here instead. A thread is small and this
cannot fail.

**A thread is this mailbox's copy of a conversation, never the conversation.** A message another
participant sent to somebody else was never in this mailbox, and one this user permanently deleted
is gone from it. The answer says which scope it searched, so a reader does not take absence as
proof.
"""

from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.headers_collection import HeadersCollection
from msgraph.generated.models.message import Message
from msgraph.generated.users.item.messages.item.message_item_request_builder import (
    MessageItemRequestBuilder,
)
from msgraph.generated.users.item.messages.messages_request_builder import MessagesRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step
from office_365_mcp.shared.handles import MailMessageHandle, mail_message_handle
from office_365_mcp.shared.mail import SUMMARY_FIELDS, MailSummary
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "outlook_read_thread"

STEP_ANCHOR = "thread_anchor"
STEP_THREAD = "thread_messages"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Mail.Read",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "outlook:///messages/AAMkAGI2SYNTHETIC-immutable-0001%3D"
}

MAX_MESSAGES = 100

# This header names the id space every handle in this connector uses. This tool sends it so one
# id space runs through the whole surface. Whether Graph also re-parses a path id in the space a
# header names is undocumented.
_PREFER_IMMUTABLE_IDS = ("Prefer", 'IdType="ImmutableId"')

_ANCHOR_FIELDS: tuple[str, ...] = ("id", "conversationId")

_THREAD_FIELDS: tuple[str, ...] = (*SUMMARY_FIELDS, "conversationId", "sentDateTime")

type _AnchorQuery = MessageItemRequestBuilder.MessageItemRequestBuilderGetQueryParameters
type _ThreadQuery = MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters

_DESCRIPTION = """\
Read every message of one conversation that this mailbox holds, oldest first, from any one message \
of it. Use it for "what happened in this thread" and for "did I ever reply". The answer spans \
Sent Items, as well as the folder the anchor is in. That is why a reply of the user's own shows \
up here, and not in a folder listing. Pass the `uri` of a hit from outlook_search_mail or a row \
from outlook_list_mail. Read `searched_scope` before reporting that something is missing: this is \
the mailbox's copy of a conversation, not the conversation.\
"""

_BAD_HANDLE = (
    "outlook_read_thread takes the `uri` of a message, which outlook_search_mail and "
    + "outlook_list_mail both report, and this is not one. A message handle is "
    + "`outlook:///messages/{id}`. Find the message first, then pass its `uri` verbatim — no "
    + "subject line, address or Outlook link becomes one."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 has no message at that handle. Graph answers a deleted message, a handle that "
    + "never named one, and a message this user cannot see with the same 404. So this tool "
    + "cannot tell which of the three it is. Search for the message again rather than reusing a "
    + "handle from earlier in the conversation."
)

_FILTER_IGNORED = (
    "Microsoft 365 answered this thread read with messages from other conversations, which means "
    + "it did not apply the filter this tool asked for. `$filter=conversationId` is not in "
    + "Microsoft's documentation. Microsoft documents that Graph ignores an unsupported filter, "
    + "rather than refuses it, so this connector checks the answer instead of trusting it. This "
    + "tool reports no thread, because the alternative is an arbitrary slice of the mailbox "
    + "presented as one. Read the messages individually with outlook_read_mail."
)


class MailThread(BaseModel):
    """One conversation as this mailbox holds it, and what that excludes."""

    messages: list[MailSummary] = Field(
        description=(
            "Every message of the conversation found in this mailbox, oldest first. Sorted here "
            + "rather than by Graph, which cannot sort a filtered collection on this property."
        )
    )
    message_count: int = Field(
        description="How many messages of the conversation this tool found in this mailbox."
    )
    complete: bool = Field(
        description=(
            "False when Graph still had more to give when this tool stopped, so the oldest part "
            + "of the thread can be missing. True means every message this mailbox holds for the "
            + "conversation is here — which is not the same as every message of the conversation."
        )
    )
    searched_scope: str = Field(
        description="Where this tool looked for these messages, and where it did not."
    )


async def read_thread(client: GraphServiceClient, *, handle: MailMessageHandle) -> MailThread:
    with graph_errors(TOOL_NAME):
        with graph_step(STEP_ANCHOR):
            anchor = await client.me.messages.by_message_id(handle.message_id).get(
                request_configuration=_anchor_request()
            )
        assert anchor is not None, "Graph answered a message read with no message"
        conversation = anchor.conversation_id
        if conversation is None:
            return _answer([], complete=True)

        with graph_step(STEP_THREAD):
            page = await client.me.messages.get(request_configuration=_thread_request(conversation))

    found = list((page.value if page is not None else None) or [])
    # Graph's own "there is more" signal, rather than a full window.
    # A page can come back short of `$top` and still carry a next link, because `$skip` counts
    # every item the service walked.
    truncated = page is not None and page.odata_next_link is not None
    _make_sure_the_filter_was_applied(
        found, conversation=conversation, anchor=handle.message_id, truncated=truncated
    )
    return _answer(found, complete=not truncated)


def _make_sure_the_filter_was_applied(
    found: list[Message], *, conversation: str, anchor: str, truncated: bool
) -> None:
    """Refuse an answer Graph did not filter.

    Two checks, and only one of them survives a truncated page. A foreign conversation proves
    Graph dropped the filter, whatever the page size. Anchor-absent is the subtler shape. It is
    what a filter applied to the wrong value looks like. Answering with it reports somebody
    else's thread as this one. But a thread longer than one page can leave the anchor off it
    honestly, with no `$orderby` to say which messages the page holds. Checking it there refuses
    a correct answer, and blames Graph for a filter it applied.
    """
    if not found:
        return
    foreign = [message for message in found if message.conversation_id != conversation]
    if foreign or (not truncated and all(message.id != anchor for message in found)):
        raise ToolError(_FILTER_IGNORED)


def _answer(found: list[Message], *, complete: bool) -> MailThread:
    ordered = sorted(found, key=_received_at)
    return MailThread(
        messages=[
            MailSummary.from_message(message, message_id=message.id)
            for message in ordered
            if message.id is not None
        ],
        message_count=len(ordered),
        complete=complete,
        searched_scope=(
            "The signed-in user's own mailbox, every folder of it including Sent Items, Deleted "
            + "Items and Junk Email. Not searched: any other participant's mailbox, a shared or "
            + "delegated mailbox, and an in-place archive, which Microsoft Graph does not support "
            + "at all. A message that was never delivered here, or that was permanently deleted, "
            + "is absent. Nobody can tell it apart from one that never existed."
        ),
    )


def _received_at(message: Message) -> str:
    """Oldest first, and a message with no received time sorts first rather than crashing the sort:
    a draft in the thread has none."""
    return "" if message.received_date_time is None else message.received_date_time.isoformat()


def _anchor_request() -> RequestConfiguration[_AnchorQuery]:
    return RequestConfiguration[_AnchorQuery](
        query_parameters=MessageItemRequestBuilder.MessageItemRequestBuilderGetQueryParameters(
            select=list(_ANCHOR_FIELDS)
        ),
        headers=_immutable_ids(),
    )


def _thread_request(conversation: str) -> RequestConfiguration[_ThreadQuery]:
    """No `$orderby`. See the module docstring."""
    return RequestConfiguration[_ThreadQuery](
        query_parameters=MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters(
            filter=f"conversationId eq '{_escaped(conversation)}'",
            select=list(_THREAD_FIELDS),
            top=MAX_MESSAGES,
        ),
        headers=_immutable_ids(),
    )


def _escaped(value: str) -> str:
    """Doubling escapes a single quote inside an OData string literal.

    Graph's ids do not carry one, so this closes a hole rather than serving a case. If an id
    ever carries one, it ends the literal.
    """
    return value.replace("'", "''")


def _immutable_ids() -> HeadersCollection:
    """Built per call: kiota's `RequestConfiguration.headers` default is one collection shared by
    every configuration in the process. So a preference added to it leaks onto every Graph call."""
    headers = HeadersCollection()
    headers.add(*_PREFER_IMMUTABLE_IDS)
    return headers


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Read Mail Thread",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def outlook_read_thread(
        uri: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The `uri` of any one message of the thread, exactly as outlook_search_mail "
                    + "or outlook_list_mail reported it. Any message of the conversation reaches "
                    + "the same thread, so the newest hit is as good as the oldest."
                ),
            ),
        ],
        client: GraphServiceClient = graph,
    ) -> MailThread:
        handle = mail_message_handle(uri)
        if handle is None:
            raise ToolError(_BAD_HANDLE)
        return await read_thread(client, handle=handle)
