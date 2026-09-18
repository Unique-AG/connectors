from datetime import datetime
from typing import Self

from msgraph.generated.models.drive_item import DriveItem
from msgraph.generated.models.identity_set import IdentitySet
from pydantic import BaseModel, Field

from office_365_mcp.shared.handles import DriveFileHandle, DriveFolderHandle

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
            "True for a folder, false for a file. Graph uses one type for both and tells them "
            + "apart by which facet it returns, so this is the only reliable test. A folder has "
            + "no content to read; browse it instead. A search never returns a folder, so every "
            + "search result has this false; a folder listing returns both."
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
            "The handle of the folder that holds this item. Pass it to sharepoint_browse_folder to "
            + "see everything else in the same folder. This is the way to reach a SharePoint "
            + "folder: a search finds files, and this field turns a file into the folder around "
            + "it. Null only when Graph reported no parent, which happens for the root of a drive."
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
