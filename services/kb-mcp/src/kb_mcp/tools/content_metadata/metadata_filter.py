"""Folder-scoped metadata filter for the content-metadata tool."""

from __future__ import annotations

from typing import Any

from kb_mcp.tools.search.metadata_filter import (
    RawOrParsedUniqueQL,
    merge_request_metadata_filter,
)


def build_folder_scoped_metadata_filter(
    folder_ids: list[str] | None,
    *,
    include_subfolders: bool = True,
    admin_metadata_filter: RawOrParsedUniqueQL = None,
) -> dict[str, Any] | None:
    """Admin filter ANDed with an optional folder-scope clause.

    Same `scope_xxx` ids and admin-filter-never-bypassed semantics as
    `search`'s `folder_ids`, for callers (e.g. content_metadata) that only
    need folder scoping, not the full LLM-filter-merging surface of
    ``merge_request_metadata_filter``.
    """
    return merge_request_metadata_filter(
        admin_metadata_filter=admin_metadata_filter,
        folder_ids=folder_ids,
        include_subfolders=include_subfolders,
    )
