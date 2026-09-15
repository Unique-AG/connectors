"""AND admin UniqueQL, optional folder scope, and optional LLM UniqueQL."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastmcp.tools import ToolResult
from mcp.types import TextContent
from pydantic import ValidationError
from unique_toolkit._common.metadata_filter_scope import (
    build_folder_id_in_clause,
    merge_scope_clause_into_metadata_filter,
)
from unique_toolkit.content.smart_rules import (
    Operator,
    OrStatement,
    Statement,
    UniqueQL,
    parse_uniqueql,
    uniqueql_to_dict,
)

from kb_mcp.references import INVALID_METADATA_FILTER_MESSAGE

type RawOrParsedUniqueQL = UniqueQL | Mapping[str, Any] | None


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


def try_parse_llm_metadata_filter(
    raw: Mapping[str, Any] | None,
) -> tuple[UniqueQL | None, ToolResult | None]:
    if raw is None:
        return None, None
    try:
        return parse_uniqueql(dict(raw)), None
    except ValueError, ValidationError:
        return None, ToolResult(
            content=[TextContent(type="text", text=INVALID_METADATA_FILTER_MESSAGE)],
            is_error=True,
        )


def merge_request_metadata_filter(
    *,
    admin_metadata_filter: RawOrParsedUniqueQL,
    folder_ids: list[str] | None = None,
    include_subfolders: bool = True,
    llm_metadata_filter: RawOrParsedUniqueQL = None,
    admin_scope_ids: list[str] | None = None,
) -> dict[str, Any] | None:
    result: RawOrParsedUniqueQL = admin_metadata_filter
    if llm_metadata_filter is not None:
        llm_dict = uniqueql_to_dict(llm_metadata_filter)
        assert llm_dict is not None
        result = merge_scope_clause_into_metadata_filter(llm_dict, result)
    if folder_ids:
        result = merge_scope_clause_into_metadata_filter(
            _folder_ids_clause(folder_ids, include_subfolders=include_subfolders),
            result,
        )
    if admin_scope_ids:
        result = merge_scope_clause_into_metadata_filter(
            build_folder_id_in_clause(admin_scope_ids),
            result,
        )
    return uniqueql_to_dict(result)
