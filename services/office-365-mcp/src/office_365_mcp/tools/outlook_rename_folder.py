import hashlib
import json
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
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.handles import MailFolderHandle, mail_folder_handle
from office_365_mcp.shared.mail import OUTLOOK_FOLDER_NAMES, made_by_outlook
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    MAILBOX_FIELD,
    WRITE_IDEMPOTENT,
    Confirm,
    Confirmed,
    graph_client_for_caller,
    graph_mailbox,
    person_confirms,
)

TOOL_NAME = "outlook_rename_folder"

STEP_READ_FOLDER = "mail_folder"
STEP_RENAME = "rename_folder"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Mail.ReadWrite", "Mail.ReadWrite.Shared")

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "folder_ref": "outlook:///folders/AQMkADAwSYNTHETIC-folder-0001",
    "name": "Invoices 2025",
}

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return the folder that this call named, and nothing was renamed. "
    + "The handle is well formed. A person probably deleted the folder, or moved it. Microsoft "
    + "365 can give a moved folder a new id. Call outlook_browse_folders again. Then use the "
    + "`uri` that it reports now. If you call this tool again with the same arguments, the call "
    + "will fail the same way."
)

_AGREE = "rename"
_DECLINE = "do not rename"
_NOTHING_RENAMED = "The folder was not renamed."

_SOMEONE_ELSES = "That mailbox belongs to someone else, not to the signed-in user."

_FOLDER_FIELDS: tuple[str, ...] = ("id", "parentFolderId", "displayName")

_FolderQuery = MailFolderItemRequestBuilder.MailFolderItemRequestBuilderGetQueryParameters

_DESCRIPTION = """\
Changes the name of one mail folder and nothing else. The folder keeps its mail and its \
subfolders. It acts on the signed-in user's own mailbox or, with `mailbox`, on a shared or \
delegated one. outlook_browse_folders lists the folders and their handles.

Notes:
- This tool asks the user to agree before it changes a shared or delegated mailbox. \
It changes the user's own mailbox without a question.
- This tool refuses a folder that Outlook creates for every mailbox, such as Inbox.
- This call is safe to repeat after a timeout.
"""

_NOT_A_FOLDER_HANDLE = (
    "outlook_rename_folder takes a folder handle in `folder_ref`: outlook:///folders/{id}, "
    + "exactly as outlook_browse_folders reported it in `uri`. A folder's name is not one. "
    + "A well-known name such as `inbox` is not one. A message handle is not one. Nothing was "
    + "renamed."
)


class RenamedFolder(BaseModel):
    uri: str = Field(
        description=(
            "The handle of the renamed folder, outlook:///folders/{id}, from the answer of "
            "Microsoft 365. Pass it as `folder_ref` to outlook_move_mail or "
            "outlook_delete_folder, or as `parent_ref` to outlook_create_folder."
        )
    )
    display_name: str | None = Field(
        description=(
            "The name that Microsoft 365 stored for the folder. Read the name from here, and "
            "not from the `name` argument. The value is null when Microsoft 365 reports none."
        )
    )


async def rename_folder(
    client: GraphServiceClient,
    *,
    folder_ref: str,
    name: str,
    confirm: Confirm,
    mailbox: str | None = None,
) -> RenamedFolder | InputRequiredResult:
    assert name, "the schema admits no empty name"
    handle = _folder(folder_ref)
    reached = graph_mailbox(client, mailbox)
    folder = reached.mail_folders.by_mail_folder_id(handle.folder_id)

    answer: Confirmed = None
    renamed: MailFolder | None = None
    with graph_errors(TOOL_NAME):
        with graph_step(STEP_READ_FOLDER):
            read = await folder.get(
                request_configuration=RequestConfiguration[_FolderQuery](
                    query_parameters=_FolderQuery(select=list(_FOLDER_FIELDS))
                )
            )
        assert read is not None and read.id is not None, (
            "Graph answered a mail folder read with no folder or no id"
        )
        current = read.display_name or handle.uri
        if await made_by_outlook(reached.mail_folders, read.id, read.parent_folder_id):
            answer = _outlook_makes(current)
        elif mailbox is not None:
            with not_graph():
                answer = await confirm(
                    _question(mailbox, current, name), _about(mailbox, handle, name)
                )
        if answer is None:
            with graph_step(STEP_RENAME):
                renamed = await folder.patch(
                    MailFolder(display_name=name),
                    request_configuration=RequestConfiguration[QueryParameters](options=no_retry()),
                )

    if isinstance(answer, InputRequiredResult):
        return answer
    if answer is not None:
        raise ToolError(answer)
    assert renamed is not None and renamed.id is not None, (
        "Graph answered a folder rename with no folder, so there is no id to hand back"
    )
    return RenamedFolder(uri=MailFolderHandle(renamed.id).uri, display_name=renamed.display_name)


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_AGREE, decline=_DECLINE, nothing_happened=_NOTHING_RENAMED)


def _folder(folder_ref: str) -> MailFolderHandle:
    handle = mail_folder_handle(folder_ref)
    if handle is None:
        raise ToolError(_NOT_A_FOLDER_HANDLE)
    if handle.folder_id.casefold() in OUTLOOK_FOLDER_NAMES:
        raise ToolError(_outlook_makes(handle.folder_id))
    return handle


def _outlook_makes(named: str) -> str:
    return (
        f"Outlook creates the folder {cut_for_a_question(named)!r} for every mailbox. "
        + "This tool does not rename it. Nothing was renamed. If you call this tool again with "
        + "the same arguments, the call will fail the same way."
    )


def _question(mailbox: str, current: str, name: str) -> str:
    return (
        f"Rename the folder {cut_for_a_question(current)!r} in the mailbox "
        + f"{cut_for_a_question(mailbox)!r} to {cut_for_a_question(name)!r}? "
        + _SOMEONE_ELSES
    )


def _about(mailbox: str, handle: MailFolderHandle, name: str) -> str:
    bound = [mailbox, handle.folder_id, name]
    return hashlib.sha256(json.dumps(bound).encode()).hexdigest()


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Rename a Mail Folder",
        description=_DESCRIPTION,
        annotations=WRITE_IDEMPOTENT,
    )
    async def outlook_rename_folder(
        folder_ref: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The folder to rename, as the `uri` of an outlook_browse_folders result or "
                    "of an outlook_create_folder answer. A well-known name such as `inbox` is "
                    "not a handle."
                ),
            ),
        ],
        name: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The new name of the folder, as the user writes it. Microsoft 365 refuses a "
                    "name that another folder at the same level already has. The answer's "
                    "`display_name` is what Microsoft 365 stored."
                ),
            ),
        ],
        ctx: Context,
        mailbox: Annotated[str | None, Field(min_length=1, description=MAILBOX_FIELD)] = None,
        client: GraphServiceClient = graph,
    ) -> RenamedFolder | InputRequiredResult:
        return await rename_folder(
            client,
            folder_ref=folder_ref,
            name=name,
            confirm=a_person_agrees(ctx),
            mailbox=mailbox,
        )
