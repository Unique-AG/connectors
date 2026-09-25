from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from kiota_abstractions.headers_collection import HeadersCollection
from msgraph.generated.models.mail_folder import MailFolder
from msgraph.generated.models.mail_search_folder import MailSearchFolder
from msgraph.generated.users.item.messages.item.move.move_post_request_body import (
    MovePostRequestBody,
)
from msgraph.generated.users.item.user_item_request_builder import UserItemRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import GraphFailure, graph_errors, graph_step, no_retry
from office_365_mcp.shared.handles import (
    MailFolderHandle,
    MailMessageHandle,
    mail_folder_handle,
    mail_message_handle,
)
from office_365_mcp.shared.mail import WellKnownFolder
from office_365_mcp.shared.seam import (
    MAILBOX_FIELD,
    WRITE_DESTRUCTIVE,
    graph_client_for_caller,
    graph_mailbox,
)

TOOL_NAME = "outlook_move_mail"

STEP_DESTINATION = "destination_folder"
STEP_MOVE = "move_message"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Mail.ReadWrite", "Mail.ReadWrite.Shared")

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "message_refs": ["outlook:///messages/AAMkAGI2SYNTHETIC-immutable-0001%3D"],
    "destination": "archive",
}

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return the item this move addressed, and nothing moved. If "
    + "`folder_ref` was used, the destination is the likelier cause: the handle is well formed. "
    + "So the folder was most likely deleted, moved, or copied, and given a new id. Call "
    + "outlook_browse_folders again, and take the `uri` it reports now. Otherwise, a message "
    + "handle is stale. That is exactly what a stale handle looks like for a message that "
    + "already moved. Find the message again with outlook_search_mail, and move the `uri` that "
    + "search returns. Retrying with these arguments will fail identically."
)

MAX_MESSAGES = 20

_SEARCH_FOLDER_ONLY: frozenset[str] = frozenset(
    MailSearchFolder().get_field_deserializers()
) - frozenset(MailFolder().get_field_deserializers())

assert _SEARCH_FOLDER_ONLY, (
    "MailSearchFolder declares no property of its own, so the destination check below accepts "
    "every search folder silently"
)

_PREFER_IMMUTABLE_IDS = ("Prefer", 'IdType="ImmutableId"')


_DESCRIPTION = (
    f"Moves up to {MAX_MESSAGES} messages into another folder, in the signed-in user's own "
    "mailbox or, with `mailbox`, a shared or delegated one — moving to `deleteditems` is the "
    "only way this connector erases mail, and the message stays recoverable in Deleted Items "
    "because there is no permanent-erase operation."
)

_BOTH_DESTINATIONS = (
    "outlook_move_mail moves mail into one folder, so `destination` and `folder_ref` are "
    + "alternatives, not a pair. `destination` names a well-known folder such as `deleteditems`. "
    + "`folder_ref` addresses any folder, by the handle outlook_browse_folders reported for it. "
    + "Pass whichever one names the folder the mail belongs in, and omit the other entirely. "
    + "Nothing was moved."
)

_NO_DESTINATION = (
    "outlook_move_mail was given no destination, so there was nowhere to move the mail, and "
    + "nothing moved. Pass `destination` for a well-known folder: `inbox`, `sentitems`, "
    + "`drafts`, `archive`, `deleteditems`, `junkemail` or `clutter`. `deleteditems` is how a "
    + "message is removed here. Or pass `folder_ref` for any other folder, which is the `uri` "
    + "of an outlook_browse_folders result. Pass exactly one of the two, never neither."
)

_NOT_A_FOLDER_HANDLE = (
    "outlook_move_mail takes a folder handle in `folder_ref`: outlook:///folders/{id}, exactly "
    + "as outlook_browse_folders reported it in `uri`. A folder's name is not one, and neither "
    + "is a message handle. For Deleted Items and the other well-known folders, use "
    + "`destination` instead. It takes names such as `deleteditems` and `archive`. Nothing was "
    + "moved."
)

