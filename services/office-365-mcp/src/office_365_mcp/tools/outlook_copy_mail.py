import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.mail_folder import MailFolder
from msgraph.generated.models.mail_search_folder import MailSearchFolder
from msgraph.generated.users.item.messages.item.copy.copy_post_request_body import (
    CopyPostRequestBody,
)
from msgraph.generated.users.item.user_item_request_builder import UserItemRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import GraphFailure, graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.handles import (
    MailFolderHandle,
    MailMessageHandle,
    mail_folder_handle,
    mail_message_handle,
)
from office_365_mcp.shared.immutable_ids import immutable_id_headers
from office_365_mcp.shared.mail import WellKnownFolder
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    MAILBOX_FIELD,
    WRITE_ADDITIVE,
    Confirm,
    Confirmed,
    graph_client_for_caller,
    graph_mailbox,
    person_confirms,
)

TOOL_NAME = "outlook_copy_mail"

STEP_DESTINATION = "destination_folder"
STEP_COPY = "copy_message"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Mail.ReadWrite", "Mail.ReadWrite.Shared")

CHANGE_SHOWN_BY: tuple[str, ...] = ("outlook_read_mail", "outlook_list_mail")

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "message_refs": ["outlook:///messages/AAMkAGI2SYNTHETIC-immutable-0001%3D"],
    "destination": "archive",
}

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return an item that this call needed. No message was copied.\n\n"
    + "If you passed `folder_ref`, the destination folder is the likely cause. The handle is "
    + "well formed. Somebody can delete, move, or copy a folder, and then Microsoft 365 can give "
    + "it a new id. Call outlook_browse_folders again. Then use the `uri` that it reports now.\n\n"
    + "If you did not pass `folder_ref`, a message handle is stale. A message that moves to "
    + "another folder of this mailbox keeps its handle. Somebody can delete a message "
    + "permanently, or move it to an archive mailbox. Then Microsoft 365 gives this answer. "
    + "Find the message again with outlook_search_mail. Then copy the `uri` that the search "
    + "returns. If the search does not find the message, tell the user that the message is not "
    + "in this mailbox now.\n\n"
    + "If you call this tool again with the same arguments, the call will fail the same way."
)

_SEARCH_FOLDER_ONLY: frozenset[str] = frozenset(
    MailSearchFolder().get_field_deserializers()
) - frozenset(MailFolder().get_field_deserializers())

assert _SEARCH_FOLDER_ONLY, (
    "MailSearchFolder declares no property of its own, so the destination check below accepts "
    "every search folder silently"
)


_DESCRIPTION = """\
Copies messages into another folder of the signed-in user's own mailbox or, with `mailbox`, a \
shared or delegated one. A copy is a new message, and the original stays where it is. \
outlook_move_mail is the tool to move a message instead.

Notes:
- This tool asks the user to agree before it changes a shared or delegated mailbox. It changes the \
user's own mailbox without a question.
- The answer has one row for each message. A row that succeeded has a `new_uri`, which is the \
handle of the copy. A row can fail while the other rows succeed.
- If a call times out, do not call this tool again first. A second call can make a second copy of \
each message. Before you call again, make sure that outlook_list_mail does not show the copies in \
the destination folder.
"""

_AGREE = "copy"
_DECLINE = "do not copy"
_NOTHING_COPIED = "No message was copied."

_SOMEONE_ELSES = "That mailbox belongs to someone else, not to the signed-in user."

_BOTH_DESTINATIONS = (
    "outlook_copy_mail copies mail into one folder. So `destination` and `folder_ref` are "
    + "alternatives, not a pair. `destination` names a well-known folder such as `archive`. "
    + "`folder_ref` addresses any folder, with the handle that outlook_browse_folders reported "
    + "for it. Pass one of the two and omit the other. No message was copied."
)

_NO_DESTINATION = (
    "outlook_copy_mail was given no destination, so there was nowhere to copy the mail. No "
    + "message was copied. Pass `destination` for a well-known folder: `inbox`, `sentitems`, "
    + "`drafts`, `archive`, `deleteditems`, `junkemail`, or `clutter`. Or pass `folder_ref` for "
    + "any other folder. Use the `uri` of an outlook_browse_folders result. Pass exactly one of "
    + "the two, never neither."
)

