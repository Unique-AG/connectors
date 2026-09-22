"""One unfiltered folder walk per scope, filtered in memory per request."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import PurePosixPath
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
    """Drop files not matching ``metadata_filter``. Folders are never filtered.

    With no filter this is the cached snapshot itself, so callers must not
    mutate what they get back.
    """
    if not metadata_filter:
        return snapshot
    keep = uniqueql_predicate(metadata_filter)
    return FolderWalkSnapshot(
        files=[(info, path) for info, path in snapshot.files if keep(info)],
        folder_paths=snapshot.folder_paths,
        complete=snapshot.complete,
    )


def _depth_order_key(path: PurePosixPath) -> tuple[int, str]:
    """Shallowest first, then lexicographic, so any caller that slices this
    list gets a stable, breadth-biased prefix instead of whichever branch's
    concurrent directory listings happened to return first."""
    return (len(path.parts), str(path))


def sorted_by_depth(snapshot: FolderWalkSnapshot) -> FolderWalkSnapshot:
    """A new snapshot with files and folders in deterministic, shallowest-first
    order. Never mutates ``snapshot``: it may be the live, shared cache entry
    a background walk is still appending to."""
    return FolderWalkSnapshot(
        files=sorted(snapshot.files, key=lambda row: _depth_order_key(row[1])),
        folder_paths=sorted(snapshot.folder_paths, key=_depth_order_key),
        complete=snapshot.complete,
    )


async def resolve_filtered_snapshot(
    tree_svc: ContentTree,
    *,
    walk_filter: dict[str, Any] | None,
    post_filter: dict[str, Any] | None,
    max_depth: int | None,
    timeout: float | None,
    max_concurrent_directory_listings: int,
) -> FolderWalkSnapshot:
    """Split the filter by who varies it, since the walk cache is keyed by it:
    a constant ``walk_filter`` is cached, a varying ``post_filter`` would not be."""
    assert tree_svc.metadata_filter is None, (
        "tree must be unfiltered, or its filter is applied twice"
    )
    snapshot = await tree_svc.resolve_visible_file_paths_via_folders_async(
        metadata_filter=walk_filter,
        max_depth=max_depth,
        timeout=timeout,
        max_concurrent_directory_listings=max_concurrent_directory_listings,
    )
    return sorted_by_depth(filter_snapshot(snapshot, post_filter))
