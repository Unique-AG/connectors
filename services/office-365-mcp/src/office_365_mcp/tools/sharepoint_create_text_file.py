import hashlib
from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.method import Method
from kiota_abstractions.request_information import RequestInformation
from mcp.types import InputRequiredResult
from msgraph.generated.models.drive_item import DriveItem
from msgraph.generated.models.o_data_errors.o_data_error import ODataError
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

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
    NAME_RULES,
    DriveItemSummary,
    folder_label,
    item_for_a_question,
    summary_after_write,
    unusable_name,
)
from office_365_mcp.shared.handles import drive_folder_handle
from office_365_mcp.shared.notes import write_state_for
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    WRITE_ADDITIVE,
    Confirm,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "sharepoint_create_text_file"

STEP_CREATE_FILE = "create_text_file"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Files.ReadWrite.All",)

CHANGE_SHOWN_BY: tuple[str, ...] = ("sharepoint_browse_folder",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "folder": "sharepoint:///folders/b%21SYNTHETICDRIVE0000/01SYNTHETICFOLDER0000",
    "name": "Synthetic note.txt",
    "content": "Synthetic text.",
}

TEXT_EXTENSIONS: tuple[str, ...] = (
    "txt",
    "md",
    "csv",
    "tsv",
    "json",
    "xml",
    "html",
    "htm",
    "yaml",
    "yml",
    "log",
)

MAX_CONTENT_CHARACTERS = 1_000_000

_NEW_FILE_TEMPLATE = "{+baseurl}/drives/{drive%2Did}/items/{driveItem%2Did}:/{fileName}:/content"

_CREATE = "create"
_DO_NOT_CREATE = "do not create"
_NOTHING_CREATED = "No file was created."

_EVERY_TEXT_EXTENSION = ", ".join(f"`.{extension}`" for extension in TEXT_EXTENSIONS)

_DESCRIPTION = """\
This tool creates one new text file in a OneDrive or SharePoint folder that the signed-in user \
can write to. It cannot replace a file or upload a binary file. sharepoint_browse_folder finds the \
folder, and sharepoint_read_file reads the new file back. OneDrive and SharePoint can show the \
change to everyone who can open the folder.

Notes:
- This tool asks the user to agree before it creates anything, every time.
- If a file named `name` is already there, Microsoft refuses and creates nothing.
- If a call times out, do not call this tool again first. Before you call again, make sure that \
sharepoint_browse_folder does not show a file named `name`.
"""

_NOT_A_FOLDER_HANDLE = (
    "No file was created. sharepoint_create_text_file takes a folder handle in `folder`. It looks "
    + "like sharepoint:///folders/{drive_id}/{item_id}. "
    + FOLDER_HANDLE_SOURCES
    + " A file handle, a folder name, a path and a web address are not folder handles. This same "
    + "value fails again, so do not retry it."
)

_NOT_TEXT = (
    "No file was created. sharepoint_create_text_file writes text only. The name must end with "
    + f"one of these extensions: {_EVERY_TEXT_EXTENSION}. This tool cannot create a Word, Excel, "
    + "PowerPoint or PDF file, or any other binary file. If the user wants such a file, tell them "
    + "that this connector cannot create it. This same value fails again, so do not retry it."
)

_NOT_A_FOLDER = (
    "No file was created, because the item in `folder` is not a folder. This tool creates a file "
    + "only inside a folder. Use the `uri` of a row that sharepoint_browse_folder shows with "
    + "`is_folder` true. This same value fails again, so do not retry it."
)

_WRITTEN_BUT_UNREAD = (
    "Microsoft 365 created the file. Then this connector did not receive the new file from "
    + "Microsoft 365. Do not call this tool again for this file. Use sharepoint_browse_folder on "
    + "the same `folder` to find the new file and its `uri`."
)

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not find this folder, and this call created nothing. The handle is well "
    + "formed, so the folder was most likely deleted. It can also have moved to another drive, "
    + "which gives it a new handle. Find the folder again with sharepoint_search_files or "
    + "sharepoint_browse_folder, and take the `uri` from that result. This same handle fails the "
    + "same way, so do not retry it."
)


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(
        ctx, agree=_CREATE, decline=_DO_NOT_CREATE, nothing_happened=_NOTHING_CREATED
    )


