from collections.abc import Mapping, Sequence
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.users.item.messages.item.move.move_post_request_body import (
    MovePostRequestBody,
)
from msgraph.generated.users.item.user_item_request_builder import UserItemRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import GraphFailure, graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.handles import MailMessageHandle
from office_365_mcp.shared.immutable_ids import immutable_id_headers
from office_365_mcp.shared.mail import (
    MailDestination,
    MailFault,
    MessageAttempt,
    WellKnownFolder,
    destination_asked_for,
    mail_batch_confirmation_id,
    message_handles,
    raise_when_no_message_succeeded,
    resolve_destination,
)
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    MAILBOX_FIELD,
    WRITE_DESTRUCTIVE,
    Confirm,
    Confirmed,
    graph_client_for_caller,
    graph_mailbox,
    person_confirms,
)

TOOL_NAME = "outlook_move_mail"

STEP_MOVE = "move_message"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Mail.ReadWrite", "Mail.ReadWrite.Shared")

CHANGE_SHOWN_BY: tuple[str, ...] = ("outlook_read_mail", "outlook_list_mail")

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "message_refs": ["outlook:///messages/AAMkAGI2SYNTHETIC-immutable-0001%3D"],
    "destination": "archive",
}

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return an item that this call needed, and nothing moved. If you "
    + "passed `folder_ref`, the destination is the more probable cause, because the handle is "
    + "well formed. The probable cause is that somebody deleted, moved, or copied the folder. "
    + "Microsoft 365 can give a moved or copied folder a new id. Call outlook_browse_folders "
    + "again. Then use the `uri` that it reports now.\n\n"
    + "If you did not pass `folder_ref`, a message handle is stale. If a message moves to "
    + "another folder of this mailbox, its handle does not change. If somebody deletes the "
    + "message permanently, or moves it to an archive mailbox, Microsoft 365 gives this answer. "
    + "Find the message again with outlook_search_mail. Then move the `uri` that the search "
    + "returns. If the search does not find the message, tell the user that the message is not "
    + "in this mailbox now.\n\n"
    + "If you call this tool again with the same arguments, the call will fail the same way."
)


_DESCRIPTION = (
    "Moves messages into another folder, in the signed-in user's own mailbox or, with "
    "`mailbox`, a shared or delegated one — moving to `deleteditems` is the only way this "
    "connector erases mail, and the message stays recoverable in Deleted Items because there is "
    "no permanent-erase operation. "
    "This tool asks the user to agree before it changes a shared or delegated mailbox. "
    "It changes the user's own mailbox without a question."
)

_AGREE = "move"
_DECLINE = "do not move"
_NOTHING_MOVED = "No message was moved."

_DELETED_ITEMS = "deleteditems"

_SOMEONE_ELSES = "That mailbox belongs to someone else, not to the signed-in user."

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

_REFUSALS: Mapping[MailFault, str] = {
    MailFault.BOTH_DESTINATIONS: _BOTH_DESTINATIONS,
    MailFault.NO_DESTINATION: _NO_DESTINATION,
    MailFault.NOT_A_FOLDER_HANDLE: _NOT_A_FOLDER_HANDLE,
    MailFault.NOT_A_MESSAGE_HANDLE: _NOT_A_MESSAGE_HANDLE,
    MailFault.SEARCH_FOLDER: _SEARCH_FOLDER_DESTINATION,
    MailFault.HIDDEN_FOLDER: _HIDDEN_DESTINATION,
}


