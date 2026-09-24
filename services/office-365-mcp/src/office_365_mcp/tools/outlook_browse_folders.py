from collections.abc import Mapping
from typing import Annotated, Self

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.mail_folder import MailFolder
from msgraph.generated.models.mail_folder_collection_response import MailFolderCollectionResponse
from msgraph.generated.users.item.mail_folders.item.child_folders.child_folders_request_builder import (  # noqa: E501
    ChildFoldersRequestBuilder,
)
from msgraph.generated.users.item.mail_folders.mail_folders_request_builder import (
    MailFoldersRequestBuilder,
)
from msgraph.generated.users.item.user_item_request_builder import UserItemRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import collect_pages, graph_errors
from office_365_mcp.shared.handles import MailFolderHandle, mail_folder_handle
from office_365_mcp.shared.seam import (
    MAILBOX_FIELD,
    READ_ONLY,
    graph_client_for_caller,
    graph_mailbox,
)

TOOL_NAME = "outlook_browse_folders"

STEP = "mail_folders"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Mail.Read", "Mail.Read.Shared")

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {}

GRAPH_NOT_FOUND = (
    "Microsoft 365 will not return this folder. The handle is well formed, so most likely the "
    + "folder was deleted, or it was moved or copied and Outlook gave it a new id. Call "
    + "outlook_browse_folders on the level above with no `parent` and take the `uri` it reports "
    + "now. Retrying with this one will fail identically."
)

MAX_FOLDERS = 200

_FOLDER_FIELDS: tuple[str, ...] = (
    "id",
    "displayName",
    "totalItemCount",
    "unreadItemCount",
    "childFolderCount",
    "isHidden",
)

_INCLUDE_HIDDEN = "true"

_FoldersQuery = MailFoldersRequestBuilder.MailFoldersRequestBuilderGetQueryParameters
_ChildFoldersQuery = ChildFoldersRequestBuilder.ChildFoldersRequestBuilderGetQueryParameters

_DESCRIPTION = (
    "Lists the folders immediately under one level of a mail folder tree, with a handle for "
    + "each folder. Returns one level only, never the whole tree."
)

_NOT_A_FOLDER_HANDLE = (
    "outlook_browse_folders takes a folder handle, outlook:///folders/{id}, exactly as an earlier "
    + "call reported it in `uri`. A folder's name is not one, nor is a well-known name such as "
    + "`inbox`, nor a message handle. Omit `parent` entirely to browse the top of the mailbox."
)


class MailFolderSummary(BaseModel):
    uri: str = Field(description="A handle for this folder; pass it back as `parent`.")
    display_name: str | None = Field(description="The folder's name, or null if none.")
    total_items: int | None = Field(
        description="An upper bound on items of every kind this folder holds, or null if unset."
    )
    unread_items: int | None = Field(
        description="An upper bound on unread items in this folder, or null if unset."
    )
    child_folder_count: int | None = Field(
        description="How many folders sit directly under this one, or null if unset."
    )
    is_hidden: bool | None = Field(
        description="Whether Outlook hides this folder from the user, or null if unset."
    )

    @classmethod
    def from_folder(cls, folder: MailFolder) -> Self:
        assert folder.id is not None, "Graph returned a mail folder with no id"
        return cls(
            uri=MailFolderHandle(folder.id).uri,
            display_name=folder.display_name,
            total_items=folder.total_item_count,
            unread_items=folder.unread_item_count,
            child_folder_count=folder.child_folder_count,
            is_hidden=folder.is_hidden,
        )


class MailFolderLevel(BaseModel):
    folders: list[MailFolderSummary] = Field(
        description="The folders immediately under the named folder, one level, never the tree."
    )
    capped: bool = Field(
        description="Whether `limit` stopped the listing while more of this level remained."
    )


async def browse_folders(
    client: GraphServiceClient,
    *,
    parent: str | None = None,
    include_hidden: bool = False,
    limit: int,
    mailbox: str | None = None,
) -> MailFolderLevel:
    assert 1 <= limit <= MAX_FOLDERS, f"limit must be within 1..{MAX_FOLDERS}, got {limit}"
    handle = _parent_folder(parent)
    reached = graph_mailbox(client, mailbox)

    with graph_errors(TOOL_NAME, step=STEP):
        first_page = await _first_page(
            reached, parent=handle, include_hidden=include_hidden, limit=limit
        )
        assert first_page is not None, "Graph answered a folder listing with no collection"
        collected = await collect_pages(first_page, client, limit=limit)

    return MailFolderLevel(
        folders=[MailFolderSummary.from_folder(folder) for folder in collected.items],
        capped=collected.capped,
    )


def _parent_folder(parent: str | None) -> MailFolderHandle | None:
    if parent is None:
        return None
    handle = mail_folder_handle(parent)
    if handle is None:
        raise ToolError(_NOT_A_FOLDER_HANDLE)
    return handle


async def _first_page(
    reached: UserItemRequestBuilder,
    *,
    parent: MailFolderHandle | None,
    include_hidden: bool,
    limit: int,
) -> MailFolderCollectionResponse | None:
    hidden = _INCLUDE_HIDDEN if include_hidden else None
    if parent is None:
        return await reached.mail_folders.get(
            request_configuration=RequestConfiguration[_FoldersQuery](
                query_parameters=_FoldersQuery(
                    select=list(_FOLDER_FIELDS),
                    top=limit,
                    include_hidden_folders=hidden,
                )
            )
        )
    return await reached.mail_folders.by_mail_folder_id(parent.folder_id).child_folders.get(
        request_configuration=RequestConfiguration[_ChildFoldersQuery](
            query_parameters=_ChildFoldersQuery(
                select=list(_FOLDER_FIELDS),
                top=limit,
                include_hidden_folders=hidden,
            )
        )
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Browse Mail Folders",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def outlook_browse_folders(
        parent: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "The folder whose children to list, as an earlier result's `uri`. Omit for "
                    + "the top of the mailbox."
                ),
            ),
        ] = None,
        include_hidden: Annotated[
            bool,
            Field(description="Set to `true` to include folders that Outlook hides from the user."),
        ] = False,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_FOLDERS,
                description=f"How many folders to return from this level, at most {MAX_FOLDERS}.",
            ),
        ] = 50,
        mailbox: Annotated[str | None, Field(min_length=1, description=MAILBOX_FIELD)] = None,
        client: GraphServiceClient = graph,
    ) -> MailFolderLevel:
        return await browse_folders(
            client, parent=parent, include_hidden=include_hidden, limit=limit, mailbox=mailbox
        )