_NOT_A_MESSAGE_HANDLE = (
    "outlook_move_mail takes message handles in `message_refs`: outlook:///messages/{id}, "
    + "exactly as outlook_search_mail, outlook_list_mail or outlook_read_thread reported them "
    + "in `uri`. One of these is not a handle. A subject line, an email address, an Outlook web "
    + "link and a bare message id are not handles. Neither is a folder, draft or rule handle "
    + "under the same scheme. This tool makes sure that every handle is valid before any "
    + "message moves, so nothing moved. Fix the value and call again with the whole batch."
)

_HIDDEN_DESTINATION = (
    "That folder is hidden from the user in Outlook, so mail moved into it disappears from "
    + "their view, without being deleted. outlook_move_mail will not file mail there. "
    + "Nothing was moved. Pick a folder the user can see: outlook_browse_folders lists them, "
    + "and leaves the hidden ones out unless asked for them. If the intent is to remove the "
    + "mail, use `destination` with `deleteditems` instead. The user can undo that from Deleted "
    + "Items."
)

_SEARCH_FOLDER_DESTINATION = (
    "That handle addresses a search folder. A search folder is a saved query over other "
    + "folders, not a place to keep a message, so outlook_move_mail will not file mail into it. "
    + "Nothing was moved. Move the mail into the real folder it belongs in instead: "
    + "outlook_browse_folders reports the handle for it. The message then appears in any search "
    + "folder whose query matches it."
)


class MovedMessage(BaseModel):
    uri: str = Field(
        description=(
            "The handle the request gave for this message; once `moved` is true it addresses "
            "nothing, so never pass it to another tool."
        )
    )
    new_uri: str | None = Field(
        description=(
            "The message's handle in its new folder, read from Microsoft's response, or null "
            "if the move failed; once set, it is the only valid handle from now on, and every "
            "earlier handle for it, from a search, a listing, or a thread read, is now dead."
        )
    )
    moved: bool = Field(
        description=(
            "Whether Microsoft moved this one message; results are per message, not per call."
        )
    )
    error: str | None = Field(
        description="What Microsoft said when this message did not move; null if it moved."
    )


class MailMoved(BaseModel):
    destination: str = Field(description="The folder the messages moved into.")
    messages: list[MovedMessage] = Field(
        description="One row per handle in `message_refs`, in that order."
    )
    moved_count: int = Field(description="How many of `messages` moved.")
    failed_count: int = Field(
        description="How many messages did not move; see `messages` for which ones."
    )


@dataclass(frozen=True, slots=True)
class _Destination:
    folder_id: str
    name: str


@dataclass(frozen=True, slots=True)
class _Unusable:
    refusal: str


@dataclass(frozen=True, slots=True)
class _Attempt:
    result: MovedMessage
    failure: GraphFailure | None


async def move_mail(
    client: GraphServiceClient,
    *,
    message_refs: Sequence[str],
    destination: WellKnownFolder | None = None,
    folder_ref: str | None = None,
    mailbox: str | None = None,
) -> MailMoved:
    assert 1 <= len(message_refs) <= MAX_MESSAGES, (
        f"message_refs is bounded by the schema at 1..{MAX_MESSAGES}, got {len(message_refs)}"
    )
    handles = _message_handles(message_refs)
    wanted = _destination_asked_for(destination, folder_ref)
    reached = graph_mailbox(client, mailbox)

    with graph_errors(TOOL_NAME):
        target = await _destination(reached, wanted)
        attempts = (
            []
            if isinstance(target, _Unusable)
            else [await _move_one(reached, handle=handle, into=target) for handle in handles]
        )
        _raise_when_nothing_moved(attempts)

    if isinstance(target, _Unusable):
        raise ToolError(target.refusal)
    return _answer(target, attempts)


def _message_handles(message_refs: Sequence[str]) -> tuple[MailMessageHandle, ...]:
    handles: list[MailMessageHandle] = []
    for ref in message_refs:
        handle = mail_message_handle(ref)
        if handle is None:
            raise ToolError(_NOT_A_MESSAGE_HANDLE)
        handles.append(handle)
    return tuple(handles)


