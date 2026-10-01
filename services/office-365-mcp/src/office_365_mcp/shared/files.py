import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Self

from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.drives.item.items.item.drive_item_item_request_builder import (
    DriveItemItemRequestBuilder,
)
from msgraph.generated.models.drive_item import DriveItem
from msgraph.generated.models.identity_set import IdentitySet
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import graph_step
from office_365_mcp.shared.handles import DriveFileHandle, DriveFolderHandle, drive_file_handle

STEP_DRIVE_ITEM = "drive_item"

ATTACHMENT_FIELDS: tuple[str, ...] = (
    "id",
    "name",
    "eTag",
    "webDavUrl",
    "file",
    "folder",
    "parentReference",
)

ITEM_FIELDS: tuple[str, ...] = (
    "id",
    "name",
    "size",
    "webUrl",
    "createdDateTime",
    "lastModifiedDateTime",
    "lastModifiedBy",
    "file",
    "folder",
    "parentReference",
)


class DriveItemSummary(BaseModel):
    """One file or folder: what it is, where it lives, and the handle that reaches it again."""

    uri: str = Field(
        description=(
            "This item's handle. A file is sharepoint:///files/{drive}/{item} and a folder is "
            + "sharepoint:///folders/{drive}/{item}. Pass a file handle to sharepoint_read_file "
            + "and a folder handle to sharepoint_browse_folder. Microsoft keeps a drive item's id "
            + "through a rename and through a move inside the same drive, so a handle stays good. "
            + "Take it verbatim and never build one: the drive id is part of it, and an item id "
            + "alone reaches nothing."
        )
    )
    name: str | None = Field(
        description=(
            "The file or folder name, with its extension. Null when Graph recorded none. Names "
            + "repeat across folders and across sites, so the name alone does not say which item "
            + "this is. The `uri` does."
        )
    )
    is_folder: bool = Field(
        description=(
            "This field is true for a folder and false for a file. Graph uses one type for both, "
            + "and only the facet in its answer shows which one an item is. So this field is the "
            + "only reliable test. A folder has no content to read. Browse it instead."
        )
    )
    size: int | None = Field(
        description=(
            "Size in bytes, as Graph reports it. For a folder this is the total of everything "
            + "under it. Read it before asking for a file's content, because a large file is "
            + "refused rather than returned."
        )
    )
    web_url: str | None = Field(
        description=(
            "The address that opens this item in a browser, for a person to follow. It is not a "
            + "download link and this connector cannot read a file from it. Give it to the user "
            + "when they ask where a file is."
        )
    )
    created_at: datetime | None = Field(
        description=(
            "When the item was created, as Graph reported it. Null when Graph recorded none."
        )
    )
    last_modified_at: datetime | None = Field(
        description=(
            "When the item last changed, as Graph reported it. This is the field the date "
            + "arguments of sharepoint_search_files bound."
        )
    )
    last_modified_by: str | None = Field(
        description=(
            "The display name of whoever last changed the item. Null when the change was made by "
            + "an application rather than a person, or when Graph recorded no name."
        )
    )
    mime_type: str | None = Field(
        description=(
            "The content type Graph holds for a file, for example "
            + "`application/vnd.openxmlformats-officedocument.wordprocessingml.document`. Always "
            + "null for a folder."
        )
    )
    child_count: int | None = Field(
        description=(
            "How many items sit directly inside a folder. Always null for a file. Zero means the "
            + "folder is empty."
        )
    )
    parent_path: str | None = Field(
        description=(
            "Where the item sits inside its drive, as Graph's own percent-encoded path, for "
            + "example `/drive/root:/Reports/2026`. Read it to tell two files of the same name "
            + "apart. It is a description of a location and not a handle: browsing needs the "
            + "parent folder's own `uri`. Always null on a search result, because Microsoft's "
            + "search index does not carry the path. Browse a folder to get it."
        )
    )
    drive_type: str | None = Field(
        description=(
            "Which kind of drive holds this item, as Graph names it: `personal` or `business` for "
            + "a OneDrive, and `documentLibrary` for a SharePoint document library. This is how to "
            + "tell a file in the user's own OneDrive from one on a SharePoint site. Always null "
            + "on a search result, because Microsoft's search index does not carry it. Browse a "
            + "folder to get it."
        )
    )

    parent_uri: str | None = Field(
        description=(
            "This is the handle of the folder that holds this item. Pass it to "
            + "sharepoint_browse_folder to see everything else in the same folder. This field is "
            + "null only when Graph reported no parent. That happens for the root of a drive."
        )
    )

    @classmethod
    def from_item(cls, item: DriveItem) -> Self | None:
        parent = item.parent_reference
        drive_id = parent.drive_id if parent is not None else None
        if item.id is None or drive_id is None:
            return None
        is_folder = item.folder is not None
        handle = (
            DriveFolderHandle(drive_id, item.id)
            if is_folder
            else DriveFileHandle(drive_id, item.id)
        )
        parent_id = parent.id if parent is not None else None
        return cls(
            uri=handle.uri,
            parent_uri=None if parent_id is None else DriveFolderHandle(drive_id, parent_id).uri,
            name=item.name,
            is_folder=is_folder,
            size=item.size,
            web_url=item.web_url,
            created_at=item.created_date_time,
            last_modified_at=item.last_modified_date_time,
            last_modified_by=_display_name(item.last_modified_by),
            mime_type=item.file.mime_type if item.file is not None else None,
            child_count=item.folder.child_count if item.folder is not None else None,
            parent_path=parent.path if parent is not None else None,
            drive_type=parent.drive_type if parent is not None else None,
        )


