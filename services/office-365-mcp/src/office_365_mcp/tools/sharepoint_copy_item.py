from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.method import Method
from kiota_serialization_json.json_serialization_writer import JsonSerializationWriter
from mcp.types import InputRequiredResult
from msgraph.generated.drives.item.items.item.copy.copy_post_request_body import (
    CopyPostRequestBody,
)
from msgraph.generated.models.drive_item import DriveItem
from msgraph.generated.models.item_reference import ItemReference
from msgraph.generated.models.o_data_errors.o_data_error import ODataError
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import (
    graph_errors,
    graph_step,
    no_retry,
    not_graph,
    request_with_query,
)
from office_365_mcp.shared.files import (
    FAIL_ON_CONFLICT,
    FOLDER_HANDLE_SOURCES,
    ITEM_HANDLE_SOURCES,
    NAME_RULES,
    UNNAMED_ITEM_LABEL,
    folder_label,
    item_for_a_question,
    unusable_name,
)
from office_365_mcp.shared.handles import (
    DriveFileHandle,
    DriveFolderHandle,
    drive_folder_handle,
    drive_item_handle,
)
from office_365_mcp.shared.notes import write_state_for
from office_365_mcp.shared.seam import (
    WRITE_ADDITIVE,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "sharepoint_copy_item"

STEP_COPY = "copy_item"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Files.ReadWrite.All",)

CHANGE_SHOWN_BY: tuple[str, ...] = ("sharepoint_browse_folder",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "item": "sharepoint:///files/b%21SYNTHETICDRIVE0000/01SYNTHETICFILE0000",
    "to_folder": "sharepoint:///folders/b%21SYNTHETICDRIVE0000/01SYNTHETICFOLDER0000",
}

_COPY = "copy"
_DO_NOT_COPY = "do not copy"
_NOTHING_COPIED = "Nothing was copied."

_DESCRIPTION = """\
Starts a copy of one file or folder in OneDrive or SharePoint, for the signed-in user. The copy \
goes into a folder in the same drive or in another drive. The copy of a folder includes everything \
inside it. Microsoft makes the copy after this call returns, so the copy can take some time to \
show. Get both handles from sharepoint_search_files or sharepoint_browse_folder. To move an item \
instead, use sharepoint_move_item. OneDrive and SharePoint can show the change to everyone who can \
open the folder.

Notes:
- This tool asks the user to agree before it creates anything, every time.
- The copy gets the permissions of the destination folder, not the permissions of the original.
- If the destination already holds an item with the same name, the copy fails. This failure can \
come after this call returns, and then this tool cannot show it. To copy an item into its own \
folder, give the copy a new `name`.
- If a call times out, do not call this tool again first. Before you call again, make sure that \
sharepoint_browse_folder does not show the copy in the destination.
"""

_NOT_AN_ITEM_HANDLE = (
    "sharepoint_copy_item takes a file handle or a folder handle in `item`. A file handle looks "
    + "like sharepoint:///files/{drive_id}/{item_id}, and a folder handle looks like "
    + "sharepoint:///folders/{drive_id}/{item_id}. A name, a path and a web address are not "
    + "handles. "
    + ITEM_HANDLE_SOURCES
    + " This same value fails again, so do not retry it."
)

_NOT_A_FOLDER_HANDLE = (
    "sharepoint_copy_item takes a folder handle in `to_folder`. It looks like "
    + "sharepoint:///folders/{drive_id}/{item_id}. A file handle is not a folder handle, because "
    + "a file cannot hold a copy. "
    + FOLDER_HANDLE_SOURCES
    + " This same value fails again, so do not retry it."
)

_TOP_FOLDER_CANNOT_BE_COPIED = (
    "Nothing was copied. The item in `item` is the top folder of a drive, and Microsoft 365 "
    + "cannot copy the top folder of a drive. To copy what is in it, copy the items inside it "
    + "one at a time. Use sharepoint_browse_folder to list them. This same value fails again, so "
    + "do not retry it."
)

_DESTINATION_IS_NOT_A_FOLDER = (
    "Nothing was copied. Microsoft 365 reports that the item in `to_folder` is not a folder, so "
    + "it cannot hold a copy. Use sharepoint_browse_folder to find a folder, and pass the `uri` "
    + "of that folder. This same value fails again, so do not retry it."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not find the item or the destination folder, and nothing was copied. Both "
    + "handles are well formed, so the arguments are not the problem. Somebody probably deleted "
    + "one of the two, or moved it to another drive. A move to another drive gives an item a new "
    + "handle. Find both again with sharepoint_search_files or sharepoint_browse_folder, and take "
    + "the `uri` values from those new results. The same handles fail the same way, so do not "
    + "retry them."
)


class CopyStarted(BaseModel):
    """The copy that Microsoft accepted, with the handles that find it later."""

    source_uri: str = Field(
        description=(
            "The handle of the item that this call copies. It is a file handle or a folder "
            + "handle. The original stays where it is, and this tool does not change it."
        )
    )
    destination_uri: str = Field(
        description=(
            "The handle of the folder that gets the copy, in the shape "
            + "sharepoint:///folders/{drive_id}/{item_id}. Pass it to sharepoint_browse_folder "
            + "to see the copy after Microsoft finishes it."
        )
    )
    name: str | None = Field(
        description=(
            "The name that the copy gets. It is the value of `name`, or the name of the "
            + "original when `name` is not given. This value is null when Graph reported no name "
            + "for the original."
        )
    )


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_COPY, decline=_DO_NOT_COPY, nothing_happened=_NOTHING_COPIED)


