from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.mail_folder import MailFolder
from msgraph.generated.users.item.mail_folders.item.mail_folder_item_request_builder import (
    MailFolderItemRequestBuilder,
)
from msgraph.generated.users.item.mail_folders.item.move.move_post_request_body import (
    MovePostRequestBody,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.handles import MailFolderHandle, mail_folder_handle
from office_365_mcp.shared.mail import OUTLOOK_FOLDER_NAMES, made_by_outlook
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    MAILBOX_FIELD,
    WRITE_DESTRUCTIVE,
    Confirm,
    confirmation_digest,
    graph_client_for_caller,
    graph_mailbox,
    person_confirms,
)

TOOL_NAME = "outlook_delete_folder"

STEP_READ_FOLDER = "mail_folder"
STEP_READ_DELETED_ITEMS = "destination_folder"
STEP_MOVE = "move_folder"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Mail.ReadWrite", "Mail.ReadWrite.Shared")

CHANGE_SHOWN_BY: tuple[str, ...] = ("outlook_browse_folders",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "folder_ref": "outlook:///folders/AQMkADAwSYNTHETIC-folder-0001",
}

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return the folder that this call named, and nothing was deleted. "
    + "The handle is well formed. A person probably deleted the folder, or moved it. An earlier "
    + "call of this tool can also have moved it to Deleted Items. Microsoft 365 can give a moved "
    + "folder a new id. Call outlook_browse_folders again. Then use the `uri` that it reports "
    + "now. If you call this tool again with the same arguments, the call will fail the same way."
)

_DELETED_ITEMS = "deleteditems"

_FOLDER_FIELDS: tuple[str, ...] = (
    "displayName",
    "totalItemCount",
    "childFolderCount",
    "parentFolderId",
)

_FolderQuery = MailFolderItemRequestBuilder.MailFolderItemRequestBuilderGetQueryParameters

_AGREE = "delete"
_DECLINE = "keep the folder"
_NOTHING_DELETED = "The folder was not deleted."

_SOMEONE_ELSES = "That mailbox belongs to someone else, not to the signed-in user."

_DESCRIPTION = """\
Moves one mail folder to Deleted Items, with all of its items and subfolders. This is how this \
connector deletes a folder. It never erases anything, and the user can move the folder back from \
Deleted Items in Outlook. It acts on the signed-in user's own mailbox or, with `mailbox`, on a \
shared or delegated one. outlook_browse_folders lists the folders and their handles.

Notes:
- This tool always asks the user to agree, also for the user's own mailbox. The question names \
the folder and how many items and subfolders it holds.
- This tool refuses Deleted Items itself, and a folder that is already directly in Deleted Items. \
It also refuses a folder that Outlook creates for every mailbox, such as Inbox.
- If a call times out, do not call this tool again first. Before you call again, make sure that \
outlook_browse_folders does not show the folder in Deleted Items.
"""

_NOT_A_FOLDER_HANDLE = (
    "outlook_delete_folder takes a folder handle in `folder_ref`: outlook:///folders/{id}, "
    + "exactly as outlook_browse_folders reported it in `uri`. A folder's name is not one. "
    + "A well-known name such as `inbox` is not one. A message handle is not one. Nothing was "
    + "deleted."
)

_DELETED_ITEMS_ITSELF = (
    "That handle addresses Deleted Items itself. outlook_delete_folder moves a folder to Deleted "
    + "Items, so it cannot delete Deleted Items. Nothing was deleted. This connector cannot erase "
    + "mail or folders. If the user wants to erase what Deleted Items holds, tell them to do that "
    + "in Outlook. If you call this tool again with the same arguments, the call will fail the "
    + "same way."
)

_ALREADY_IN_DELETED_ITEMS = (
    "That folder is already in Deleted Items, so outlook_delete_folder did not move it. Nothing "
    + "was deleted. This connector cannot erase mail or folders. If the user wants to erase the "
    + "folder, tell them to do that in Outlook. If you call this tool again with the same "
    + "arguments, the call will fail the same way."
)


class DeletedFolder(BaseModel):
    uri: str = Field(
        description=(
            "The handle of the folder in Deleted Items, from the answer of Microsoft 365. "
            "Microsoft 365 can give a moved folder a new id, so use this handle and not "
            "`folder_ref`."
        )
    )
    display_name: str | None = Field(
        description=(
            "The name that Microsoft 365 stored for the folder after the move. The value is "
            "null when Microsoft 365 reports none."
        )
    )