class MovedMessage(BaseModel):
    uri: str = Field(
        description=(
            "This is the handle that the request gave for this message. This connector asks "
            "Microsoft 365 for immutable ids. An immutable id does not change when the message "
            "moves to another folder of the same mailbox. So this handle still addresses the "
            "message."
        )
    )
    new_uri: str | None = Field(
        description=(
            "This is the handle of this message, as Microsoft 365 gave it after it moved the "
            "message. This field is null when Microsoft 365 did not move the message."
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


async def move_mail(
    client: GraphServiceClient,
    *,
    message_refs: Sequence[str],
    confirm: Confirm,
    destination: WellKnownFolder | None = None,
    folder_ref: str | None = None,
    mailbox: str | None = None,
) -> MailMoved | InputRequiredResult:
    assert len(message_refs) >= 1, "the schema admits no empty batch"
    handles = message_handles(message_refs)
    if isinstance(handles, MailFault):
        raise ToolError(_REFUSALS[handles])
    wanted = destination_asked_for(destination, folder_ref)
    if isinstance(wanted, MailFault):
        raise ToolError(_REFUSALS[wanted])
    reached = graph_mailbox(client, mailbox)

    answer: Confirmed = None
    attempts: list[MessageAttempt[MovedMessage]] = []
    with graph_errors(TOOL_NAME):
        target = await resolve_destination(reached, wanted)
        if not isinstance(target, MailFault):
            if mailbox is not None:
                with not_graph():
                    answer = await confirm(
                        _question(mailbox, len(handles), target),
                        mail_batch_confirmation_id(
                            TOOL_NAME, mailbox=mailbox, handles=handles, target=target
                        ),
                    )
            if answer is None:
                attempts = [
                    await _move_one(reached, handle=handle, into=target) for handle in handles
                ]
                raise_when_no_message_succeeded(attempts)

    if isinstance(target, MailFault):
        raise ToolError(_REFUSALS[target])
    if isinstance(answer, InputRequiredResult):
        return answer
    if answer is not None:
        raise ToolError(answer)
    return _answer(target, attempts)


def _question(mailbox: str, count: int, target: MailDestination) -> str:
    messages = f"{count} {'message' if count == 1 else 'messages'}"
    if target.folder_id == _DELETED_ITEMS:
        return (
            f"Delete {messages} in the mailbox {cut_for_a_question(mailbox)!r}? "
            + "This tool moves them to Deleted Items. They stay recoverable in Deleted Items. "
            + _SOMEONE_ELSES
        )
    return (
        f"Move {messages} in the mailbox {cut_for_a_question(mailbox)!r} to the folder "
        + f"{cut_for_a_question(target.name)!r}? "
        + _SOMEONE_ELSES
    )


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_AGREE, decline=_DECLINE, nothing_happened=_NOTHING_MOVED)


async def _move_one(
    reached: UserItemRequestBuilder, *, handle: MailMessageHandle, into: MailDestination
) -> MessageAttempt[MovedMessage]:
    try:
        with graph_step(STEP_MOVE):
            moved = await reached.messages.by_message_id(handle.message_id).move.post(
                MovePostRequestBody(destination_id=into.folder_id),
                request_configuration=_move_request(),
            )
    except GraphFailure as failure:
        return MessageAttempt(
            result=MovedMessage(uri=handle.uri, new_uri=None, moved=False, error=str(failure)),
            failure=failure,
        )
    assert moved is not None and moved.id is not None, (
        "Graph answered a move with no message, so there is no new id to hand back"
    )
    return MessageAttempt(
        result=MovedMessage(
            uri=handle.uri, new_uri=MailMessageHandle(moved.id).uri, moved=True, error=None
        ),
        failure=None,
    )


def _move_request() -> RequestConfiguration[QueryParameters]:
    return RequestConfiguration[QueryParameters](headers=immutable_id_headers(), options=no_retry())


def _answer(target: MailDestination, attempts: Sequence[MessageAttempt[MovedMessage]]) -> MailMoved:
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
                description=(
                    "The messages to move: `uri` values from a search, list, or thread result."
                ),
            ),
        ],
        ctx: Context,
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
    ) -> MailMoved | InputRequiredResult:
        return await move_mail(
            client,
            message_refs=message_refs,
            confirm=a_person_agrees(ctx),
            destination=destination,
            folder_ref=folder_ref,
            mailbox=mailbox,
        )