async def copy_item(
    client: GraphServiceClient,
    *,
    item: str,
    to_folder: str,
    name: str | None = None,
    confirm: Confirm,
) -> CopyStarted | InputRequiredResult:
    source = drive_item_handle(item)
    if source is None:
        raise ToolError(_NOT_AN_ITEM_HANDLE)
    destination = drive_folder_handle(to_folder)
    if destination is None:
        raise ToolError(_NOT_A_FOLDER_HANDLE)
    if name is not None:
        unusable = unusable_name(name)
        if unusable is not None:
            raise ToolError(unusable)

    about = write_state_for(
        TOOL_NAME,
        source.drive_id,
        source.item_id,
        destination.drive_id,
        destination.item_id,
        name or "",
    )
    started: CopyStarted | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME):
        original = await item_for_a_question(client, source.drive_id, source.item_id)
        target = await item_for_a_question(client, destination.drive_id, destination.item_id)
        refused = _cannot_copy(original, target)
        if refused is None:
            with not_graph():
                answer = await confirm(_question(original, target, name), about)
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            assert target.id is not None, "Graph answered a folder read with no id"
            with graph_step(STEP_COPY):
                await _start_copy(
                    client, source, ItemReference(drive_id=destination.drive_id, id=target.id), name
                )
            started = CopyStarted(
                source_uri=source.uri,
                destination_uri=DriveFolderHandle(destination.drive_id, target.id).uri,
                name=name if name is not None else original.name,
            )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert started is not None, "a copy neither asked about nor refused sent nothing"
    return started


def _cannot_copy(original: DriveItem, target: DriveItem) -> str | None:
    if original.root is not None:
        return _TOP_FOLDER_CANNOT_BE_COPIED
    if target.folder is None:
        return _DESTINATION_IS_NOT_A_FOLDER
    return None


def _question(original: DriveItem, target: DriveItem, name: str | None) -> str:
    item_label = repr(original.name) if original.name else UNNAMED_ITEM_LABEL
    renamed = f" as {name!r}" if name is not None else ""
    return f"Copy {item_label} into {folder_label(target)}{renamed}?"


async def _start_copy(
    client: GraphServiceClient,
    source: DriveFileHandle | DriveFolderHandle,
    parent: ItemReference,
    name: str | None,
) -> None:
    copy = client.drives.by_drive_id(source.drive_id).items.by_drive_item_id(source.item_id).copy
    request = request_with_query(
        Method.POST, copy.url_template, copy.path_parameters, query=FAIL_ON_CONFLICT
    )
    request.headers.try_add("Accept", "application/json")
    request.set_stream_content(_copy_body(parent, name), "application/json")
    request.add_request_options(no_retry())
    await client.request_adapter.send_no_response_content_async(  # pyright: ignore[reportUnknownMemberType]
        request, {"XXX": ODataError}
    )


def _copy_body(parent: ItemReference, name: str | None) -> bytes:
    writer = JsonSerializationWriter()
    writer.write_object_value(
        None,
        CopyPostRequestBody(
            parent_reference=parent,
            name=name,
            children_only=None,
            include_all_version_history=None,
        ),
    )
    return writer.get_serialized_content()


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Copy an Item",
        description=_DESCRIPTION,
        annotations=WRITE_ADDITIVE,
    )
    async def sharepoint_copy_item(
        item: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The file or folder to copy. A file handle and a folder handle both work. "
                    + ITEM_HANDLE_SOURCES
                    + " A web address, a path and a name are not handles. This tool cannot copy "
                    + "the top folder of a drive."
                ),
            ),
        ],
        to_folder: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The folder that gets the copy. "
                    + FOLDER_HANDLE_SOURCES
                    + " A file handle, a path and a web address are not folder handles."
                ),
            ),
        ],
        ctx: Context,
        name: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "A new name for the copy, with the extension for a file. Omit it to keep the "
                    + f"name of the original. {NAME_RULES} If the name does not obey these rules, "
                    + "this tool copies nothing."
                ),
            ),
        ] = None,
        client: GraphServiceClient = graph,
    ) -> CopyStarted | InputRequiredResult:
        return await copy_item(
            client, item=item, to_folder=to_folder, name=name, confirm=a_person_agrees(ctx)
        )
