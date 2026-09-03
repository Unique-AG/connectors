"""Build the per-call ``metadata_filter_override`` for folder-scoped search."""

from __future__ import annotations

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
)


def build_folder_scoped_metadata_filter(
    folder_ids: list[str],
    *,
    include_subfolders: bool,
    admin_metadata_filter: UniqueQL | dict[str, Any] | None,
) -> dict[str, Any]:
    """AND a folder-scope clause onto the admin's ``metadata_filter``, never
    bypassing it — the result is never ``None`` when the admin filter isn't."""
    if include_subfolders:
        scope_clause = OrStatement(
            or_list=[
                Statement(operator=Operator.CONTAINS, path=["folderIdPath"], value=fid)
                for fid in folder_ids
            ]
        ).to_dict()
    else:
        scope_clause = build_folder_id_in_clause(folder_ids)

    return merge_scope_clause_into_metadata_filter(scope_clause, admin_metadata_filter)
