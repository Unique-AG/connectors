"""`outlook_browse_folders` — one level of the mail folder tree, and a handle for each folder.

**One level, and Graph offers no other shape.** Microsoft: "This operation doesn't return all mail
folders in a mailbox, only the child folders of the root folder. To return all mail folders in a
mailbox, each child folder must be traversed separately"
(https://learn.microsoft.com/en-us/graph/api/user-list-mailfolders). So the answer reports which
folders have more underneath, through `child_folder_count`, rather than posing as the tree. The
description also says, in as many words, that one call is not an inventory of the mailbox. A
model that answers "the mailbox has these folders" after one call only read one level. It named
that level as if it were the whole mailbox.

**Hidden folders are Graph's own default omission**, and `includeHiddenFolders=true` is the only
way past it. A folder Outlook does not display to the user still holds mail, so it is a real place
a message can be, not a technicality.

**The counts are free here and expensive anywhere else.** `totalItemCount` and `unreadItemCount`
sit on the folder object, and Microsoft recommends them over counting a folder's messages with
`$count` and `$filter`, which "can incur significant latency"
(https://learn.microsoft.com/en-us/graph/api/resources/mailfolder). They count items of every type,
so they bound the messages in a folder rather than counting them.

**Microsoft does not promise a folder id is permanent, whichever page you believe.** The
immutable-id page says container ids "were already constant"
(https://learn.microsoft.com/en-us/graph/outlook-immutable-id). The Mail API overview says a
`mailFolder` id can change after certain actions, such as a copy or a move. Two pages, one
contradiction, so nothing here promises a handle survives: `uri` names re-browsing as the recovery,
which is what works under either reading.
"""

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
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import collect_pages, graph_errors
from office_365_mcp.shared.handles import MailFolderHandle, mail_folder_handle
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "outlook_browse_folders"

STEP = "mail_folders"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Mail.Read",)

# No arguments at all is a valid call for this tool. It is the one that reaches Graph without a
# handle from a previous response: the top of the mailbox.
GRAPH_CALL_EXAMPLE: Mapping[str, object] = {}

# The default 404 advice says to check that the id came from a tool response, verbatim. That
# check already passes here: a folder handle is this connector's own. The real reason is
# different. Microsoft does not promise the id inside a folder handle outlives a copy or a move.
GRAPH_NOT_FOUND = (
    "Microsoft 365 will not return this folder. The handle is well formed, so most likely the "
    + "folder was deleted, or it was moved or copied and Outlook gave it a new id. Call "
    + "outlook_browse_folders on the level above with no `parent` and take the `uri` it reports "
    + "now. Retrying with this one will fail identically."
)

MAX_FOLDERS = 200

# Every property the answer reads. `childFolders` is deliberately absent. Expanding it is the
# one way to get a second level in a single request. But Graph expands only one level either
# way. So including `childFolders` only moves this tool's boundary. It does not remove it.
_FOLDER_FIELDS: tuple[str, ...] = (
    "id",
    "displayName",
    "totalItemCount",
    "unreadItemCount",
    "childFolderCount",
    "isHidden",
)

# TRAP: the SDK types `includeHiddenFolders` as `str`, not `bool`. The generated query
# parameter is a plain string appended to the URL. So a Python `True` here reaches Graph as the
# literal string `True`.
_INCLUDE_HIDDEN = "true"

# Bound rather than aliased with `type`. These names serve as the query parameters' constructor,
# and also as `RequestConfiguration`'s argument. A `TypeAliasType` is not callable.
_FoldersQuery = MailFoldersRequestBuilder.MailFoldersRequestBuilderGetQueryParameters
_ChildFoldersQuery = ChildFoldersRequestBuilder.ChildFoldersRequestBuilderGetQueryParameters

_DESCRIPTION = """\
List the folders immediately under one level of the signed-in user's mail folder tree, with a \
handle for each, for discovering what folders exist and how large they are.

Notes:
- Returns one level only, never the tree: a folder whose `child_folder_count` is above zero has \
folders below that this call did not return.
"""

_NOT_A_FOLDER_HANDLE = (
    "outlook_browse_folders takes a folder handle, outlook:///folders/{id}, exactly as an earlier "
    + "call reported it in `uri`. A folder's name is not one, nor is a well-known name such as "
    + "`inbox`, nor a message handle. Omit `parent` entirely to browse the top of the mailbox."
)


