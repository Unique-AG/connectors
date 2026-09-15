"""Folder walk rooted at one or more folders, instead of the knowledge-base
root.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Any, override

from unique_toolkit.content.schemas import BaseFolderInfo, ContentInfo
from unique_toolkit.experimental.components.content_tree import ContentTree

# Reused rather than reimplemented: the per-folder listing primitive
# unique_toolkit's own walk calls for every folder it visits (root or not) —
# pagination, the client-side UniqueQL filter, and partial-failure handling
# all live here. Underscore-prefixed (module-private) and not nested, so it's
# importable, but pin the exact unique_toolkit version this matches; a bump
# that renames/removes it needs a look.
from unique_toolkit.experimental.components.content_tree.functions import (
    _list_direct_children_async,  # pyright: ignore[reportPrivateUsage]
)
from unique_toolkit.experimental.components.content_tree.schemas import (
    FolderWalkSnapshot,
)

_LOGGER = logging.getLogger(__name__)

# Same defaults unique_toolkit's own walk uses.
_STEP_SIZE = 100
_MAX_CONCURRENT_PAGE_FETCHES = 10


def _log_walk_failure(task: asyncio.Task[FolderWalkSnapshot]) -> None:
    """Retrieve an evicted walk's exception so asyncio does not report it."""
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        _LOGGER.debug("Scoped folder walk failed", exc_info=error)


async def walk_visible_paths_via_folders_async(
    user_id: str,
    company_id: str,
    root_scope_ids: Sequence[str],
    *,
    metadata_filter: dict[str, Any] | None = None,
    max_depth: int | None = None,
    max_concurrent_directory_listings: int = 25,
    timeout: float | None = None,
    progress: FolderWalkSnapshot | None = None,
) -> FolderWalkSnapshot:
    """Same shape and semantics as unique_toolkit's
    ``walk_visible_paths_via_folders_async``, except the walk starts at
    ``root_scope_ids`` instead of the knowledge-base root — so only those
    folders' subtrees are ever visited, never the whole company tree.

    Every root is walked concurrently; a root that fails to list is skipped
    (logged) rather than failing the whole call, the same tolerance already
    given to any other folder encountered mid-walk.
    """
    assert root_scope_ids, "root_scope_ids must be a non-empty sequence"
    acc = progress or FolderWalkSnapshot(files=[], folder_paths=[], complete=False)
    dir_semaphore = asyncio.Semaphore(max_concurrent_directory_listings)
    seen_content_ids = {info.id for info, _path in acc.files}
    seen_folder_paths = set(acc.folder_paths)

    async def _visit(scope_id: str, path: PurePosixPath, depth: int) -> None:
        def _on_folders(page: list[BaseFolderInfo]) -> None:
            for folder in page:
                folder_path = path / folder.name
                if folder_path in seen_folder_paths:
                    continue
                seen_folder_paths.add(folder_path)
                acc.folder_paths.append(folder_path)

        def _on_files(page: list[ContentInfo]) -> None:
            for info in page:
                if info.id in seen_content_ids:
                    continue
                seen_content_ids.add(info.id)
                acc.files.append((info, path / info.key))

        async with dir_semaphore:
            folders = await asyncio.shield(
                _list_direct_children_async(
                    user_id,
                    company_id,
                    scope_id=scope_id,
                    metadata_filter=metadata_filter,
                    step_size=_STEP_SIZE,
                    max_concurrent_page_fetches=_MAX_CONCURRENT_PAGE_FETCHES,
                    on_folders=_on_folders,
                    on_files=_on_files,
                )
            )
        recurse = max_depth is None or depth + 1 < max_depth
        if recurse and folders:
            results = await asyncio.gather(
                *(
                    _visit(folder.id, path / folder.name, depth + 1)
                    for folder in folders
                ),
                return_exceptions=True,
            )
            for folder, result in zip(folders, results, strict=True):
                if isinstance(result, BaseException):
                    _LOGGER.debug("Skipping subtree %s", folder.id, exc_info=result)

    async def _visit_roots() -> None:
        results = await asyncio.gather(
            *(_visit(root_id, PurePosixPath(), 0) for root_id in root_scope_ids),
            return_exceptions=True,
        )
        for root_id, result in zip(root_scope_ids, results, strict=True):
            if isinstance(result, BaseException):
                _LOGGER.debug("Skipping root %s", root_id, exc_info=result)

    try:
        if timeout is None:
            await _visit_roots()
        else:
            async with asyncio.timeout(timeout):
                await _visit_roots()
    except TimeoutError:
        acc.complete = False
        return acc.copy(complete=False)

    acc.complete = True
    return acc.copy(complete=True)


class ScopedContentTree(ContentTree):
    """``ContentTree`` whose folder walk is rooted at ``root_scope_ids``
    instead of the knowledge-base root — see module docstring."""

    def __init__(
        self,
        company_id: str,
        user_id: str,
        root_scope_ids: Sequence[str],
        metadata_filter: dict[str, Any] | None = None,
    ) -> None:
        self._root_scope_ids = tuple(root_scope_ids)
        assert self._root_scope_ids, "root_scope_ids must be non-empty"
        super().__init__(
            company_id=company_id, user_id=user_id, metadata_filter=metadata_filter
        )

    @property
    def root_scope_ids(self) -> tuple[str, ...]:
        return self._root_scope_ids

    @override
    def _create_folder_walk_task(
        self,
        filter_key: str,
        max_depth_key: int,
        max_concurrent_directory_listings: int,
    ) -> tuple[asyncio.Task[FolderWalkSnapshot], FolderWalkSnapshot]:
        effective_filter: dict[str, Any] | None = (
            None if filter_key == "null" else json.loads(filter_key)
        )
        max_depth = None if max_depth_key < 0 else max_depth_key
        progress = FolderWalkSnapshot(files=[], folder_paths=[], complete=False)
        task = asyncio.ensure_future(
            walk_visible_paths_via_folders_async(
                user_id=self.user_id,
                company_id=self.company_id,
                root_scope_ids=self._root_scope_ids,
                metadata_filter=effective_filter,
                max_depth=max_depth,
                max_concurrent_directory_listings=max_concurrent_directory_listings,
                progress=progress,
            )
        )
        task.add_done_callback(_log_walk_failure)
        return task, progress
