from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.message import Message
from msgraph.generated.models.message_collection_response import MessageCollectionResponse
from msgraph.generated.users.item.mail_folders.item.messages.messages_request_builder import (
    MessagesRequestBuilder as FolderMessagesRequestBuilder,
)
from msgraph.generated.users.item.messages.item.message_item_request_builder import (
    MessageItemRequestBuilder,
)
from msgraph.generated.users.item.messages.messages_request_builder import MessagesRequestBuilder
from msgraph.generated.users.item.user_item_request_builder import UserItemRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import (
    MAX_SCANNED_ITEMS,
    CollectedItems,
    GraphNotFound,
    collect_pages,
    graph_errors,
    graph_step,
)
from office_365_mcp.shared.handles import MailMessageHandle, mail_message_handle
from office_365_mcp.shared.mail import PREVIEW_CHARACTERS, SUMMARY_FIELDS, MailSummary
from office_365_mcp.shared.odata import odata_literal
from office_365_mcp.shared.outlook.immutable_ids import immutable_id_headers
from office_365_mcp.shared.seam import (
    MAILBOX_FIELD,
    READ_ONLY,
    graph_client_for_caller,
    graph_mailbox,
)

TOOL_NAME = "outlook_read_thread"

PRESETS: tuple[str, ...] = ("outlook-read", "outlook-write", "outlook-delete", "outlook-send")

STEP_ANCHOR = "thread_anchor"
STEP_THREAD = "thread_messages"
STEP_FOLDER_THREAD = "thread_folder_messages"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Mail.Read", "Mail.Read.Shared")

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "outlook:///messages/AAMkAGI2SYNTHETIC-immutable-0001%3D"
}

_ANCHOR_FIELDS: tuple[str, ...] = ("id", "conversationId")

_THREAD_FIELDS: tuple[str, ...] = (*SUMMARY_FIELDS, "conversationId", "sentDateTime")

type _AnchorQuery = MessageItemRequestBuilder.MessageItemRequestBuilderGetQueryParameters
type _ThreadQuery = MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters
type _FolderThreadQuery = FolderMessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters

_DESCRIPTION = (
    "Lists the messages of one conversation, oldest first, in the signed-in user's own mailbox "
    "or, with `mailbox`, a shared or delegated one. Each message has only the first "
    f"{PREVIEW_CHARACTERS} characters of its body. outlook_read_mail reads the full body of one "
    "message. In a mailbox where the user has access to some folders only, it lists the "
    "conversation in the folder of the given message only."
)

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
    + "rather than refuses it. So this connector makes sure that the answer is correct, instead "
    + "of trusting it. This tool reports no thread, because the alternative is an arbitrary "
    + "slice of the mailbox presented as one. Read the messages individually with "
    + "outlook_read_mail."
)


class MailThread(BaseModel):
    messages: list[MailSummary] = Field(
        description="Every message of the conversation found in this mailbox, oldest first."
    )
    message_count: int = Field(
        description="How many messages of the conversation this tool found in this mailbox."
    )
    complete: bool = Field(
        description=(
            "False if more of the conversation remained in this mailbox when the tool stopped "
            "reading, or if the tool read one folder only."
        )
    )
    searched_scope: str = Field(
        description="Where this tool looked for these messages, and where it did not."
    )


async def read_thread(
    client: GraphServiceClient, *, handle: MailMessageHandle, mailbox: str | None = None
) -> MailThread:
    reached = graph_mailbox(client, mailbox)
    with graph_errors():
        with graph_step(STEP_ANCHOR):
            anchor = await reached.messages.by_message_id(handle.message_id).get(
                request_configuration=_anchor_request()
            )
        assert anchor is not None, "Graph answered a message read with no message"
        conversation = anchor.conversation_id
        if conversation is None:
            return _answer([], complete=True, mailbox=mailbox, folder=None)

        folder = None
        try:
            with graph_step(STEP_THREAD):
                first_page = await reached.messages.get(
                    request_configuration=_thread_request(conversation)
                )
                collected = await _all_of(first_page, client)
        except GraphNotFound:
            if mailbox is None:
                raise
            with graph_step(STEP_FOLDER_THREAD):
                folder = await _anchor_folder(reached, handle.message_id)
                if folder is None:
                    raise
                collected = await _all_of(
                    await _folder_thread(reached, folder, conversation), client
                )

    _make_sure_the_filter_was_applied(
        collected.items,
        conversation=conversation,
        anchor=handle.message_id,
        truncated=collected.capped,
    )
    return _answer(
        collected.items,
        complete=folder is None and not collected.capped,
        mailbox=mailbox,
        folder=folder,
    )


