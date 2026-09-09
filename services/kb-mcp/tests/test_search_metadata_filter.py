"""Tests for the folder-scoped metadata-filter helper used by search's folder_ids."""

from unique_toolkit.content.smart_rules import Statement

from kb_mcp.tools.search.metadata_filter import build_folder_scoped_metadata_filter

ADMIN_FILTER = Statement.model_validate(
    {"operator": "isNotNull", "path": ["folderId"], "value": ""}
)


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