def _destination_asked_for(
    destination: WellKnownFolder | None, folder_ref: str | None
) -> WellKnownFolder | MailFolderHandle:
    if destination is not None and folder_ref is not None:
        raise ToolError(_BOTH_DESTINATIONS)
    if destination is not None:
        return destination
    if folder_ref is None:
        raise ToolError(_NO_DESTINATION)
    handle = mail_folder_handle(folder_ref)
    if handle is None:
        raise ToolError(_NOT_A_FOLDER_HANDLE)
    return handle


async def _destination(
    reached: UserItemRequestBuilder, wanted: WellKnownFolder | MailFolderHandle
) -> _Destination | _Unusable:
    if not isinstance(wanted, MailFolderHandle):
        return _Destination(folder_id=wanted, name=wanted)
    with graph_step(STEP_DESTINATION):
        folder = await reached.mail_folders.by_mail_folder_id(wanted.folder_id).get()
    assert folder is not None, "Graph answered a mail folder read with no folder"
    if _is_search_folder(folder):
        return _Unusable(_SEARCH_FOLDER_DESTINATION)
    if folder.is_hidden:
        return _Unusable(_HIDDEN_DESTINATION)
    return _Destination(folder_id=wanted.folder_id, name=folder.display_name or wanted.uri)


def _is_search_folder(folder: MailFolder) -> bool:
    if isinstance(folder, MailSearchFolder):
        return True
    return bool(_SEARCH_FOLDER_ONLY & frozenset(folder.additional_data or {}))


async def _move_one(
    reached: UserItemRequestBuilder, *, handle: MailMessageHandle, into: _Destination
) -> _Attempt:
    try:
        with graph_step(STEP_MOVE):
            moved = await reached.messages.by_message_id(handle.message_id).move.post(
                MovePostRequestBody(destination_id=into.folder_id),
                request_configuration=_move_request(),
            )
    except GraphFailure as failure:
        return _Attempt(
            result=MovedMessage(uri=handle.uri, new_uri=None, moved=False, error=str(failure)),
            failure=failure,
        )
    assert moved is not None and moved.id is not None, (
        "Graph answered a move with no message, so there is no new id to hand back"
    )
    return _Attempt(
        result=MovedMessage(
            uri=handle.uri, new_uri=MailMessageHandle(moved.id).uri, moved=True, error=None
        ),
        failure=None,
    )


def _move_request() -> RequestConfiguration[QueryParameters]:
    headers = HeadersCollection()
    headers.add(*_PREFER_IMMUTABLE_IDS)
    return RequestConfiguration[QueryParameters](headers=headers, options=no_retry())


def _raise_when_nothing_moved(attempts: Sequence[_Attempt]) -> None:
    if any(attempt.result.moved for attempt in attempts):
        return
    failed = next((attempt.failure for attempt in attempts if attempt.failure is not None), None)
    if failed is not None:
        raise failed


def _answer(target: _Destination, attempts: Sequence[_Attempt]) -> MailMoved:
    results = [attempt.result for attempt in attempts]
    return MailMoved(
        destination=target.name,
        messages=results,
        moved_count=sum(1 for result in results if result.moved),
        failed_count=sum(1 for result in results if not result.moved),
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Move Mail to a Folder",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE,
    )
    async def outlook_move_mail(
        message_refs: Annotated[
            list[str],
            Field(
                min_length=1,
                max_length=MAX_MESSAGES,
                description=(
                    f"The messages to move: up to {MAX_MESSAGES} `uri` values from a search, "
                    "list, or thread result."
                ),
            ),
        ],
        destination: Annotated[
            WellKnownFolder | None,
            Field(
                description=(
                    "Which well-known folder to move into (`inbox`, `sentitems`, `drafts`, "
                    "`archive`, `deleteditems`, `junkemail`, or `clutter`); alternative to "
                    "`folder_ref`."
                )
            ),
        ] = None,
        folder_ref: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The folder to move into, as the `uri` handle from an "
                    "outlook_browse_folders result; alternative to `destination`."
                ),
            ),
        ] = None,
        mailbox: Annotated[str | None, Field(min_length=1, description=MAILBOX_FIELD)] = None,
        client: GraphServiceClient = graph,
    ) -> MailMoved:
        return await move_mail(
            client,
            message_refs=message_refs,
            destination=destination,
            folder_ref=folder_ref,
            mailbox=mailbox,
        )
