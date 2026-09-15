"""Tests for scoped_walk — the root-scoped folder walk and ScopedContentTree.

Unlike unique_toolkit's own walk (always starts at the KB root, then filters
files after the fact), this walk must never visit anything outside the given
root_scope_ids' subtrees.
"""

import asyncio
from pathlib import PurePosixPath
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from unique_toolkit.experimental.components.content_tree.schemas import (
    FolderWalkSnapshot,
)

from kb_mcp.tools.content_metadata.scoped_walk import ScopedContentTree, walk_visible_paths_via_folders_async

pytestmark = pytest.mark.ai


def _folder(id_: str, name: str, parent_id: str | None = None) -> dict[str, Any]:
    return {"id": id_, "name": name, "parentId": parent_id}


def _content(id_: str, key: str, metadata: dict | None = None) -> dict[str, Any]:
    return {
        "id": id_,
        "object": "content",
        "key": key,
        "byteSize": 1,
        "mimeType": "application/pdf",
        "ownerId": "owner",
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": "2024-01-01T00:00:00Z",
        "metadata": metadata,
    }


def _folders_page(*folders: dict[str, Any], total: int | None = None) -> dict[str, Any]:
    return {
        "folderInfos": list(folders),
        "totalCount": total if total is not None else len(folders),
    }


def _content_page(*items: dict[str, Any], total: int | None = None) -> dict[str, Any]:
    return {
        "contentInfos": list(items),
        "totalCount": total if total is not None else len(items),
    }


def _patch_sdk(folder_infos, content_infos):
    # scoped_walk delegates the actual SDK calls to unique_toolkit's own
    # _list_direct_children_async, so that's where they're made from.
    return (
        patch(
            "unique_toolkit.experimental.components.content_tree.functions"
            ".unique_sdk.Folder.get_infos_async",
            side_effect=folder_infos,
        ),
        patch(
            "unique_toolkit.experimental.components.content_tree.functions"
            ".unique_sdk.Content.get_infos_async",
            side_effect=content_infos,
        ),
    )


@pytest.mark.asyncio
async def test_walk_starts_at_root_scope_ids_and_never_visits_none():
    """The one property that fixes the underlying bug: no listing call is
    ever made with parentId=None (the knowledge-base root)."""
    folder_calls: list[str | None] = []

    async def _folder_infos(*, user_id, company_id, parentId, skip, take):
        folder_calls.append(parentId)
        if parentId == "scope_root":
            return _folders_page(_folder("scope_child", "Child", "scope_root"))
        return _folders_page()

    async def _content_infos(*, user_id, company_id, parentId, skip, take):
        return _content_page()

    folder_patch, content_patch = _patch_sdk(_folder_infos, _content_infos)
    with folder_patch, content_patch:
        snapshot = await walk_visible_paths_via_folders_async(
            "user-1", "company-1", ["scope_root"]
        )

    assert None not in folder_calls
    assert set(folder_calls) == {"scope_root", "scope_child"}
    assert snapshot.complete is True


@pytest.mark.asyncio
async def test_walk_visits_multiple_independent_roots():
    folder_calls: list[str | None] = []

    async def _folder_infos(*, user_id, company_id, parentId, skip, take):
        folder_calls.append(parentId)
        return _folders_page()

    async def _content_infos(*, user_id, company_id, parentId, skip, take):
        if parentId == "scope_a":
            return _content_page(_content("c1", "a.pdf"))
        if parentId == "scope_b":
            return _content_page(_content("c2", "b.pdf"))
        return _content_page()

    folder_patch, content_patch = _patch_sdk(_folder_infos, _content_infos)
    with folder_patch, content_patch:
        snapshot = await walk_visible_paths_via_folders_async(
            "user-1", "company-1", ["scope_a", "scope_b"]
        )

    assert set(folder_calls) == {"scope_a", "scope_b"}
    assert {info.key for info, _path in snapshot.files} == {"a.pdf", "b.pdf"}
    assert snapshot.complete is True


