"""`outlook_browse_folders` — one level of the mail folder tree, and a handle for each folder.

**This call returns one level, and Graph offers no other shape.** Microsoft says: "This
operation doesn't return all mail folders in a mailbox, only the child folders of the root
folder. To return all mail folders in a mailbox, each child folder must be traversed
separately" (https://learn.microsoft.com/en-us/graph/api/user-list-mailfolders). So the answer
reports which folders have more underneath, through `child_folder_count`, instead of posing as
the whole tree. The description also says, in as many words, that one call is not an inventory
of the mailbox. A model that answers "the mailbox has these folders" after one call has read
only one level. That model named one level as if it were the whole mailbox.

**Graph omits hidden folders by default.** `includeHiddenFolders=true` is the only way past
this default. A folder that Outlook does not display to the user still holds mail. It is a real
place that a message can be, and not a technicality.

**The counts are free here, and expensive anywhere else.** `totalItemCount` and
`unreadItemCount` sit on the folder object. Microsoft recommends them over a count of a
folder's messages with `$count` and `$filter`, which "can incur significant latency"
(https://learn.microsoft.com/en-us/graph/api/resources/mailfolder). These counts include items
of every type, so they bound the messages in a folder, instead of counting them exactly.

**Microsoft does not promise that a folder id is permanent, on either page.** The immutable-id
page says that container ids "were already constant"
(https://learn.microsoft.com/en-us/graph/outlook-immutable-id). The Mail API overview says that
a `mailFolder` id can change after certain actions, such as a copy or a move. These two pages
contradict each other, so nothing here promises that a handle survives. `uri` names re-browsing
as the recovery, and this works under either page.

**`mailbox` re-points both request builders from `/me` to `/users/{id}`.**
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

# No arguments at all is a valid call for this tool. This is the one call that reaches Graph
# with no handle from a previous response: the top of the mailbox.
GRAPH_CALL_EXAMPLE: Mapping[str, object] = {}

# The default 404 advice says to make sure that the id came from a tool response, with no
# change. That check already passes here, because a folder handle is this connector's own. The
# real reason is different. Microsoft does not promise that the id inside a folder handle
# outlives a copy or a move.
GRAPH_NOT_FOUND = (
    "Microsoft 365 will not return this folder. The handle is well formed, so most likely the "
    + "folder was deleted, or it was moved or copied and Outlook gave it a new id. Call "
    + "outlook_browse_folders on the level above with no `parent` and take the `uri` it reports "
    + "now. Retrying with this one will fail identically."
)

MAX_FOLDERS = 200

# This is every property that the answer reads. `childFolders` is absent on purpose. Expanding
# it is the one way to get a second level in one request. But Graph expands only one level
# either way. So including `childFolders` only moves this tool's boundary. It does not remove
# the boundary.
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

# These are bound, instead of aliased with `type`. These names serve as the constructor for the
# query parameters, and also as the argument for `RequestConfiguration`. A `TypeAliasType` is
# not callable.
_FoldersQuery = MailFoldersRequestBuilder.MailFoldersRequestBuilderGetQueryParameters
_ChildFoldersQuery = ChildFoldersRequestBuilder.ChildFoldersRequestBuilderGetQueryParameters

_DESCRIPTION = """\
Lists the folders immediately under one level of a mail folder tree, with a handle for each \
folder — the signed-in user's own mailbox, or, with `mailbox`, a shared or delegated mailbox. \
This shows what folders exist and how large they are.

