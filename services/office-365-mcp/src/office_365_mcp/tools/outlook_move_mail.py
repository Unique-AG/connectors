"""`outlook_move_mail` — file messages into another folder, and the only removal this server has.

**There is no delete tool, and that is the design.** Moving a message to `deleteditems` is what
"delete this mail" means here: the user finds it in Deleted Items and can put it back. Microsoft
publishes a permanent delete and this connector exposes none, so no argument, no folder name and no
sequence of calls through this server destroys a message. The description says that in as many
words, because a model that cannot delete permanently and does not know it reports a message as
gone for good.

**A move changes the message's id, so every handle for it dies.** Microsoft describes the operation
as creating "a new copy of the message in the destination folder" and removing the original
(https://learn.microsoft.com/en-us/graph/api/message-move). So the answer carries a new `uri` for
every message that moved, read off Graph's own response rather than carried over from the request,
and says the old one is dead — and not only the one the caller passed: every hit a search, a
listing or a thread read reported for that message earlier in the conversation is stale too, and a
model holding one has no way to notice.

**One request per message, and each is reported on its own.** Graph publishes no batch form of this
route, so `message_refs` is a loop rather than one call, and a partial failure is the ordinary shape
of a bad batch rather than an edge case. Every row carries the handle that went in, the handle that
came out and whether it moved. A failure is raised only when nothing moved at all: once the mailbox
has changed, an exception would throw away the only record of which handles are now dead.

**`no_retry()` on every move, because a move is not idempotent.** The first attempt removes the
original, so a retry after a lost response addresses an id that no longer exists. The SDK's retry
handler retries `POST` on 429, 503 and 504 exactly as readily as `GET`, three times by default, and
Graph publishes no idempotency key for this operation.

**The destination vocabulary is closed.** `WellKnownFolder` in `shared/mail.py` leaves out the purge
bin, the folder parents, the Outbox and the sync diagnostics, and no free-form folder name is
accepted at all: matching a user's own folder by string is how mail is filed into the wrong place.
Any other folder is reached by the handle `outlook_browse_folders` reported for it.

**A destination handle is read in this same call.** A folder that is hidden, or that is a search
folder, is refused: mail filed into either vanishes from the user's view without having been
deleted. It is read now rather than trusted from an earlier answer, because a flag in an earlier
answer is a snapshot the model is holding and not a fact about the mailbox. `mailSearchFolder` is a
distinct `@odata.type` rather than a flag, so the check is on the type Graph's own discriminator
produced.
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
from msgraph.generated.models.mail_search_folder import MailSearchFolder
from msgraph.generated.users.item.mail_folders.item.mail_folder_item_request_builder import (
    MailFolderItemRequestBuilder,
)
from msgraph.generated.users.item.messages.item.move.move_post_request_body import (
    MovePostRequestBody,
)
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
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE, graph_client_for_caller

TOOL_NAME = "outlook_move_mail"

STEP_DESTINATION = "destination_folder"
STEP_MOVE = "move_message"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Mail.ReadWrite",)

# A well-known destination, so the first Graph call this makes is the move itself: a call that
# reached the folder read first would be refused there and never exercise the move at all.
GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "message_refs": ["outlook:///messages/AAMkAGI2SYNTHETIC-immutable-0001%3D"],
    "destination": "archive",
}

# The default 404 advice, to check the id was copied from a tool response verbatim, is wrong here
# because it was: both arguments that can 404 carry handles this connector minted.
GRAPH_NOT_FOUND = (
    "Microsoft 365 would not return something this move addressed, and nothing was moved. If "
    + "`folder_ref` was used, the destination is the likelier of the two: the handle is well "
    + "formed, so the folder was most likely deleted, or moved or copied and given a new id — "
    + "call outlook_browse_folders again and take the `uri` it reports now. Otherwise a message "
    + "handle is stale, which is exactly what a handle for a message that has already been moved "
    + "looks like: find the message again with outlook_search_mail and move the `uri` that search "
    + "returns. Retrying with these arguments will fail identically."
)

MAX_MESSAGES = 20

# The two ways to name a destination, spelled once: the schema constraint and the refusals below
# must name the same pair, and a rename that reached only one of them would leave a client refused
# by a rule the schema does not publish.
DESTINATION_ARGUMENTS: tuple[str, str] = ("destination", "folder_ref")

# Everything the destination check reads. `@odata.type` is deliberately absent and cannot be asked
# for: it is the annotation Graph puts on an instance of a derived type, and it is what the SDK's
# discriminator reads to hand back a `MailSearchFolder` instead of a `MailFolder`.
_DESTINATION_FIELDS: tuple[str, ...] = ("displayName", "isHidden")

_PREFER_IMMUTABLE_IDS = ("Prefer", 'IdType="ImmutableId"')

_FolderQuery = MailFolderItemRequestBuilder.MailFolderItemRequestBuilderGetQueryParameters

_DESCRIPTION = f"""\
Move messages in the signed-in user's mailbox into another folder, up to {MAX_MESSAGES} at a time. \
THIS IS ALSO HOW THIS CONNECTOR DELETES: there is no delete tool, and moving a message to \
`deleteditems` is what "delete this mail" means here. That form is reversible — the message is in \
Deleted Items and the user can put it back — and this server has no way to delete a message \
permanently, by design, so never report a message as gone for good. Name the destination with \
`destination` for a well-known folder (`inbox`, `sentitems`, `drafts`, `archive`, `deleteditems`, \
`junkemail`, `clutter`) or with `folder_ref`, the `uri` of an outlook_browse_folders result, for \
any other folder including every folder the user made; pass exactly one of the two. A folder's own \
name is not accepted — browse for its handle. EVERY HANDLE FOR A MOVED MESSAGE DIES WITH THE MOVE: \
Microsoft performs a move as a new copy in the destination plus the removal of the original, so \
each result carries that message's new `uri`, and the handle passed in — along with any other \
handle for that message reported earlier in this conversation — must never be used again. Each \
message is moved by its own request and reported on its own, so a batch where some moved and some \
did not says exactly which.\
"""