@pytest.mark.asyncio
async def test_walk_deduplicates_files_visible_through_overlapping_roots():
    """A file reachable through two given roots (e.g. one root nested inside
    another) must only be counted once."""

    async def _folder_infos(*, user_id, company_id, parentId, skip, take):
        if parentId == "scope_parent":
            return _folders_page(_folder("scope_child", "Child", "scope_parent"))
        return _folders_page()

    async def _content_infos(*, user_id, company_id, parentId, skip, take):
        if parentId == "scope_child":
            return _content_page(_content("c1", "shared.pdf"))
        return _content_page()

    folder_patch, content_patch = _patch_sdk(_folder_infos, _content_infos)
    with folder_patch, content_patch:
        snapshot = await walk_visible_paths_via_folders_async(
            "user-1", "company-1", ["scope_parent", "scope_child"]
        )

    assert len(snapshot.files) == 1
    assert snapshot.files[0][0].key == "shared.pdf"


@pytest.mark.asyncio
async def test_walk_skips_a_root_that_fails_without_losing_other_roots():
    async def _folder_infos(*, user_id, company_id, parentId, skip, take):
        if parentId == "scope_broken":
            raise RuntimeError("backend error")
        return _folders_page()

    async def _content_infos(*, user_id, company_id, parentId, skip, take):
        if parentId == "scope_ok":
            return _content_page(_content("c1", "ok.pdf"))
        return _content_page()

    folder_patch, content_patch = _patch_sdk(_folder_infos, _content_infos)
    with folder_patch, content_patch:
        snapshot = await walk_visible_paths_via_folders_async(
            "user-1", "company-1", ["scope_ok", "scope_broken"]
        )

    assert snapshot.complete is True
    assert {info.key for info, _path in snapshot.files} == {"ok.pdf"}


@pytest.mark.asyncio
async def test_walk_respects_max_depth():
    folder_calls: list[str | None] = []

    async def _folder_infos(*, user_id, company_id, parentId, skip, take):
        folder_calls.append(parentId)
        if parentId == "scope_root":
            return _folders_page(_folder("scope_child", "Child", "scope_root"))
        return _folders_page()

    async def _content_infos(*, user_id, company_id, parentId, skip, take):
        return _content_page()

    folder_patch, content_patch = _patch_sdk(_folder_infos, _content_infos)
    with folder_patch, content_patch:
        snapshot = await walk_visible_paths_via_folders_async(
            "user-1", "company-1", ["scope_root"], max_depth=1
        )

    assert folder_calls == ["scope_root"]
    # Child was listed (and so recorded) but never itself visited.
    assert snapshot.folder_paths == [PurePosixPath("Child")]


@pytest.mark.asyncio
async def test_walk_collects_files_with_paths_relative_to_the_root():
    async def _folder_infos(*, user_id, company_id, parentId, skip, take):
        if parentId == "scope_root":
            return _folders_page(_folder("scope_child", "Child", "scope_root"))
        return _folders_page()

    async def _content_infos(*, user_id, company_id, parentId, skip, take):
        if parentId == "scope_child":
            return _content_page(_content("c1", "a.pdf"))
        return _content_page()

    folder_patch, content_patch = _patch_sdk(_folder_infos, _content_infos)
    with folder_patch, content_patch:
        snapshot = await walk_visible_paths_via_folders_async(
            "user-1", "company-1", ["scope_root"]
        )

    assert snapshot.files == [
        (snapshot.files[0][0], PurePosixPath("Child/a.pdf"))
    ]
    assert snapshot.files[0][0].key == "a.pdf"


@pytest.mark.asyncio
async def test_walk_applies_metadata_filter_client_side():
    async def _folder_infos(*, user_id, company_id, parentId, skip, take):
        return _folders_page()

    async def _content_infos(*, user_id, company_id, parentId, skip, take):
        return _content_page(
            _content("c1", "a.pdf", metadata={"department": "Legal"}),
            _content("c2", "b.pdf", metadata={"department": "Finance"}),
        )

    folder_patch, content_patch = _patch_sdk(_folder_infos, _content_infos)
    with folder_patch, content_patch:
        snapshot = await walk_visible_paths_via_folders_async(
            "user-1",
            "company-1",
            ["scope_root"],
            metadata_filter={
                "operator": "equals",
                "path": ["department"],
                "value": "Legal",
            },
        )

    keys = {info.key for info, _path in snapshot.files}
    assert keys == {"a.pdf"}