_NOT_A_FOLDER_HANDLE = (
    "outlook_copy_mail takes a folder handle in `folder_ref`. A folder handle looks like "
    + "outlook:///folders/{id}. Copy it from the `uri` of an outlook_browse_folders result. A "
    + "folder name is not a folder handle. A message handle is not one either. For Deleted Items "
    + "and the other well-known folders, use `destination` instead. No message was copied."
)

_NOT_A_MESSAGE_HANDLE = (
    "outlook_copy_mail takes message handles in `message_refs`. A message handle looks like "
    + "outlook:///messages/{id}. Take it from the `uri` of an outlook_search_mail, "
    + "outlook_list_mail, or outlook_read_thread result. One value in `message_refs` is not a "
    + "message handle. A subject line, an email address, an Outlook web link, and a bare message "
    + "id are not handles. A folder handle, a draft handle, and a rule handle are not message "
    + "handles either. This tool makes sure that every handle is valid before it copies a "
    + "message. No message was copied. Fix the value and call again with the whole batch."
)

_HIDDEN_DESTINATION = (
    "That folder is hidden from the user in Outlook. If you copy mail into it, the mail "
    + "disappears from the view of the user. outlook_copy_mail will not copy mail there. No "
    + "message was copied. Pick a folder that the user can see. outlook_browse_folders lists "
    + "the folders that the user can see. It leaves out the hidden folders unless you ask for "
    + "them."
)

_SEARCH_FOLDER_DESTINATION = (
    "That handle addresses a search folder. A search folder is a saved query over other "
    + "folders. It does not hold messages. outlook_copy_mail will not copy mail into it. No "
    + "message was copied. Copy the mail into the real folder that it belongs in. "
    + "outlook_browse_folders reports the handle of that folder. Then any search folder with a "
    + "matching query shows the copy."
)


class CopiedMessage(BaseModel):
    uri: str = Field(
        description=(
            "This is the handle that the request gave for this message. The original stays in "
            "its folder, so this handle still addresses the original."
        )
    )
    new_uri: str | None = Field(
        description=(
            "This is the handle of the copy, as Microsoft 365 gave it. The copy is a new "
            "message in the destination folder. This field is null when Microsoft 365 did not "
            "copy the message."
        )
    )
    copied: bool = Field(
        description=(
            "This says if Microsoft 365 copied this one message. Results are for each message "
            "and not for the whole call."
        )
    )
    error: str | None = Field(
        description=(
            "This is what Microsoft 365 said when it did not copy this message. This field is "
            "null when the message was copied. After a timeout or an outage, a copy can exist. "
            "Before you copy the message again, make sure that outlook_list_mail does not show "
            "it in the destination folder."
        )
    )


class MailCopied(BaseModel):
    destination: str = Field(
        description=(
            "The name of the folder that received the copies. It is a well-known folder name, "
            "or the display name that Microsoft 365 gave to the folder."
        )
    )
    messages: list[CopiedMessage] = Field(
        description=(
            "One row for each handle in `message_refs`, in the same order. A row says if the "
            "copy was made and gives the handle of the copy."
        )
    )
    copied_count: int = Field(
        description=(
            "The number of rows in `messages` where `copied` is true. Each of these rows has a "
            "`new_uri`."
        )
    )
    failed_count: int = Field(
        description=(
            "The number of rows in `messages` where `copied` is false. Read `error` in each of "
            "these rows to see why."
        )
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
    result: CopiedMessage
    failure: GraphFailure | None


async def copy_mail(
    client: GraphServiceClient,
    *,
    message_refs: Sequence[str],
    confirm: Confirm,
    destination: WellKnownFolder | None = None,
    folder_ref: str | None = None,
    mailbox: str | None = None,
) -> MailCopied | InputRequiredResult:
    assert len(message_refs) >= 1, "the schema admits no empty batch"
    handles = _message_handles(message_refs)
    wanted = _destination_asked_for(destination, folder_ref)
    reached = graph_mailbox(client, mailbox)

    answer: Confirmed = None
    attempts: list[_Attempt] = []
    with graph_errors(TOOL_NAME):
        target = await _destination(reached, wanted)
        if not isinstance(target, _Unusable):
            if mailbox is not None:
                with not_graph():
                    answer = await confirm(
                        _question(mailbox, len(handles), target), _about(mailbox, handles, target)
                    )
            if answer is None:
                attempts = [
                    await _copy_one(reached, handle=handle, into=target) for handle in handles
                ]
                _raise_when_nothing_copied(attempts)

    if isinstance(target, _Unusable):
        raise ToolError(target.refusal)
    if isinstance(answer, InputRequiredResult):
        return answer
    if answer is not None:
        raise ToolError(answer)
    return _answer(target, attempts)


def _question(mailbox: str, count: int, target: _Destination) -> str:
    messages = f"{count} {'message' if count == 1 else 'messages'}"
    return (
        f"Copy {messages} in the mailbox {cut_for_a_question(mailbox)!r} to the folder "
        + f"{cut_for_a_question(target.name)!r}? "
        + _SOMEONE_ELSES
    )


def _about(mailbox: str, handles: Sequence[MailMessageHandle], target: _Destination) -> str:
    parts = (mailbox, target.folder_id, *(handle.uri for handle in handles))
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_AGREE, decline=_DECLINE, nothing_happened=_NOTHING_COPIED)


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


