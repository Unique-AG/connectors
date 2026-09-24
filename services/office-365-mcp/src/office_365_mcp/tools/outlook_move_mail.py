"""`outlook_move_mail` — file messages into another folder, and the only removal this server has.

**There is no delete tool. That is by design.** Moving a message to `deleteditems` is what
"delete this mail" means here. The user finds the message in Deleted Items, and can restore it.
Microsoft Graph publishes a permanent delete operation, and this connector exposes none of it. No
argument, no folder name and no sequence of calls through this server destroys a message. The
description states this directly, because a model that does not know this limit can wrongly
report a message as gone for good.

**A move changes the message's id, so every old handle for it dies.** Microsoft describes this
operation as creating "a new copy of the message in the destination folder" and removing the
original (https://learn.microsoft.com/en-us/graph/api/message-move). So the answer carries a new
`uri` for every message that moved. This tool reads that new `uri` from Graph's own response, not
from the request. The old handle is dead, and not only the one the caller passed in. This
staleness reaches every earlier hit for that message, from a search, a listing, or a thread read.
A model that holds one has no way to notice.

**One request per message. Each is reported on its own.** Graph publishes no batch form of this
route, so `message_refs` drives a loop, not one call. A partial failure is the ordinary shape of
a bad batch here, not an edge case. Every row carries the handle that went in, the handle that
came out, and whether it moved. This function raises a failure only when nothing moved at all.
Once the mailbox changes, an exception here throws away the only record of which handles are
now dead.

**Every move uses `no_retry()`, because a move is not idempotent.** The first attempt removes the
original message, so a retry after a lost response addresses an id that no longer exists. The
SDK's retry handler retries `POST` on 429, 503 and 504 just as readily as `GET`, three times by
default. Graph publishes no idempotency key for this operation.

**The destination vocabulary is closed.** `WellKnownFolder` in `shared/mail.py` leaves out the
purge bin, the folder parents, the Outbox and the sync diagnostics folders. No free-form folder
name is accepted at all: matching a user's own folder by name is how mail gets filed into the
wrong place. A caller reaches any other folder with the handle that `outlook_browse_folders`
reported for it.

**This call reads the destination handle itself.** It refuses a folder that is hidden, or that is
a search folder. Mail filed into either one disappears from the user's view, even though it was
not deleted. This call reads the folder now, instead of trusting an earlier answer. A flag in an
earlier answer is only a snapshot that the model holds, not a fact about the current mailbox.
`mailSearchFolder` is a distinct `@odata.type`, not a flag. This read narrows nothing, because
Graph can leave that annotation out of a narrowed answer. The SDK then has no discriminator. It
builds a plain `MailFolder`, and a type check alone lets the folder through. The check also falls
back to the properties only a search folder declares, which the SDK keeps in `additional_data`
when it did not recognize them.

**`mailbox` re-points every request — the destination read included — from `/me` to
`/users/{id}`.** One `mailbox` covers the whole call, never split across two.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from fastmcp.tools import tool as tool_metadata
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

# A well-known destination, so the first Graph call this makes is the move itself. If the
# example named a folder handle instead, the call fails at the folder read, before it reaches
# the move.
GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "message_refs": ["outlook:///messages/AAMkAGI2SYNTHETIC-immutable-0001%3D"],
    "destination": "archive",
}

# The default 404 advice tells the caller to make sure that the id came from a tool response
# verbatim. That advice is wrong here, because it already did: both arguments that can 404
# carry handles this connector minted itself.
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

# The two ways to name a destination, spelled once here. The schema constraint and the refusals
# below must name the same pair. If a rename reaches only one of them, a client is refused by a
# rule the schema does not publish.
DESTINATION_ARGUMENTS: tuple[str, str] = ("destination", "folder_ref")

# The properties only a search folder declares, taken from the SDK rather than written out, so a
# property Microsoft adds later is covered without an edit here.
_SEARCH_FOLDER_ONLY: frozenset[str] = frozenset(
    MailSearchFolder().get_field_deserializers()
) - frozenset(MailFolder().get_field_deserializers())

assert _SEARCH_FOLDER_ONLY, (
    "MailSearchFolder declares no property of its own, so the destination check below accepts "
    "every search folder silently"
)

_PREFER_IMMUTABLE_IDS = ("Prefer", 'IdType="ImmutableId"')


_DESCRIPTION = f"""\
This tool moves up to {MAX_MESSAGES} messages into another folder, in the mailbox of the \
signed-in user or, with `mailbox`, a shared or delegated one. This is the only way this \
connector erases mail.

