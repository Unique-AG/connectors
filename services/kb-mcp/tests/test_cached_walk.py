"""One unfiltered walk per scope; the filter is applied to its snapshot."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from unique_toolkit.content.schemas import ContentInfo
from unique_toolkit.experimental.components.content_tree import FolderWalkSnapshot

from kb_mcp.common.cached_walk import filter_snapshot, resolve_filtered_snapshot

_PDF_ONLY = {"operator": "equals", "path": ["mimeType"], "value": "application/pdf"}


def _content(content_id: str, mime_type: str) -> ContentInfo:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return ContentInfo(
        id=content_id,
        object="content",
        key=f"{content_id}.file",
        byteSize=1,
        mimeType=mime_type,
        ownerId="scope_a",
        createdAt=now,
        updatedAt=now,
    )


def _snapshot() -> FolderWalkSnapshot:
    return FolderWalkSnapshot(
        files=[
            (_content("c_pdf", "application/pdf"), PurePosixPath("Docs/a.pdf")),
            (_content("c_txt", "text/plain"), PurePosixPath("Docs/b.txt")),
        ],
        folder_paths=[PurePosixPath("Empty")],
        complete=True,
    )


def test_filter_drops_non_matching_files_and_keeps_every_folder():
    filtered = filter_snapshot(_snapshot(), _PDF_ONLY)

    assert [info.id for info, _ in filtered.files] == ["c_pdf"]
    assert filtered.folder_paths == [PurePosixPath("Empty")]
    assert filtered.complete is True


def test_no_filter_returns_the_snapshot_untouched():
    snapshot = _snapshot()

    assert filter_snapshot(snapshot, None) is snapshot


@pytest.mark.asyncio
async def test_distinct_post_filters_share_one_walk():
    """The whole point: a varying filter never reaches the walk's cache key."""
    tree = MagicMock()
    tree.metadata_filter = None
    tree.resolve_visible_file_paths_via_folders_async = AsyncMock(
        return_value=_snapshot()
    )
    admin = {"operator": "equals", "path": ["ownerId"], "value": "scope_a"}

    async def _resolve(post_filter: dict[str, Any] | None) -> list[str]:
        snapshot = await resolve_filtered_snapshot(
            tree,
            walk_filter=admin,
            post_filter=post_filter,
            max_depth=None,
            timeout=None,
            max_concurrent_directory_listings=25,
        )
        return [info.id for info, _ in snapshot.files]

    assert await _resolve(_PDF_ONLY) == ["c_pdf"]
    assert await _resolve(
        {"operator": "equals", "path": ["mimeType"], "value": "text/plain"}
    ) == ["c_txt"]

    keys = {
        call.kwargs["metadata_filter"]["value"]
        for call in tree.resolve_visible_file_paths_via_folders_async.call_args_list
    }
    assert keys == {"scope_a"}, "a post filter leaked into the walk's cache key"