_BOTH_DESTINATIONS = (
    "outlook_move_mail moves mail into one folder, so `destination` and `folder_ref` are "
    + "alternatives and not a pair: `destination` names a well-known folder such as "
    + "`deleteditems`, `folder_ref` addresses any folder by the handle outlook_browse_folders "
    + "reported for it. Pass whichever one names the folder the mail belongs in and omit the "
    + "other entirely. Nothing was moved."
)

_NO_DESTINATION = (
    "outlook_move_mail was given no destination, so there was nowhere to move the mail to and "
    + "nothing was moved. Pass `destination` for a well-known folder — `inbox`, `sentitems`, "
    + "`drafts`, `archive`, `deleteditems`, `junkemail` or `clutter`, and `deleteditems` is how a "
    + "message is removed here — or `folder_ref` for any other folder, which is the `uri` of an "
    + "outlook_browse_folders result. Exactly one of the two, never neither."
)

_NOT_A_FOLDER_HANDLE = (
    "outlook_move_mail takes a folder handle in `folder_ref`, outlook:///folders/{id}, exactly as "
    + "outlook_browse_folders reported it in `uri`. A folder's name is not one, nor is a message "
    + "handle. For Deleted Items and the other well-known folders use `destination` instead, "
    + "which takes names such as `deleteditems` and `archive`. Nothing was moved."
)

_NOT_A_MESSAGE_HANDLE = (
    "outlook_move_mail takes message handles in `message_refs`, outlook:///messages/{id}, exactly "
    + "as outlook_search_mail, outlook_list_mail or outlook_read_thread reported them in `uri`, "
    + "and one of these is not one. A subject line, an email address, an Outlook web link and a "
    + "bare message id are none of them handles, and neither is a folder, draft or rule handle "
    + "under the same scheme. Every handle is checked before any message moves, so nothing was "
    + "moved: fix the value and call again with the whole batch."
)

_HIDDEN_DESTINATION = (
    "That folder is hidden from the user in Outlook, so mail moved into it would disappear from "
    + "their view without having been deleted, and outlook_move_mail will not file mail there. "
    + "Nothing was moved. Pick a folder the user can see — outlook_browse_folders lists them, and "
    + "leaves the hidden ones out unless asked for them — or use `destination` with `deleteditems` "
    + "if the intent was to remove the mail, which the user can undo from Deleted Items."
)