def _display_name(identity: IdentitySet | None) -> str | None:
    if identity is None or identity.user is None:
        return None
    return identity.user.display_name


@dataclass(frozen=True, slots=True)
class AttachableFile:
    attachment_id: str
    web_dav_url: str
    name: str


_ETAG_GUID = re.compile(
    r"\{([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\}"
)

_PERSONAL_DRIVE = "personal"

_AttachmentQuery = DriveItemItemRequestBuilder.DriveItemItemRequestBuilderGetQueryParameters

_SAME_FAILURE = (
    "If you call this tool again with the same arguments, the call will fail the same way."
)

_A_FILE_HANDLE = (
    "A file handle looks like sharepoint:///files/{drive_id}/{item_id}, with both ids "
    + "percent-encoded. A folder handle, a web address and a file name are not file handles. "
    + "Copy the `uri` of a sharepoint_search_files hit or of a sharepoint_browse_folder row, word "
    + "for word. "
    + _SAME_FAILURE
)


def attachment_handles(uris: Sequence[str]) -> tuple[DriveFileHandle, ...] | str:
    handles: list[DriveFileHandle] = []
    for uri in uris:
        handle = drive_file_handle(uri)
        if handle is None:
            return f"The attachment {uri!r} is not a file handle. {_A_FILE_HANDLE}"
        handles.append(handle)
    return tuple(handles)


async def attachable_files(
    client: GraphServiceClient, handles: Sequence[DriveFileHandle]
) -> tuple[AttachableFile, ...] | str:
    files: list[AttachableFile] = []
    for handle in handles:
        with graph_step(STEP_DRIVE_ITEM):
            item = await (
                client.drives.by_drive_id(handle.drive_id)
                .items.by_drive_item_id(handle.item_id)
                .get(
                    request_configuration=RequestConfiguration[_AttachmentQuery](
                        query_parameters=_AttachmentQuery(select=list(ATTACHMENT_FIELDS))
                    )
                )
            )
        assert item is not None, "Graph answered a drive item read with no item"
        attachable = _attachable(item, handle)
        if isinstance(attachable, str):
            return attachable
        files.append(attachable)
    return tuple(files)


def _attachable(item: DriveItem, handle: DriveFileHandle) -> AttachableFile | str:
    if item.folder is not None:
        return (
            f"The attachment {handle.uri} names a folder, and this tool attaches files only. "
            + "To find a file in this folder, give this handle to sharepoint_browse_folder: "
            + DriveFolderHandle(handle.drive_id, handle.item_id).uri
            + ". Then attach the `uri` of one file. "
            + _SAME_FAILURE
        )
    if item.file is None:
        return (
            f"The attachment {handle.uri} is not a plain file in Microsoft 365. A OneNote "
            + "notebook is an example of such an item. This tool attaches files only. "
            + _SAME_FAILURE
        )
    parent = item.parent_reference
    if parent is not None and parent.drive_type == _PERSONAL_DRIVE:
        return (
            f"The attachment {handle.uri} is in a personal OneDrive. Microsoft Teams can attach "
            + "a file only when the file is already in SharePoint. A personal OneDrive is not in "
            + f"SharePoint. {_SAME_FAILURE}"
        )
    guid = None if item.e_tag is None else _ETAG_GUID.search(item.e_tag)
    if guid is None or item.web_dav_url is None or item.name is None:
        return (
            f"Microsoft 365 did not send all the details of the attachment {handle.uri}. This "
            + "tool needs the name, the eTag and the WebDAV address of a file to attach it. This "
            + "is a gap in what Microsoft reported, and not a bad argument. Tell the user to "
            + f"attach the file in Microsoft Teams instead. {_SAME_FAILURE}"
        )
    return AttachableFile(
        attachment_id=guid.group(1).lower(), web_dav_url=item.web_dav_url, name=item.name
    )