Notes:
- Pass exactly one of `destination` or `folder_ref`, never both.
- A move to `deleteditems` is what "delete this mail" means here. The message stays \
recoverable in Deleted Items, because this server has no permanent-erase operation.
- `message_refs` takes the `uri` of an outlook_search_mail, outlook_list_mail, or \
outlook_read_thread result. A subject line, an email address, an Outlook web link, and a bare \
message id are not handles.
- `mailbox`, when given, applies to the destination and to every message in `message_refs`. \
All of them must be in that one mailbox.
"""

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
    """One message's move: the handle that went in, the handle that came out, and whether it did."""

    uri: str = Field(
        description=(
            "The handle that the request gave for this message. Once `moved` is true, it "
            + "addresses nothing. Keep it only to identify which message this row is about. "
            + "Never pass it to another tool."
        )
    )
    new_uri: str | None = Field(
        description=(
            "The message's handle in its new folder, read from Microsoft's response rather "
            + "than carried over from the request. Null when the move failed, in which case "
            + "`uri` still addresses the message. Once set, this handle is the only one for "
            + "the message from now on. `uri` and every earlier handle for it, from a search, "
            + "a listing, or a thread read, are now dead."
        )
    )
    moved: bool = Field(
        description=(
            "Whether Microsoft moved this one message. Microsoft moves each message by its "
            + "own request, so this result is per message, not per call. False here beside "
            + "true on another row means that part of the batch moved and the rest did not."
        )
    )
    error: str | None = Field(
        description=(
            "What Microsoft said about this message when it did not move. Null when the "
            + "message moved. A not-found error here is most often a handle that was already "
            + "stale. Find the message again. Then move the handle that the search returns, "
            + "rather than retrying this one."
        )
    )


class MailMoved(BaseModel):
    """What became of one batch: where it went, and every message's own outcome."""

    destination: str = Field(
        description=(
            "The folder that the messages moved into. This is the well-known name that the "
            + "call asked for, or the folder's name as Outlook shows it when the call used "
            + "`folder_ref`."
        )
    )
    messages: list[MovedMessage] = Field(
        description=(
            "One row exists per handle in `message_refs`, in that order. Each says whether "
            + "that message moved and, when it did, the new handle that replaces every older "
            + "one for it."
        )
    )
    moved_count: int = Field(
        description=(
            "How many of `messages` moved. If a later message fails, nothing rolls back, so "
            + "this count is what happened to the mailbox, not an all-or-nothing outcome."
        )
    )
    failed_count: int = Field(
        description=(
            "How many messages did not move. Read `messages` for which ones. These counts "
            + "alone do not say."
        )
    )


@dataclass(frozen=True, slots=True)
class _Destination:
    """A folder mail can be moved into: what Graph is told, and what a person calls it."""

    folder_id: str
    name: str


@dataclass(frozen=True, slots=True)
class _Unusable:
    """A destination read back from Graph that mail must not be filed into, and why not."""

    refusal: str


@dataclass(frozen=True, slots=True)
class _Attempt:
    """One message's outcome, and the failure behind it while it is still raisable."""

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
    """Move each of `message_refs` into one folder, and report every message's own outcome."""
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

    # This function decides inside the block above, and raises outside it. `graph_errors` treats
    # a `ToolError` that escapes it as a Graph operation that failed for a reason the seam cannot
    # describe. A destination this tool refuses is not a Graph failure at all.
    if isinstance(target, _Unusable):
        raise ToolError(target.refusal)
    return _answer(target, attempts)


def _message_handles(message_refs: Sequence[str]) -> tuple[MailMessageHandle, ...]:
    """Every handle parsed before any message moves, so a batch with a bad value in it moves
    nothing rather than leaving the mailbox half filed."""
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
    """Which folder was named. This function refuses a call that names both, or names neither.
    `destination` carries no default, so an argument that is present here is one a caller
    spelled out, and the pair is unambiguous."""
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
    """The folder to move into, read from Graph when a handle named it.

    A well-known name is not read back. Microsoft accepts one as `destinationId` directly, the
    vocabulary is closed, and none of the seven names in it is hidden or a search folder.
    """
    if not isinstance(wanted, MailFolderHandle):
        return _Destination(folder_id=wanted, name=wanted)
    # No `$select` here. Narrowing this read is what hides a search folder. Graph can leave the
    # `@odata.type` annotation out of a narrowed answer. Then the SDK has no discriminator to
    # read, so it hands back a plain `MailFolder`, and the check below never fires. A whole
    # folder is a small answer, and this is one folder once per call.
    with graph_step(STEP_DESTINATION):
        folder = await reached.mail_folders.by_mail_folder_id(wanted.folder_id).get()
    assert folder is not None, "Graph answered a mail folder read with no folder"
    if _is_search_folder(folder):
        return _Unusable(_SEARCH_FOLDER_DESTINATION)
    if folder.is_hidden:
        return _Unusable(_HIDDEN_DESTINATION)
    return _Destination(folder_id=wanted.folder_id, name=folder.display_name or wanted.uri)


