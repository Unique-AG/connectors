"""Build the per-call ``metadata_filter_override`` for folder-scoped search."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from unique_toolkit._common.metadata_filter_scope import (
    build_folder_id_in_clause,
    merge_scope_clause_into_metadata_filter,
)
from unique_toolkit.content.smart_rules import (
    Operator,
    OrStatement,
    Statement,
    UniqueQL,
    uniqueql_to_dict,
)


def _folder_ids_clause(
    folder_ids: list[str], *, include_subfolders: bool
) -> dict[str, Any]:
    assert folder_ids, "folder_ids must be a non-empty list"
    if include_subfolders:
        return OrStatement(
            or_list=[
                Statement(operator=Operator.CONTAINS, path=["folderIdPath"], value=fid)
                for fid in folder_ids
            ]
        ).to_dict()
    return build_folder_id_in_clause(folder_ids)


def merge_request_metadata_filter(
    *,
    admin_metadata_filter: UniqueQL | Mapping[str, Any] | None,
    folder_ids: list[str] | None = None,
    include_subfolders: bool = True,
    llm_metadata_filter: UniqueQL | Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    result: UniqueQL | Mapping[str, Any] | None = admin_metadata_filter
    if llm_metadata_filter is not None:
        llm_dict = uniqueql_to_dict(llm_metadata_filter)
        assert llm_dict is not None
        result = merge_scope_clause_into_metadata_filter(llm_dict, result)
    if folder_ids:
        result = merge_scope_clause_into_metadata_filter(
            _folder_ids_clause(folder_ids, include_subfolders=include_subfolders),
            result,
        )
    return uniqueql_to_dict(result)


def build_folder_scoped_metadata_filter(
    folder_ids: list[str],
    *,
    include_subfolders: bool,
    admin_metadata_filter: UniqueQL | dict[str, Any] | None,
) -> dict[str, Any]:
    """AND a folder-scope clause onto the admin's ``metadata_filter``, never
    bypassing it — the result is never ``None`` when the admin filter isn't."""
    merged = merge_request_metadata_filter(
        admin_metadata_filter=admin_metadata_filter,
        folder_ids=folder_ids,
        include_subfolders=include_subfolders,
    )
    assert merged is not None
    return merged