Notes:
- Returns one level only, never the tree. A folder whose `child_folder_count` is above zero has \
folders below it that this call did not return.
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
            "This is the handle for this folder. Pass it back as `parent` to browse its "
            + "children. Microsoft does not guarantee that it survives a copy or move. If it "
            + "stops resolving, browse the level above again. Take the handle that is reported "
            + "then, instead of repairing this one."
        )
    )
    display_name: str | None = Field(
        description=(
            "This is the folder's name, as Outlook shows it, for example `Inbox`. Names are "
            + "unique only among folders that share a parent, so two folders named `Archive` on "
            + "different branches are different folders. This field is null when Graph recorded "
            + "none."
        )
    )
    total_items: int | None = Field(
        description=(
            "This is how many items of every kind this folder holds — an upper bound on its "
            + "messages, and not an exact count. This excludes the folders below. This field is "
            + "null when Graph did not report it."
        )
    )
    unread_items: int | None = Field(
        description=(
            "This is how many of `total_items` are unread, on the same terms: an upper bound, "
            + "and not an exact count. This field is null when Graph did not report it."
        )
    )
    child_folder_count: int | None = Field(
        description=(
            "This is how many folders sit directly under this one. This field is null when "
            + "Graph did not report it. A value above zero means that this call did not return "
            + "those folders. Pass this folder's `uri` back as `parent` to see them. Zero is the "
            + "only value that means there is nothing below."
        )
    )
    is_hidden: bool | None = Field(
        description=(
            "This says whether Outlook hides this folder from the user. A hidden folder can "
            + "still hold mail. This field is null when Graph did not report it. This field is "
            + "true only when the caller set `include_hidden`. Graph omits hidden folders "
            + "otherwise."
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
            "These are the folders immediately under the folder that the caller named, in the "
            + "order that Graph returned them — one level, never the tree. A folder here with "
            + "`child_folder_count` above zero has more folders of its own, not in this list. "
            + "An empty list means that this folder has no children, or none visible without "
            + "`include_hidden`."
        )
    )
    capped: bool = Field(
        description=(
            "This is true when `limit` stopped the listing while more of this level remained. "
            + "Raise `limit` to see the rest. `false` means this level ran out on its own. This "
            + "says nothing about the levels below. Read `child_folder_count` for those."
        )
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
        # No request header needs a resupply for each page, because `includeHiddenFolders` is a
        # query option. Graph carries its own query options in the `@odata.nextLink` that it
        # mints.
        collected = await collect_pages(first_page, client, limit=limit)

    return MailFolderLevel(
        folders=[MailFolderSummary.from_folder(folder) for folder in collected.items],
        capped=collected.capped,
    )


def _parent_folder(parent: str | None) -> MailFolderHandle | None:
    """This function returns the folder to list the children of, or `None` for the top of the
    mailbox."""
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
    """This function returns the children of the mailbox root, or the children of one folder,
    from the two collections that Graph publishes.

    This function has two branches, instead of one, because these are two request builders
    with two query-parameter types. The arguments written into each branch are the same.
    """
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
                    "This is the folder whose children to list, as the `uri` of an earlier "
                    + "result: outlook:///folders/{id}. Omit this argument for the folders at "
                    + "the top of the mailbox. A folder name is not a handle, and neither is a "
                    + "well-known name such as `inbox`."
                ),
            ),
        ] = None,
        include_hidden: Annotated[
            bool,
            Field(
                description=(
                    "Set this to `true` to include folders that Outlook hides from the user. "
                    + "This is off by default. Turn it on for a full account of the mailbox. If "
                    + "a message's folder does not appear in an unhidden listing, turn this on "
                    + "too. A hidden folder still holds mail."
                )
            ),
        ] = False,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_FOLDERS,
                description=(
                    "This is how many folders to return from this level, at most "
                    + f"{MAX_FOLDERS}. `capped` says whether more folders remain. This argument "
                    + "bounds this level only — a higher value never reaches the folders below."
                ),
            ),
        ] = 50,
        mailbox: Annotated[str | None, Field(min_length=1, description=MAILBOX_FIELD)] = None,
        client: GraphServiceClient = graph,
    ) -> MailFolderLevel:
        return await browse_folders(
            client, parent=parent, include_hidden=include_hidden, limit=limit, mailbox=mailbox
        )