async def create_text_file(
    client: GraphServiceClient,
    *,
    folder: str,
    name: str,
    content: str,
    confirm: Confirm,
) -> DriveItemSummary | InputRequiredResult:
    assert len(name) >= 1, f"name is bounded by the schema, got {len(name)}"
    assert 1 <= len(content) <= MAX_CONTENT_CHARACTERS, (
        f"content is bounded by the schema, got {len(content)} characters"
    )
    handle = drive_folder_handle(folder)
    if handle is None:
        raise ToolError(_NOT_A_FOLDER_HANDLE)
    refused_name = unusable_name(name) or _not_text(name)
    if refused_name is not None:
        raise ToolError(refused_name)

    about = write_state_for(
        TOOL_NAME,
        handle.drive_id,
        handle.item_id,
        name,
        hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )
    created: DriveItemSummary | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors(TOOL_NAME):
        found = await item_for_a_question(client, handle.drive_id, handle.item_id)
        assert found.id is not None, "Graph answered a drive item read with no id"
        if found.folder is None:
            refused = _NOT_A_FOLDER
        else:
            with not_graph():
                answer = await confirm(_question(name, content, found), about)
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            request = _put_request(client, handle.drive_id, found.id, name=name, content=content)
            with graph_step(STEP_CREATE_FILE):
                written = await client.request_adapter.send_async(  # pyright: ignore[reportUnknownMemberType]
                    request, DriveItem, {"XXX": ODataError}
                )
            created = await summary_after_write(
                client,
                handle.drive_id,
                written,
                item_id=None if written is None else written.id,
                unread=_WRITTEN_BUT_UNREAD,
            )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert created is not None, "a create neither asked about nor refused created nothing"
    return created


def _not_text(name: str) -> str | None:
    _stem, dot, extension = name.rpartition(".")
    return None if dot and extension.casefold() in TEXT_EXTENSIONS else _NOT_TEXT


def _put_request(
    client: GraphServiceClient, drive_id: str, parent_id: str, *, name: str, content: str
) -> RequestInformation:
    parent = client.drives.by_drive_id(drive_id).items.by_drive_item_id(parent_id)
    request = request_with_query(
        Method.PUT,
        _NEW_FILE_TEMPLATE,
        {**parent.path_parameters, "fileName": name},
        query=FAIL_ON_CONFLICT,
    )
    request.headers.try_add("Accept", "application/json")
    request.set_stream_content(content.encode("utf-8"), "text/plain; charset=utf-8")
    request.add_request_options(no_retry())
    return request


def _question(name: str, content: str, folder: DriveItem) -> str:
    return (
        f"Create the text file {name!r} ({len(content)} characters) in {folder_label(folder)}? "
        + f"It starts: {cut_for_a_question(content)!r}"
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Create a Text File",
        description=_DESCRIPTION,
        annotations=WRITE_ADDITIVE,
    )
    async def sharepoint_create_text_file(
        folder: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The folder that gets the new file. "
                    + FOLDER_HANDLE_SOURCES
                    + " A file handle, a path and a web address are not folder handles."
                ),
            ),
        ],
        name: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The name of the new file, with its extension. The extension must be one of "
                    + f"{_EVERY_TEXT_EXTENSION}. {NAME_RULES}"
                ),
            ),
        ],
        content: Annotated[
            str,
            Field(
                min_length=1,
                max_length=MAX_CONTENT_CHARACTERS,
                description=(
                    "The whole text of the new file, as plain text, at most "
                    + f"{MAX_CONTENT_CHARACTERS:,} characters. This tool stores the text as "
                    + "UTF-8, exactly as you give it. Do not give base64 or the content of a "
                    + "binary file, for example a Word or PDF file."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> DriveItemSummary | InputRequiredResult:
        return await create_text_file(
            client, folder=folder, name=name, content=content, confirm=a_person_agrees(ctx)
        )