def _is_search_folder(folder: MailFolder) -> bool:
    """Whether Graph answered with a search folder, by either of the two signals it can carry.

    The typed answer is the clean one: `@odata.type` names the derived type and the SDK's
    discriminator hands back a `MailSearchFolder`. Without that annotation, the SDK builds a
    plain `MailFolder`. It puts the properties that it did not recognize in `additional_data`,
    so a search folder still names itself there.
    """
    if isinstance(folder, MailSearchFolder):
        return True
    return bool(_SEARCH_FOLDER_ONLY & frozenset(folder.additional_data or {}))


async def _move_one(
    reached: UserItemRequestBuilder, *, handle: MailMessageHandle, into: _Destination
) -> _Attempt:
    """One message, one request. A refusal is caught rather than raised here, so the messages
    moved before it survive into the answer. `_raise_when_nothing_moved` decides whether it
    stays caught.
    """
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
    """`no_retry()`, because the first attempt removes the original, so a retry after a lost
    response addresses an id that no longer exists. The SDK retries `POST` by default.

    The header is built per call: kiota's `RequestConfiguration.headers` defaults to one collection
    shared by every configuration in the process. A preference added to it leaks onto every Graph
    call. It is what makes the id in the response an immutable one. That makes it a handle in the
    same id space as every other handle this connector mints.
    """
    headers = HeadersCollection()
    headers.add(*_PREFER_IMMUTABLE_IDS)
    return RequestConfiguration[QueryParameters](headers=headers, options=no_retry())


def _raise_when_nothing_moved(attempts: Sequence[_Attempt]) -> None:
    """A batch in which nothing moved is the call's own failure. So this function raises the
    first refusal, and the advice middleware gets to word it. Once one message moved, this
    function raises nothing more, because an exception here discards the only record of which
    handles are now dead."""
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

    @tool_metadata(
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
                    "The messages to move: `uri` values from an outlook_search_mail, "
                    + "outlook_list_mail, or outlook_read_thread result. This tool accepts one "
                    + f"to {MAX_MESSAGES} per call. This tool makes sure that every handle is "
                    + "valid before it moves any message, so a batch with a bad value moves "
                    + "nothing."
                ),
            ),
        ],
        destination: Annotated[
            WellKnownFolder | None,
            Field(
                description=(
                    "Which well-known folder to move into, by Microsoft's own "
                    + "locale-independent name: `inbox`, `sentitems`, `drafts`, `archive`, "
                    + "`deleteditems`, `junkemail`, or `clutter`. Every other folder needs "
                    + "`folder_ref` instead, even a folder that the user made. A folder's own "
                    + "name is not accepted here. Alternative to `folder_ref`."
                )
            ),
        ] = None,
        folder_ref: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The folder to move into, as the opaque handle that an "
                    + "outlook_browse_folders result reported for it in `uri`: "
                    + "`outlook:///folders/{id}`. A folder's display name is not valid here. "
                    + "This tool reads the folder before anything moves. It refuses a hidden "
                    + "folder or a search folder. Mail filed into either disappears from the "
                    + "user's view, though it is not erased. Alternative to `destination`."
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

    _exactly_one_destination(mcp.add_tool(outlook_move_mail))


def _exactly_one_destination(tool: Tool) -> None:
    """Say "one of these two, and not neither" in the schema. A Python signature cannot say that.

    The runtime refusals stay. FastMCP validates arguments against the signature, not against
    this schema, so a client that ignores the constraint still needs to be told. It also needs
    to be told which of the two mistakes it made, which the schema alone cannot say.
    """
    first, second = DESTINATION_ARGUMENTS
    tool.parameters["oneOf"] = [
        {"required": [first], "not": {"required": [second]}},
        {"required": [second], "not": {"required": [first]}},
    ]