_SEARCH_FOLDER_DESTINATION = (
    "That handle addresses a search folder, which is a saved query over other folders rather than "
    + "a place a message can be kept, so outlook_move_mail will not file mail into it. Nothing was "
    + "moved. Move the mail into the real folder it belongs in — outlook_browse_folders reports "
    + "the handle for it — and it will appear in any search folder whose query it matches."
)


class MovedMessage(BaseModel):
    """One message's move: the handle that went in, the handle that came out, and whether it did."""

    uri: str = Field(
        description=(
            "The handle this call was given for the message. Once `moved` is true it addresses "
            + "nothing — keep it only to say which message this row is about, and never pass it "
            + "to another tool."
        )
    )
    new_uri: str | None = Field(
        description=(
            "The message's handle in its new folder, read off Microsoft's own answer to the move "
            + "rather than carried over from the request. This is the ONLY handle for this "
            + "message from now on. The one in `uri` is dead, and so is every handle for this "
            + "message that a search, a listing or a thread read reported earlier in this "
            + "conversation: Microsoft performs a move as a new copy in the destination plus the "
            + "removal of the original. Null when the move failed, in which case the message did "
            + "not move and `uri` still addresses it."
        )
    )
    moved: bool = Field(
        description=(
            "Whether Microsoft moved this one message. Each message is moved by its own request, "
            + "so this is per message and not per call: false here beside true on another row "
            + "means part of the batch moved and the rest did not."
        )
    )
    error: str | None = Field(
        description=(
            "What Microsoft said about this message when it did not move, and null when it did. A "
            + "not-found here is most often a handle that was already stale — a message this "
            + "conversation moved earlier, or one Outlook filed itself through a rule or "
            + "retention. Finding the message again and moving the handle that search returns is "
            + "the recovery; retrying this handle is not."
        )
    )


class MailMoved(BaseModel):
    """What became of one batch: where it was going, and every message's own outcome."""

    destination: str = Field(
        description=(
            "The folder the messages were moved into: the well-known name that was asked for, or "
            + "the folder's name as Outlook shows it when `folder_ref` was used."
        )
    )
    messages: list[MovedMessage] = Field(
        description=(
            "One row per handle in `message_refs`, in the order they were given. Each says "
            + "whether that message moved and, when it did, the new handle that replaces every "
            + "older one for it."
        )
    )
    moved_count: int = Field(
        description=(
            "How many of `messages` moved. The messages counted here have moved and nothing is "
            + "rolled back if a later one fails, so this is what actually happened to the mailbox."
        )
    )
    failed_count: int = Field(
        description=(
            "How many did not move. Above zero beside a `moved_count` above zero is a partial "
            + "move: part of the batch is in the destination and the rest is where it was. Read "
            + "the rows for which is which rather than repeating the whole batch."
        )
    )


@dataclass(frozen=True, slots=True)
class _Destination:
    """A folder mail may be moved into: what Graph is told, and what a person would call it."""

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
) -> MailMoved:
    """Move each of `message_refs` into one folder, reporting every message's own outcome."""
    assert 1 <= len(message_refs) <= MAX_MESSAGES, (
        f"message_refs is bounded by the schema at 1..{MAX_MESSAGES}, got {len(message_refs)}"
    )
    handles = _message_handles(message_refs)
    wanted = _destination_asked_for(destination, folder_ref)

    with graph_errors(TOOL_NAME):
        target = await _destination(client, wanted)
        attempts = (
            []
            if isinstance(target, _Unusable)
            else [await _move_one(client, handle=handle, into=target) for handle in handles]
        )
        _raise_when_nothing_moved(attempts)

    # Decided inside the block above and raised outside it: `graph_errors` counts a `ToolError`
    # escaping it as a Graph operation that failed for a reason the seam cannot describe, and a
    # destination this tool refuses is not a Graph failure at all.
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
    """Which folder was named, refusing both and neither. `destination` carries no default, so an
    argument that is present here is one a caller spelled out and the pair is unambiguous."""
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
    client: GraphServiceClient, wanted: WellKnownFolder | MailFolderHandle
) -> _Destination | _Unusable:
    """The folder to move into, read from Graph when a handle named it.

    A well-known name is not read back: Microsoft accepts one as `destinationId` directly, the
    vocabulary is closed, and none of the seven names in it is hidden or a search folder.
    """
    if not isinstance(wanted, MailFolderHandle):
        return _Destination(folder_id=wanted, name=wanted)
    with graph_step(STEP_DESTINATION):
        folder = await client.me.mail_folders.by_mail_folder_id(wanted.folder_id).get(
            request_configuration=RequestConfiguration[_FolderQuery](
                query_parameters=_FolderQuery(select=list(_DESTINATION_FIELDS))
            )
        )
    assert folder is not None, "Graph answered a mail folder read with no folder"
    if isinstance(folder, MailSearchFolder):
        return _Unusable(_SEARCH_FOLDER_DESTINATION)
    if folder.is_hidden:
        return _Unusable(_HIDDEN_DESTINATION)
    return _Destination(folder_id=wanted.folder_id, name=folder.display_name or wanted.uri)


