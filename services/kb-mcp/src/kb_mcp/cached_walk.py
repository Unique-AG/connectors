"""One unfiltered folder walk per scope, filtered in memory per request."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from unique_toolkit.content.schemas import ContentInfo
from unique_toolkit.content.smart_rules import parse_uniqueql
from unique_toolkit.experimental.components.content_tree import (
    ContentTree,
    FolderWalkSnapshot,
)

# The same UniqueQL evaluation the walk itself applies to each page — reused so
# a snapshot filtered here is byte-identical to one filtered during the walk.
from unique_toolkit.experimental.components.content_tree.functions import (
    _content_uniqueql_record,  # pyright: ignore[reportPrivateUsage]
    _uniqueql_fill_nullish_values,  # pyright: ignore[reportPrivateUsage]
    _uniqueql_matches,  # pyright: ignore[reportPrivateUsage]
)


def uniqueql_predicate(
    metadata_filter: dict[str, Any] | None,
) -> Callable[[ContentInfo], bool]:
    """Whether one file passes ``metadata_filter``. No filter keeps everything."""
    if not metadata_filter:
        return lambda _info: True
    query = parse_uniqueql(_uniqueql_fill_nullish_values(metadata_filter))
    return lambda info: _uniqueql_matches(_content_uniqueql_record(info), query)


def filter_snapshot(
    snapshot: FolderWalkSnapshot, metadata_filter: dict[str, Any] | None
) -> FolderWalkSnapshot:
    """Drop files not matching ``metadata_filter``. Folders are never filtered."""
    if not metadata_filter:
        return snapshot
    keep = uniqueql_predicate(metadata_filter)
    return FolderWalkSnapshot(
        files=[(info, path) for info, path in snapshot.files if keep(info)],
        folder_paths=snapshot.folder_paths,
        complete=snapshot.complete,
    )


async def resolve_filtered_snapshot(
    tree_svc: ContentTree,
    *,
    metadata_filter: dict[str, Any] | None,
    max_depth: int | None,
    timeout: float | None,
    max_concurrent_directory_listings: int,
) -> FolderWalkSnapshot:
    """Walk unfiltered, then apply ``metadata_filter`` to the cached snapshot.

    The backend rejects ``parentId`` with ``metadataFilter``, so the walk costs
    the same requests either way; keying its cache by filter just buys re-walks.
    """
    assert tree_svc.metadata_filter is None, (
        "tree must be unfiltered, or its filter is applied twice"
    )
    snapshot = await tree_svc.resolve_visible_file_paths_via_folders_async(
        max_depth=max_depth,
        timeout=timeout,
        max_concurrent_directory_listings=max_concurrent_directory_listings,
    )
    return filter_snapshot(snapshot, metadata_filter)