async def _copy_one(
    reached: UserItemRequestBuilder, *, handle: MailMessageHandle, into: _Destination
) -> _Attempt:
    try:
        with graph_step(STEP_COPY):
            copied = await reached.messages.by_message_id(handle.message_id).copy.post(
                CopyPostRequestBody(destination_id=into.folder_id),
                request_configuration=_copy_request(),
            )
    except GraphFailure as failure:
        return _Attempt(
            result=CopiedMessage(uri=handle.uri, new_uri=None, copied=False, error=str(failure)),
            failure=failure,
        )
    assert copied is not None and copied.id is not None, (
        "Graph answered a copy with no message, so there is no id of the copy to hand back"
    )
    return _Attempt(
        result=CopiedMessage(
            uri=handle.uri, new_uri=MailMessageHandle(copied.id).uri, copied=True, error=None
        ),
        failure=None,
    )


def _copy_request() -> RequestConfiguration[QueryParameters]:
    return RequestConfiguration[QueryParameters](headers=immutable_id_headers(), options=no_retry())


def _raise_when_nothing_copied(attempts: Sequence[_Attempt]) -> None:
    if any(attempt.result.copied for attempt in attempts):
        return
    failed = next((attempt.failure for attempt in attempts if attempt.failure is not None), None)
    if failed is not None:
        raise failed


def _answer(target: _Destination, attempts: Sequence[_Attempt]) -> MailCopied:
    results = [attempt.result for attempt in attempts]
    return MailCopied(
        destination=target.name,
        messages=results,
        copied_count=sum(1 for result in results if result.copied),
        failed_count=sum(1 for result in results if not result.copied),
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Copy Mail to a Folder",
        description=_DESCRIPTION,
        annotations=WRITE_ADDITIVE,
    )
    async def outlook_copy_mail(
        message_refs: Annotated[
            list[str],
            Field(
                min_length=1,
                description=(
                    "The messages to copy. Each one is the `uri` of an outlook_search_mail, "
                    "outlook_list_mail, or outlook_read_thread result. The original of each "
                    "message stays where it is."
                ),
            ),
        ],
        ctx: Context,
        destination: Annotated[
            WellKnownFolder | None,
            Field(
                description=(
                    "The well-known folder to copy into: `inbox`, `sentitems`, `drafts`, "
                    "`archive`, `deleteditems`, `junkemail`, or `clutter`. Use this or "
                    "`folder_ref`, never both."
                )
            ),
        ] = None,
        folder_ref: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The folder to copy into, as the `uri` of a folder in an "
                    "outlook_browse_folders result. Use this or `destination`, never both."
                ),
            ),
        ] = None,
        mailbox: Annotated[str | None, Field(min_length=1, description=MAILBOX_FIELD)] = None,
        client: GraphServiceClient = graph,
    ) -> MailCopied | InputRequiredResult:
        return await copy_mail(
            client,
            message_refs=message_refs,
            confirm=a_person_agrees(ctx),
            destination=destination,
            folder_ref=folder_ref,
            mailbox=mailbox,
        )