class MailFolderSummary(BaseModel):
    """One folder as this level reports it: where it is, how big it is, and whether it has more."""

    uri: str = Field(
        description=(
            "This folder's handle; pass it back as `parent` to browse its children. Not "
            + "guaranteed to survive a copy or move — if it stops resolving, browse the level "
            + "above again and take the handle reported then, rather than repairing this one."
        )
    )
    display_name: str | None = Field(
        description=(
            "The folder's name as Outlook shows it, for example `Inbox`. Names are unique only "
            + "among folders sharing a parent, so two folders named `Archive` on different "
            + "branches are different folders. Null when Graph recorded none."
        )
    )
    total_items: int | None = Field(
        description=(
            "How many items of every kind this folder holds — an upper bound on its messages, "
            + "not a count of them. Excludes the folders below. Null when Graph did not report "
            + "it."
        )
    )
    unread_items: int | None = Field(
        description=(
            "How many of `total_items` are unread, on the same terms: an upper bound, not an "
            + "exact count. Null when Graph did not report it."
        )
    )
    child_folder_count: int | None = Field(
        description=(
            "How many folders sit directly under this one. Null when Graph did not report it. "
            + "Above zero means this call did not return them — pass this folder's `uri` back as "
            + "`parent` to see them; zero is the only value meaning there is nothing below."
        )
    )
    is_hidden: bool | None = Field(
        description=(
            "Whether Outlook hides this folder from the user; a hidden folder can still hold "
            + "mail. Null when Graph did not report it. True only when `include_hidden` was set "
            + "— Graph omits hidden folders otherwise."
        )
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
    """One level of the tree, and nothing about the levels under it."""

    folders: list[MailFolderSummary] = Field(
        description=(
            "The folders immediately under the one asked about, in the order Graph returned "
            + "them — one level, never the tree. A folder here with `child_folder_count` above "
            + "zero has more of its own, not in this list. Empty means this folder has no "
            + "children, or none visible without `include_hidden`."
        )
    )
    capped: bool = Field(
        description=(
            "True when `limit` stopped the listing while more of this level remained; raise "
            + "`limit` to see them. False means this level ran out on its own. Says nothing "
            + "about the levels below — read `child_folder_count` for those."
        )
    )


async def browse_folders(
    client: GraphServiceClient,
    *,
    parent: str | None = None,
    include_hidden: bool = False,
    limit: int,
) -> MailFolderLevel:
    assert 1 <= limit <= MAX_FOLDERS, f"limit must be within 1..{MAX_FOLDERS}, got {limit}"
    handle = _parent_folder(parent)

    with graph_errors(TOOL_NAME, step=STEP):
        first_page = await _first_page(
            client, parent=handle, include_hidden=include_hidden, limit=limit
        )
        assert first_page is not None, "Graph answered a folder listing with no collection"
        # No request header needs resupply per page: `includeHiddenFolders` is a query option.
        # Graph carries its own query options in the `@odata.nextLink` it mints.
        collected = await collect_pages(first_page, client, limit=limit)

    return MailFolderLevel(
        folders=[MailFolderSummary.from_folder(folder) for folder in collected.items],
        capped=collected.capped,
    )


def _parent_folder(parent: str | None) -> MailFolderHandle | None:
    """The folder to list the children of, or None for the top of the mailbox."""
    if parent is None:
        return None
    handle = mail_folder_handle(parent)
    if handle is None:
        raise ToolError(_NOT_A_FOLDER_HANDLE)
    return handle


async def _first_page(
    client: GraphServiceClient,
    *,
    parent: MailFolderHandle | None,
    include_hidden: bool,
    limit: int,
) -> MailFolderCollectionResponse | None:
    """The mailbox root's children, or one folder's, from the two collections Graph publishes.

    Two branches rather than one, because they are two request builders with two
    query-parameter types. The arguments spelled into each are the same.
    """
    hidden = _INCLUDE_HIDDEN if include_hidden else None
    if parent is None:
        return await client.me.mail_folders.get(
            request_configuration=RequestConfiguration[_FoldersQuery](
                query_parameters=_FoldersQuery(
                    select=list(_FOLDER_FIELDS),
                    top=limit,
                    include_hidden_folders=hidden,
                )
            )
        )
    return await client.me.mail_folders.by_mail_folder_id(parent.folder_id).child_folders.get(
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
                    "The folder whose children to list, as the `uri` of an earlier result: "
                    + "outlook:///folders/{id}. Omit it for the folders at the top of the "
                    + "mailbox. A folder name is not a handle, and neither is a well-known name "
                    + "such as `inbox`."
                ),
            ),
        ] = None,
        include_hidden: Annotated[
            bool,
            Field(
                description=(
                    "Include folders Outlook hides from the user; off by default. Turn it on for "
                    + "a full account of the mailbox, or when a message's folder does not appear "
                    + "in an unhidden listing. A hidden folder still holds mail."
                )
            ),
        ] = False,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_FOLDERS,
                description=(
                    f"How many folders to return from this level, at most {MAX_FOLDERS}; "
                    + "`capped` says whether more remain. Bounds this level only — a higher "
                    + "value never reaches the folders below."
                ),
            ),
        ] = 50,
        client: GraphServiceClient = graph,
    ) -> MailFolderLevel:
        return await browse_folders(
            client, parent=parent, include_hidden=include_hidden, limit=limit
        )