async def delete_folder(
    client: GraphServiceClient,
    *,
    folder_ref: str,
    confirm: Confirm,
    mailbox: str | None = None,
) -> DeletedFolder | InputRequiredResult:
    handle = _folder(folder_ref)
    reached = graph_mailbox(client, mailbox)
    folders = reached.mail_folders

    asked: InputRequiredResult | None = None
    refused: str | None = None
    moved: MailFolder | None = None
    with graph_errors(TOOL_NAME):
        with graph_step(STEP_READ_FOLDER):
            folder = await folders.by_mail_folder_id(handle.folder_id).get(
                request_configuration=_select(_FOLDER_FIELDS)
            )
        with graph_step(STEP_READ_DELETED_ITEMS):
            deleted_items = await folders.by_mail_folder_id(_DELETED_ITEMS).get(
                request_configuration=_select(("id",))
            )
        assert folder is not None and folder.id is not None, (
            "Graph answered a mail folder read with no folder or no id"
        )
        assert deleted_items is not None and deleted_items.id is not None, (
            "Graph answered the Deleted Items read with no id to move the folder to"
        )
        refused = _refusal(handle, folder, deleted_items.id)
        if refused is None and await made_by_outlook(folders, folder.id, folder.parent_folder_id):
            refused = _outlook_makes(folder.display_name or handle.uri)
        if refused is None:
            with not_graph():
                answer = await confirm(_question(mailbox, handle, folder), _about(mailbox, handle))
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with graph_step(STEP_MOVE):
                moved = await folders.by_mail_folder_id(handle.folder_id).move.post(
                    MovePostRequestBody(destination_id=deleted_items.id),
                    request_configuration=RequestConfiguration[QueryParameters](options=no_retry()),
                )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert moved is not None and moved.id is not None, (
        "Graph answered a folder move with no folder, so there is no id to hand back"
    )
    return DeletedFolder(uri=MailFolderHandle(moved.id).uri, display_name=moved.display_name)


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_AGREE, decline=_DECLINE, nothing_happened=_NOTHING_DELETED)


def _folder(folder_ref: str) -> MailFolderHandle:
    handle = mail_folder_handle(folder_ref)
    if handle is None:
        raise ToolError(_NOT_A_FOLDER_HANDLE)
    if handle.folder_id.casefold() in OUTLOOK_FOLDER_NAMES:
        raise ToolError(_outlook_makes(handle.folder_id))
    return handle


def _select(fields: tuple[str, ...]) -> RequestConfiguration[_FolderQuery]:
    return RequestConfiguration[_FolderQuery](query_parameters=_FolderQuery(select=list(fields)))


def _outlook_makes(named: str) -> str:
    return (
        f"Outlook creates the folder {cut_for_a_question(named)!r} for every mailbox. "
        + "This tool does not move it. Nothing was deleted. If you call this tool again with "
        + "the same arguments, the call will fail the same way."
    )


def _refusal(handle: MailFolderHandle, folder: MailFolder, deleted_items_id: str) -> str | None:
    if deleted_items_id in (handle.folder_id, folder.id):
        return _DELETED_ITEMS_ITSELF
    if folder.parent_folder_id == deleted_items_id:
        return _ALREADY_IN_DELETED_ITEMS
    return None


def _question(mailbox: str | None, handle: MailFolderHandle, folder: MailFolder) -> str:
    named = cut_for_a_question(folder.display_name or handle.uri)
    where = "" if mailbox is None else f" in the mailbox {cut_for_a_question(mailbox)!r}"
    return (
        f"Delete the folder {named!r}{where}? "
        + "This tool moves it to Deleted Items, with everything in it. "
        + f"It holds {_counted(folder.total_item_count, 'item')} and "
        + f"{_counted(folder.child_folder_count, 'subfolder')}. "
        + "It stays recoverable in Deleted Items."
        + ("" if mailbox is None else f" {_SOMEONE_ELSES}")
    )


def _counted(count: int | None, noun: str) -> str:
    if count is None:
        return f"an unknown number of {noun}s"
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _about(mailbox: str | None, handle: MailFolderHandle) -> str:
    return confirmation_digest(mailbox, handle.folder_id)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Delete a Mail Folder",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE,
    )
    async def outlook_delete_folder(
        folder_ref: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The folder to move to Deleted Items, as the `uri` of an "
                    "outlook_browse_folders result or of an outlook_create_folder answer. A "
                    "well-known name such as `inbox` is not a handle."
                ),
            ),
        ],
        ctx: Context,
        mailbox: Annotated[str | None, Field(min_length=1, description=MAILBOX_FIELD)] = None,
        client: GraphServiceClient = graph,
    ) -> DeletedFolder | InputRequiredResult:
        return await delete_folder(
            client, folder_ref=folder_ref, confirm=a_person_agrees(ctx), mailbox=mailbox
        )
