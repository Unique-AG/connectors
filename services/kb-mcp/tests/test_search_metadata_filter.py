"""Tests for the folder-scoped metadata-filter helper used by search's folder_ids."""

import pytest
from pydantic import ValidationError
from unique_toolkit.content.smart_rules import Statement, parse_uniqueql

from kb_mcp.tools.search.metadata_filter import (
    build_folder_scoped_metadata_filter,
    folder_ids_clause,
    merge_request_metadata_filter,
)

ADMIN_FILTER = Statement.model_validate(
    {"operator": "isNotNull", "path": ["folderId"], "value": ""}
)

LLM_EQUALS_PDF = {
    "operator": "equals",
    "path": ["mimeType"],
    "value": "application/pdf",
}
FOLDER_CLAUSE = {"operator": "in", "path": ["folderId"], "value": ["scope_a"]}


def test_single_folder_include_subfolders_uses_folder_id_path_contains():
    result = build_folder_scoped_metadata_filter(
        ["scope_a"], include_subfolders=True, admin_metadata_filter=ADMIN_FILTER
    )

    scope_clause = result["and"][0]
    assert scope_clause == {
        "or": [{"operator": "contains", "path": ["folderIdPath"], "value": "scope_a"}]
    }
    assert result["and"][1] == ADMIN_FILTER.to_dict()


def test_multiple_folders_include_subfolders_ors_the_contains_clauses():
    result = build_folder_scoped_metadata_filter(
        ["scope_a", "scope_b"],
        include_subfolders=True,
        admin_metadata_filter=ADMIN_FILTER,
    )

    scope_clause = result["and"][0]
    assert scope_clause == {
        "or": [
            {"operator": "contains", "path": ["folderIdPath"], "value": "scope_a"},
            {"operator": "contains", "path": ["folderIdPath"], "value": "scope_b"},
        ]
    }


def test_include_subfolders_false_uses_folder_id_in_clause():
    result = build_folder_scoped_metadata_filter(
        ["scope_a", "scope_b"],
        include_subfolders=False,
        admin_metadata_filter=ADMIN_FILTER,
    )

    scope_clause = result["and"][0]
    assert scope_clause == {
        "operator": "in",
        "path": ["folderId"],
        "value": ["scope_a", "scope_b"],
    }


def test_admin_default_is_always_present_in_the_merged_result():
    result = build_folder_scoped_metadata_filter(
        ["scope_a"], include_subfolders=True, admin_metadata_filter=ADMIN_FILTER
    )

    assert result is not None
    assert ADMIN_FILTER.to_dict() in result["and"]


def test_no_admin_filter_still_returns_the_scope_clause_alone():
    result = build_folder_scoped_metadata_filter(
        ["scope_a"], include_subfolders=False, admin_metadata_filter=None
    )

    assert result == {
        "operator": "in",
        "path": ["folderId"],
        "value": ["scope_a"],
    }


def test_merge_omitted_llm_and_omitted_folder_returns_admin():
    result = merge_request_metadata_filter(admin_metadata_filter=ADMIN_FILTER)

    assert result == ADMIN_FILTER.to_dict()


def test_merge_llm_without_folder_ands_admin_and_llm():
    result = merge_request_metadata_filter(
        admin_metadata_filter=ADMIN_FILTER,
        llm_metadata_filter=LLM_EQUALS_PDF,
    )

    assert result == {"and": [LLM_EQUALS_PDF, ADMIN_FILTER.to_dict()]}


def test_merge_folder_without_llm_ands_admin_and_folder():
    result = merge_request_metadata_filter(
        admin_metadata_filter=ADMIN_FILTER,
        folder_clause=FOLDER_CLAUSE,
    )

    assert result == {"and": [FOLDER_CLAUSE, ADMIN_FILTER.to_dict()]}


def test_merge_llm_and_folder_ands_all_three():
    result = merge_request_metadata_filter(
        admin_metadata_filter=ADMIN_FILTER,
        folder_clause=FOLDER_CLAUSE,
        llm_metadata_filter=LLM_EQUALS_PDF,
    )

    assert result == {"and": [FOLDER_CLAUSE, LLM_EQUALS_PDF, ADMIN_FILTER.to_dict()]}


def test_equals_wrapped_object_is_invalid_uniqueql():
    with pytest.raises(ValueError, match="Invalid UniqueQL"):
        parse_uniqueql({"equals": {"path": ["mimeType"], "value": "application/pdf"}})


def test_path_as_string_is_invalid_uniqueql():
    with pytest.raises(ValidationError):
        parse_uniqueql(
            {"operator": "equals", "path": "mimeType", "value": "application/pdf"}
        )


def test_in_list_parses_and_merges_with_admin():
    parsed = parse_uniqueql(
        {
            "operator": "in",
            "path": ["mimeType"],
            "value": ["application/pdf", "text/plain"],
        }
    )
    result = merge_request_metadata_filter(
        admin_metadata_filter=ADMIN_FILTER,
        llm_metadata_filter=parsed,
    )

    assert result is not None
    assert parsed.to_dict() in result["and"]
    assert ADMIN_FILTER.to_dict() in result["and"]


def test_and_or_uniqueql_parses_and_merges_with_admin():
    parsed = parse_uniqueql(
        {
            "or": [
                {
                    "and": [
                        {
                            "operator": "equals",
                            "path": ["mimeType"],
                            "value": "application/pdf",
                        },
                        {"operator": "contains", "path": ["title"], "value": "Q4"},
                    ]
                },
                {"operator": "equals", "path": ["key"], "value": "notes.md"},
            ]
        }
    )
    result = merge_request_metadata_filter(
        admin_metadata_filter=ADMIN_FILTER,
        llm_metadata_filter=parsed,
    )

    assert result is not None
    assert parsed.to_dict() in result["and"]
    assert ADMIN_FILTER.to_dict() in result["and"]


def test_folder_ids_clause_does_not_mutate_the_input_list():
    folder_ids = ["scope_a", "scope_b"]
    folder_ids_clause(folder_ids, include_subfolders=True)
    folder_ids_clause(folder_ids, include_subfolders=False)
    assert folder_ids == ["scope_a", "scope_b"]