async def _move_one(
    client: GraphServiceClient, *, handle: MailMessageHandle, into: _Destination
) -> _Attempt:
    """One message, one request. A refusal is caught rather than raised here so the messages moved
    before it survive into the answer; `_raise_when_nothing_moved` decides whether it stays caught.
    """
    try:
        with graph_step(STEP_MOVE):
            moved = await client.me.messages.by_message_id(handle.message_id).move.post(
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
    """`no_retry()` because the first attempt removes the original, so a retry after a lost response
    addresses an id that no longer exists — and the SDK retries `POST` by default.

    The header is built per call: kiota's `RequestConfiguration.headers` defaults to one collection
    shared by every configuration in the process, so a preference added to it leaks onto every
    Graph call. It is what makes the id in the response an immutable one, and therefore a handle in
    the same id space as every other handle this connector mints.
    """
    headers = HeadersCollection()
    headers.add(*_PREFER_IMMUTABLE_IDS)
    return RequestConfiguration[QueryParameters](headers=headers, options=no_retry())


def _raise_when_nothing_moved(attempts: Sequence[_Attempt]) -> None:
    """A batch in which nothing moved is the call's own failure, so the first refusal is raised and
    the advice middleware gets to word it. Once one message has moved, no failure may be raised:
    an exception would discard the only record of which handles are now dead."""
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
                    "The messages to move, as the `uri` of an outlook_search_mail, "
                    + "outlook_list_mail or outlook_read_thread result, verbatim: "
                    + f"outlook:///messages/{{id}}. One to {MAX_MESSAGES} per call. Every handle "
                    + "is checked before any message moves, so a batch with a bad value in it "
                    + "moves nothing. Each one is dead once its message has moved — take the "
                    + "replacement out of that row's `new_uri`."
                ),
            ),
        ],
        destination: Annotated[
            WellKnownFolder | None,
            Field(
                description=(
                    "Which well-known folder to move into, by Microsoft's own "
                    + "locale-independent name, so `deleteditems` reaches Deleted Items in a "
                    + "mailbox of any language. `deleteditems` is how a message is removed here, "
                    + "and the user can restore it from there. Every other folder, including "
                    + "every folder the user made, is reached with `folder_ref` instead — a "
                    + "folder's own name is not accepted here. Pass this or `folder_ref`, never "
                    + "both and never neither."
                )
            ),
        ] = None,
        folder_ref: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The folder to move into, as the `uri` of an outlook_browse_folders result: "
                    + "outlook:///folders/{id}. Use it for anything the well-known names do not "
                    + "cover. The folder is read before anything moves, and a hidden folder or a "
                    + "search folder is refused: mail filed into either disappears from the "
                    + "user's view without having been deleted. Alternative to `destination`, "
                    + "never a companion to it."
                ),
            ),
        ] = None,
        client: GraphServiceClient = graph,
    ) -> MailMoved:
        return await move_mail(
            client,
            message_refs=message_refs,
            destination=destination,
            folder_ref=folder_ref,
        )

    _exactly_one_destination(mcp.add_tool(outlook_move_mail))


def _exactly_one_destination(tool: Tool) -> None:
    """Say "one of these two, and not neither" in the schema, which a Python signature cannot.

    The runtime refusals stay: FastMCP validates arguments against the signature rather than
    against this schema, so a client that ignores the constraint still has to be told — and told
    which of the two mistakes it made, which the schema alone cannot say.
    """
    first, second = DESTINATION_ARGUMENTS
    tool.parameters["oneOf"] = [
        {"required": [first], "not": {"required": [second]}},
        {"required": [second], "not": {"required": [first]}},
    ]