@pytest.mark.asyncio
async def test_walk_paginates_beyond_step_size():
    total = 150

    async def _folder_infos(*, user_id, company_id, parentId, skip, take):
        return _folders_page()

    async def _content_infos(*, user_id, company_id, parentId, skip, take):
        page = [
            _content(f"c{i}", f"f{i}.pdf") for i in range(skip, min(skip + take, total))
        ]
        return _content_page(*page, total=total)

    folder_patch, content_patch = _patch_sdk(_folder_infos, _content_infos)
    with folder_patch, content_patch:
        snapshot = await walk_visible_paths_via_folders_async(
            "user-1", "company-1", ["scope_root"]
        )

    assert len(snapshot.files) == total
    assert {info.key for info, _path in snapshot.files} == {
        f"f{i}.pdf" for i in range(total)
    }


@pytest.mark.asyncio
async def test_walk_tolerates_a_failed_subtree():
    """One folder's listing failing must not lose data already collected
    from sibling folders, and must not raise out of the walk."""

    async def _folder_infos(*, user_id, company_id, parentId, skip, take):
        if parentId == "scope_root":
            return _folders_page(
                _folder("scope_ok", "Ok", "scope_root"),
                _folder("scope_broken", "Broken", "scope_root"),
            )
        if parentId == "scope_broken":
            raise RuntimeError("backend error")
        return _folders_page()

    async def _content_infos(*, user_id, company_id, parentId, skip, take):
        if parentId == "scope_ok":
            return _content_page(_content("c1", "ok.pdf"))
        return _content_page()

    folder_patch, content_patch = _patch_sdk(_folder_infos, _content_infos)
    with folder_patch, content_patch:
        snapshot = await walk_visible_paths_via_folders_async(
            "user-1", "company-1", ["scope_root"]
        )

    assert snapshot.complete is True
    assert {info.key for info, _path in snapshot.files} == {"ok.pdf"}


@pytest.mark.asyncio
async def test_walk_timeout_returns_partial_incomplete_snapshot():
    async def _folder_infos(*, user_id, company_id, parentId, skip, take):
        await asyncio.sleep(10)
        return _folders_page()

    async def _content_infos(*, user_id, company_id, parentId, skip, take):
        return _content_page()

    folder_patch, content_patch = _patch_sdk(_folder_infos, _content_infos)
    with folder_patch, content_patch:
        snapshot = await walk_visible_paths_via_folders_async(
            "user-1", "company-1", ["scope_root"], timeout=0.05
        )

    assert snapshot.complete is False


@pytest.mark.asyncio
async def test_scoped_content_tree_walk_is_rooted_at_root_scope_ids():
    tree = ScopedContentTree(
        company_id="company-1", user_id="user-1", root_scope_ids=["scope_root"]
    )
    mock_walk = AsyncMock(
        return_value=FolderWalkSnapshot(files=[], folder_paths=[], complete=True)
    )
    with patch(
        "kb_mcp.tools.content_metadata.scoped_walk.walk_visible_paths_via_folders_async",
        mock_walk,
    ):
        await tree.resolve_visible_file_paths_via_folders_async()

    mock_walk.assert_called_once()
    _, kwargs = mock_walk.call_args
    assert kwargs["root_scope_ids"] == ("scope_root",)
    assert kwargs["user_id"] == "user-1"
    assert kwargs["company_id"] == "company-1"


@pytest.mark.asyncio
async def test_scoped_content_tree_caches_repeated_calls():
    tree = ScopedContentTree(
        company_id="company-1", user_id="user-1", root_scope_ids=["scope_root"]
    )
    mock_walk = AsyncMock(
        return_value=FolderWalkSnapshot(files=[], folder_paths=[], complete=True)
    )
    with patch(
        "kb_mcp.tools.content_metadata.scoped_walk.walk_visible_paths_via_folders_async",
        mock_walk,
    ):
        await tree.resolve_visible_file_paths_via_folders_async()
        await tree.resolve_visible_file_paths_via_folders_async()

    mock_walk.assert_called_once()


@pytest.mark.asyncio
async def test_scoped_content_tree_root_scope_ids_property():
    tree = ScopedContentTree(
        company_id="company-1",
        user_id="user-1",
        root_scope_ids=["scope_a", "scope_b"],
    )
    assert tree.root_scope_ids == ("scope_a", "scope_b")