async def _all_of(
    first_page: MessageCollectionResponse | None, client: GraphServiceClient
) -> CollectedItems[Message]:
    assert first_page is not None, "Graph answered a thread listing with no collection"
    return await collect_pages(
        first_page, client, limit=MAX_SCANNED_ITEMS, headers=immutable_id_headers()
    )


async def _anchor_folder(reached: UserItemRequestBuilder, message_id: str) -> str | None:
    located = await reached.messages.by_message_id(message_id).get(
        request_configuration=RequestConfiguration[_AnchorQuery](
            query_parameters=MessageItemRequestBuilder.MessageItemRequestBuilderGetQueryParameters(
                select=["parentFolderId"]
            ),
            headers=immutable_id_headers(),
        )
    )
    return None if located is None else located.parent_folder_id


async def _folder_thread(
    reached: UserItemRequestBuilder, folder: str, conversation: str
) -> MessageCollectionResponse | None:
    return await reached.mail_folders.by_mail_folder_id(folder).messages.get(
        request_configuration=RequestConfiguration[_FolderThreadQuery](
            query_parameters=FolderMessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters(
                filter=_conversation_filter(conversation),
                select=list(_THREAD_FIELDS),
                top=MAX_SCANNED_ITEMS,
            ),
            headers=immutable_id_headers(),
        )
    )


def _make_sure_the_filter_was_applied(
    found: list[Message], *, conversation: str, anchor: str, truncated: bool
) -> None:
    if not found:
        return
    foreign = [message for message in found if message.conversation_id != conversation]
    if foreign or (not truncated and all(message.id != anchor for message in found)):
        raise ToolError(_FILTER_IGNORED)


def _answer(
    found: list[Message], *, complete: bool, mailbox: str | None, folder: str | None
) -> MailThread:
    ordered = sorted(found, key=_received_at)
    return MailThread(
        messages=[
            MailSummary.from_message(message, message_id=message.id)
            for message in ordered
            if message.id is not None
        ],
        message_count=len(ordered),
        complete=complete,
        searched_scope=_searched_scope(mailbox, folder),
    )


def _searched_scope(mailbox: str | None, folder: str | None) -> str:
    whose = "The signed-in user's own mailbox" if mailbox is None else f"The mailbox {mailbox!r}"
    if folder is not None:
        return (
            f"{whose}, only the folder of the given message, because the signed-in user has "
            + "access to some folders of this mailbox only and Microsoft 365 refused to list the "
            + "whole mailbox. Not searched: every other folder of this mailbox, so a message of "
            + "the conversation in another folder is absent."
        )
    return (
        f"{whose}, every folder of it — Sent Items, Deleted Items, and Junk Email included. Not "
        + "searched: any other participant's mailbox, any other shared or delegated mailbox, and "
        + "an in-place archive, which Microsoft Graph does not support at all. A message that was "
        + "never delivered here, or that was permanently deleted, is absent. Nobody can tell it "
        + "apart from one that never existed."
    )


def _received_at(message: Message) -> str:
    return "" if message.received_date_time is None else message.received_date_time.isoformat()


def _anchor_request() -> RequestConfiguration[_AnchorQuery]:
    return RequestConfiguration[_AnchorQuery](
        query_parameters=MessageItemRequestBuilder.MessageItemRequestBuilderGetQueryParameters(
            select=list(_ANCHOR_FIELDS)
        ),
        headers=immutable_id_headers(),
    )


def _thread_request(conversation: str) -> RequestConfiguration[_ThreadQuery]:
    return RequestConfiguration[_ThreadQuery](
        query_parameters=MessagesRequestBuilder.MessagesRequestBuilderGetQueryParameters(
            filter=_conversation_filter(conversation),
            select=list(_THREAD_FIELDS),
            top=MAX_SCANNED_ITEMS,
        ),
        headers=immutable_id_headers(),
    )


def _conversation_filter(conversation: str) -> str:
    return f"conversationId eq '{odata_literal(conversation)}'"


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Outlook: Read Mail Thread",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def outlook_read_thread(
        uri: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The `uri` of any one message of the thread, exactly as another tool "
                    "reported it."
                ),
            ),
        ],
        mailbox: Annotated[str | None, Field(min_length=1, description=MAILBOX_FIELD)] = None,
        client: GraphServiceClient = graph,
    ) -> MailThread:
        handle = mail_message_handle(uri)
        if handle is None:
            raise ToolError(_BAD_HANDLE)
        return await read_thread(client, handle=handle, mailbox=mailbox)
