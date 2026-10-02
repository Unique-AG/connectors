from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.mail_folder import MailFolder
from msgraph.generated.users.item.user_item_request_builder import UserItemRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.handles import MailFolderHandle, mail_folder_handle
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    MAILBOX_FIELD,
    WRITE_ADDITIVE,
    Confirm,
    Confirmed,
    confirmation_digest,
    graph_client_for_caller,
    graph_mailbox,
    person_confirms,
)

TOOL_NAME = "outlook_create_folder"

STEP_CREATE = "create_folder"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Mail.ReadWrite", "Mail.ReadWrite.Shared")

CHANGE_SHOWN_BY: tuple[str, ...] = ("outlook_browse_folders",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"name": "Invoices 2026"}

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return an item that this call needed, and no folder was created. "
    + "If you passed `parent_ref`, the parent folder is the probable cause, because the handle "
    + "is well formed. A person probably deleted the folder, or moved it. Microsoft 365 can give "
    + "a moved folder a new id. Call outlook_browse_folders again. Then use the `uri` that it "
    + "reports now.\n\n"
    + "If you did not pass `parent_ref`, the `mailbox` value is the probable cause. If you call "
    + "this tool again with the same arguments, the call will fail the same way."
)

_AGREE = "create"
_DECLINE = "do not create"
_NOTHING_CREATED = "No folder was created."

_SOMEONE_ELSES = "That mailbox belongs to someone else, not to the signed-in user."

_AT_THE_TOP = "at the top level of"
_INSIDE_A_FOLDER = "inside a folder of"

_DESCRIPTION = """\
Creates one new mail folder, at the top level of a mailbox or inside the folder that `parent_ref` \
names. It acts on the signed-in user's own mailbox or, with `mailbox`, on a shared or delegated \
one. To put mail in the new folder, use outlook_move_mail.

Notes:
- This tool asks the user to agree before it changes a shared or delegated mailbox. \
It changes the user's own mailbox without a question.
- If a call times out, do not call this tool again first. Before you call again, make sure that \
outlook_browse_folders does not show a folder named `name` at that level.
"""

_NOT_A_FOLDER_HANDLE = (
    "outlook_create_folder takes a folder handle in `parent_ref`: outlook:///folders/{id}, "
    + "exactly as outlook_browse_folders reported it in `uri`. A folder's name is not one. "
    + "A well-known name such as `inbox` is not one. A message handle is not one. To create "
    + "the folder at the top level of the mailbox, omit `parent_ref`. No folder was created."
)


class CreatedFolder(BaseModel):
    uri: str = Field(
        description=(
            "The handle of the new folder, outlook:///folders/{id}, from the answer of Microsoft "
            "365. Pass it as `folder_ref` to outlook_move_mail, outlook_rename_folder or "
            "outlook_delete_folder, or as `parent_ref` to this tool."
        )
    )
    display_name: str | None = Field(
        description=(
            "The name that Microsoft 365 stored for the new folder. Read the name from here, "
            "and not from the `name` argument. The value is null when Microsoft 365 reports none."
        )
    )


async def create_folder(
    client: GraphServiceClient,
    *,
    name: str,
    confirm: Confirm,
    parent_ref: str | None = None,
    mailbox: str | None = None,
) -> CreatedFolder | InputRequiredResult:
    assert name, "the schema admits no empty name"
    parent = _parent_folder(parent_ref)
    reached = graph_mailbox(client, mailbox)

    answer: Confirmed = None
    created: MailFolder | None = None
    with graph_errors(TOOL_NAME):
        if mailbox is not None:
            with not_graph():
                answer = await confirm(
                    _question(mailbox, name, parent), _about(mailbox, name, parent)
                )
        if answer is None:
            with graph_step(STEP_CREATE):
                created = await _post_folder(reached, name=name, parent=parent)

    if isinstance(answer, InputRequiredResult):
        return answer
    if answer is not None:
        raise ToolError(answer)
    assert created is not None and created.id is not None, (
        "Graph answered a folder create with no folder, so there is no id to hand back"
    )
    return CreatedFolder(uri=MailFolderHandle(created.id).uri, display_name=created.display_name)


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_AGREE, decline=_DECLINE, nothing_happened=_NOTHING_CREATED)


def _parent_folder(parent_ref: str | None) -> MailFolderHandle | None:
    if parent_ref is None:
        return None
    handle = mail_folder_handle(parent_ref)
    if handle is None:
        raise ToolError(_NOT_A_FOLDER_HANDLE)
    return handle


def _question(mailbox: str, name: str, parent: MailFolderHandle | None) -> str:
    where = _AT_THE_TOP if parent is None else _INSIDE_A_FOLDER
    return (
        f"Create the folder {cut_for_a_question(name)!r} {where} the mailbox "
        + f"{cut_for_a_question(mailbox)!r}? "
        + _SOMEONE_ELSES
    )


def _about(mailbox: str, name: str, parent: MailFolderHandle | None) -> str:
    return confirmation_digest(mailbox, name, None if parent is None else parent.folder_id)


async def _post_folder(
    reached: UserItemRequestBuilder, *, name: str, parent: MailFolderHandle | None
) -> MailFolder | None:
    folder = MailFolder(display_name=name)
    request = RequestConfiguration[QueryParameters](options=no_retry())
    if parent is None:
        return await reached.mail_folders.post(folder, request_configuration=request)
    return await reached.mail_folders.by_mail_folder_id(parent.folder_id).child_folders.post(
        folder, request_configuration=request
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Create a Mail Folder",
        description=_DESCRIPTION,
        annotations=WRITE_ADDITIVE,
    )
    async def outlook_create_folder(
        name: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The name of the new folder, as the user writes it. Microsoft 365 refuses a "
                    "name that another folder at the same level already has. The answer's "
                    "`display_name` is what Microsoft 365 stored."
                ),
            ),
        ],
        ctx: Context,
        parent_ref: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The folder to create the new folder inside, as the `uri` of an "
                    "outlook_browse_folders result. Omit it to create the folder at the top "
                    "level of the mailbox."
                ),
            ),
        ] = None,
        mailbox: Annotated[str | None, Field(min_length=1, description=MAILBOX_FIELD)] = None,
        client: GraphServiceClient = graph,
    ) -> CreatedFolder | InputRequiredResult:
        return await create_folder(
            client,
            name=name,
            confirm=a_person_agrees(ctx),
            parent_ref=parent_ref,
            mailbox=mailbox,
        )
