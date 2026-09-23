"""Tests for the content_metadata tool — aggregation, JSON output, folder
scoping, cache."""

import json
import logging
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import unique_sdk
from fastmcp.tools import ToolResult
from pydantic import SecretStr

from kb_mcp.common import cached_walk
from kb_mcp.common import tree_cache as ct_cache
from kb_mcp.tools.content_metadata import ContentMetadataToolConfig, content_metadata
from kb_mcp.tools.content_metadata.tool import _flatten_metadata_value

pytestmark = pytest.mark.ai

_DEFAULT_ADMIN_FILTER = {
    "operator": "notContains",
    "path": ["folderIdPath"],
    "value": "user-memory",
}


def _make_settings(company_id: str = "company-1", user_id: str = "user-1"):
    settings = MagicMock()
    settings.authcontext.get_confidential_company_id.return_value = company_id
    settings.authcontext.get_confidential_user_id.return_value = user_id
    # Cache key uses the raw SecretStr fields, not the unwrapped getters above.
    settings.authcontext.company_id = SecretStr(company_id)
    settings.authcontext.user_id = SecretStr(user_id)
    return settings


@pytest.fixture(autouse=True)
def identity(monkeypatch):
    """Per-request identity now resolves in-body; tests may override the mock."""
    mock = AsyncMock(return_value=_make_settings())
    monkeypatch.setattr(
        "kb_mcp.tools.content_metadata.tool.get_unique_settings_async", mock
    )
    return mock


@pytest.fixture(autouse=True)
def readable_folders(monkeypatch):
    """folder_ids are probed before the walk; default every id to readable."""
    mock = AsyncMock(return_value={"id": "scope_a"})
    monkeypatch.setattr(
        "kb_mcp.tools.content_metadata.tool.unique_sdk.Folder.get_info_async", mock
    )
    return mock


@pytest.fixture(autouse=True)
def _reset_cache():
    ct_cache._tree_cache = None
    yield
    ct_cache._tree_cache = None


def _make_content_info(content_id: str, metadata: dict | None = None):
    info = MagicMock()
    info.id = content_id
    info.metadata = metadata
    return info


@dataclass
class FakeSnapshot:
    files: list[tuple[MagicMock, PurePosixPath]] = field(default_factory=list)
    folder_paths: list[PurePosixPath] = field(default_factory=list)
    complete: bool = True


def _make_mock_tree(*, snapshot: FakeSnapshot | None = None):
    tree = MagicMock()
    tree.metadata_filter = None
    tree.resolve_visible_file_paths_via_folders_async = AsyncMock(
        return_value=snapshot or FakeSnapshot()
    )
    return tree


def _walk_filter(mock_tree):
    """content_metadata has no LLM filter, so its whole filter rides in the walk."""
    _, kwargs = mock_tree.resolve_visible_file_paths_via_folders_async.call_args
    return kwargs["metadata_filter"]


@pytest.fixture
def applied_filter():
    """Records the merged filter, which now lands on the snapshot rather than
    on the walk call — the walk is deliberately kept filter-free and shared."""
    seen: list[Any] = []
    real = cached_walk.filter_snapshot

    def spy(snapshot: Any, metadata_filter: Any) -> Any:
        seen.append(metadata_filter)
        return real(snapshot, metadata_filter)

    with patch.object(cached_walk, "filter_snapshot", spy):
        yield seen


def _files(*metadata_dicts: dict) -> list[tuple[MagicMock, PurePosixPath]]:
    return [
        (_make_content_info(f"c{i}", metadata=m), PurePosixPath(f"file{i}.pdf"))
        for i, m in enumerate(metadata_dicts)
    ]


def _payload(result: ToolResult) -> list[dict]:
    return json.loads(result.content[0].text)  # type: ignore[union-attr]


def test_flatten_metadata_value_scalar_wraps_in_a_single_item_list():
    assert _flatten_metadata_value("Legal") == ["Legal"]


def test_flatten_metadata_value_list_expands_each_element():
    assert _flatten_metadata_value(["Legal", "Finance"]) == ["Legal", "Finance"]


def test_flatten_metadata_value_drops_nested_objects():
    assert _flatten_metadata_value(["a", {"nested": True}, ["b"]]) == ["a"]
    assert _flatten_metadata_value({"nested": True}) == []


@pytest.mark.asyncio
async def test_returns_json_list_of_single_key_field_to_values_objects():
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(
            files=_files({"department": "Legal"}, {"department": "Finance"})
        )
    )
    with patch(
        "kb_mcp.tools.content_metadata.tool.ContentTree", return_value=mock_tree
    ):
        result = await content_metadata(config=ContentMetadataToolConfig())

    assert isinstance(result, ToolResult)
    payload = _payload(result)
    assert payload == [{"department": ["Legal", "Finance"]}]


@pytest.mark.asyncio
async def test_values_within_a_field_are_ordered_most_common_first():
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(
            files=_files(
                {"status": "approved"},
                {"status": "draft"},
                {"status": "approved"},
            )
        )
    )
    with patch(
        "kb_mcp.tools.content_metadata.tool.ContentTree", return_value=mock_tree
    ):
        result = await content_metadata(config=ContentMetadataToolConfig())

    payload = _payload(result)
    assert payload == [{"status": ["approved", "draft"]}]


@pytest.mark.asyncio
async def test_excludes_folder_id_path_by_default():
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(
            files=_files(
                {"folderIdPath": "uniquepathid://scope_x", "department": "Legal"}
            )
        )
    )
    with patch(
        "kb_mcp.tools.content_metadata.tool.ContentTree", return_value=mock_tree
    ):
        result = await content_metadata(config=ContentMetadataToolConfig())

    payload = _payload(result)
    assert payload == [{"department": ["Legal"]}]


@pytest.mark.asyncio
async def test_excludes_all_system_assigned_fields_by_default():
    """Fields the platform stamps on content itself (identifiers, source
    links, owners) are not business metadata worth building a
    search filter on — none of them should ever show up in the catalog unless
    an admin explicitly re-includes them."""
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(
            files=_files(
                {
                    "key": "hello_world.docx",
                    "url": None,
                    "title": "hello_world.docx",
                    "folderId": "scope_vfr2hptka5em83v5kxtw6t2y",
                    "folderIdPath": "uniquepathid://scope_vfr2hptka5em83v5kxtw6t2y",
                    "mimeType": (
                        "application/vnd.openxmlformats-officedocument"
                        ".wordprocessingml.document"
                    ),
                    "companyId": "225319369280852798",
                    "contentId": "cont_yfco7ld0rgoq3h4cqlazgyuz",
                    "validAsOf": "2026-09-11T12:31:21.256Z",
                    "externalFileOwner": None,
                    "department": "Legal",
                }
            )
        )
    )
    with patch(
        "kb_mcp.tools.content_metadata.tool.ContentTree", return_value=mock_tree
    ):
        result = await content_metadata(config=ContentMetadataToolConfig())

    payload = _payload(result)
    assert payload == [{"department": ["Legal"]}]


@pytest.mark.asyncio
async def test_respects_config_excluded_fields():
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(files=_files({"department": "Legal", "owner": "alice"}))
    )
    config = ContentMetadataToolConfig(excluded_fields=["owner"])
    with patch(
        "kb_mcp.tools.content_metadata.tool.ContentTree", return_value=mock_tree
    ):
        result = await content_metadata(config=config)

    payload = _payload(result)
    assert payload == [{"department": ["Legal"]}]


@pytest.mark.asyncio
async def test_skips_nested_object_values():
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(files=_files({"nested": {"a": 1}, "department": "Legal"}))
    )
    with patch(
        "kb_mcp.tools.content_metadata.tool.ContentTree", return_value=mock_tree
    ):
        result = await content_metadata(config=ContentMetadataToolConfig())

    payload = _payload(result)
    assert payload == [{"department": ["Legal"]}]


@pytest.mark.asyncio
async def test_tolerates_files_with_no_metadata():
    files = _files({"department": "Legal"})
    files.append(
        (_make_content_info("c_no_meta", metadata=None), PurePosixPath("other.pdf"))
    )
    mock_tree = _make_mock_tree(snapshot=FakeSnapshot(files=files))
    with patch(
        "kb_mcp.tools.content_metadata.tool.ContentTree", return_value=mock_tree
    ):
        result = await content_metadata(config=ContentMetadataToolConfig())

    payload = _payload(result)
    assert payload == [{"department": ["Legal"]}]


@pytest.mark.asyncio
async def test_list_valued_field_ors_each_element_as_its_own_value():
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(files=_files({"tags": ["a", "b"]}, {"tags": ["b", "c"]}))
    )
    with patch(
        "kb_mcp.tools.content_metadata.tool.ContentTree", return_value=mock_tree
    ):
        result = await content_metadata(config=ContentMetadataToolConfig())

    payload = _payload(result)
    assert len(payload) == 1
    assert set(payload[0]["tags"]) == {"a", "b", "c"}


@pytest.mark.asyncio
async def test_empty_snapshot_returns_empty_list():
    mock_tree = _make_mock_tree(snapshot=FakeSnapshot(files=[]))
    with patch(
        "kb_mcp.tools.content_metadata.tool.ContentTree", return_value=mock_tree
    ):
        result = await content_metadata(config=ContentMetadataToolConfig())

    assert _payload(result) == []


@pytest.mark.asyncio
async def test_no_folder_ids_uses_the_admin_default_filter_unscoped(applied_filter):
    mock_tree = _make_mock_tree()
    with patch(
        "kb_mcp.tools.content_metadata.tool.ContentTree", return_value=mock_tree
    ):
        await content_metadata(config=ContentMetadataToolConfig())

    assert _walk_filter(mock_tree) == _DEFAULT_ADMIN_FILTER


@pytest.mark.asyncio
async def test_single_folder_id_with_subfolders_uses_scoped_walk(applied_filter):
    """A single folder_id (the common case) walks only that folder's
    subtree via ScopedContentTree instead of the whole knowledge base —
    folder scoping happens through the walk root, so only the admin filter
    (not another folderIdPath clause) reaches the walk."""
    mock_tree = _make_mock_tree()
    with patch(
        "kb_mcp.tools.content_metadata.tool.ScopedContentTree",
        return_value=mock_tree,
    ) as mock_cls:
        await content_metadata(
            folder_ids=["scope_a"], config=ContentMetadataToolConfig()
        )

    mock_cls.assert_called_once_with(
        company_id="company-1", user_id="user-1", root_scope_ids=("scope_a",)
    )
    assert _walk_filter(mock_tree) == _DEFAULT_ADMIN_FILTER


@pytest.mark.asyncio
async def test_multiple_folder_ids_all_use_scoped_walk(applied_filter):
    """Any number of folder_ids can each root their own scoped walk — no
    fallback to the old unscoped-walk-then-filter path just because there's
    more than one."""
    mock_tree = _make_mock_tree()
    with patch(
        "kb_mcp.tools.content_metadata.tool.ScopedContentTree",
        return_value=mock_tree,
    ) as mock_cls:
        await content_metadata(
            folder_ids=["scope_b", "scope_a"], config=ContentMetadataToolConfig()
        )

    mock_cls.assert_called_once_with(
        company_id="company-1",
        user_id="user-1",
        root_scope_ids=("scope_a", "scope_b"),
    )
    assert _walk_filter(mock_tree) == _DEFAULT_ADMIN_FILTER


@pytest.mark.asyncio
async def test_duplicate_folder_ids_deduplicated_before_scoped_walk():
    mock_tree = _make_mock_tree()
    with patch(
        "kb_mcp.tools.content_metadata.tool.ScopedContentTree",
        return_value=mock_tree,
    ) as mock_cls:
        await content_metadata(
            folder_ids=["scope_a", "scope_a"], config=ContentMetadataToolConfig()
        )

    mock_cls.assert_called_once_with(
        company_id="company-1", user_id="user-1", root_scope_ids=("scope_a",)
    )


@pytest.mark.asyncio
async def test_without_subfolders_scopes_the_walk_at_depth_one():
    """include_subfolders=False is direct-children-only, which the scoped walk
    expresses as max_depth=1 — no need to fall back to walking everything."""
    mock_tree = _make_mock_tree()
    with (
        patch(
            "kb_mcp.tools.content_metadata.tool.ScopedContentTree",
            return_value=mock_tree,
        ) as scoped_cls,
        patch("kb_mcp.tools.content_metadata.tool.ContentTree") as unscoped_cls,
    ):
        await content_metadata(
            folder_ids=["scope_a"],
            include_subfolders=False,
            config=ContentMetadataToolConfig(),
        )

    scoped_cls.assert_called_once()
    assert scoped_cls.call_args.kwargs["root_scope_ids"] == ("scope_a",)
    unscoped_cls.assert_not_called()
    walk_kwargs = (
        mock_tree.resolve_visible_file_paths_via_folders_async.call_args.kwargs
    )
    assert walk_kwargs["max_depth"] == 1


@pytest.mark.asyncio
async def test_folder_path_resolves_to_scope_id_and_uses_scoped_walk(applied_filter):
    mock_tree = _make_mock_tree()
    resolve = AsyncMock(return_value="scope_resolved")
    with (
        patch(
            "kb_mcp.tools.content_metadata.tool.unique_sdk.Folder"
            ".resolve_scope_id_from_folder_path_async",
            resolve,
        ),
        patch(
            "kb_mcp.tools.content_metadata.tool.ScopedContentTree",
            return_value=mock_tree,
        ) as mock_cls,
    ):
        await content_metadata(
            folder_paths=["Contracts/2024"], config=ContentMetadataToolConfig()
        )

    resolve.assert_awaited_once_with(
        user_id="user-1", company_id="company-1", folder_path="/Contracts/2024"
    )
    mock_cls.assert_called_once_with(
        company_id="company-1", user_id="user-1", root_scope_ids=("scope_resolved",)
    )
    assert _walk_filter(mock_tree) == _DEFAULT_ADMIN_FILTER


@pytest.mark.asyncio
async def test_multiple_folder_paths_resolve_and_use_scoped_walk():
    mock_tree = _make_mock_tree()
    resolve = AsyncMock(side_effect=["scope_a", "scope_b"])
    with (
        patch(
            "kb_mcp.tools.content_metadata.tool.unique_sdk.Folder"
            ".resolve_scope_id_from_folder_path_async",
            resolve,
        ),
        patch(
            "kb_mcp.tools.content_metadata.tool.ScopedContentTree",
            return_value=mock_tree,
        ) as mock_cls,
    ):
        await content_metadata(
            folder_paths=["Contracts/2024", "Invoices"],
            config=ContentMetadataToolConfig(),
        )

    assert resolve.await_count == 2
    mock_cls.assert_called_once_with(
        company_id="company-1",
        user_id="user-1",
        root_scope_ids=("scope_a", "scope_b"),
    )


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("demo", "/demo"),
        ("Contracts/2024", "/Contracts/2024"),
        ("/already/absolute", "/already/absolute"),
        ("trailing/slash/", "/trailing/slash"),
    ],
)
@pytest.mark.asyncio
async def test_folder_path_is_normalized_to_an_absolute_path(given: str, expected: str):
    """The backend's folder-path lookup only accepts an absolute path (every
    value the unique_sdk CLI itself ever sends starts with "/") — a bare
    relative path must be normalized rather than rejected by the backend."""
    resolve = AsyncMock(return_value="scope_resolved")
    with (
        patch(
            "kb_mcp.tools.content_metadata.tool.unique_sdk.Folder"
            ".resolve_scope_id_from_folder_path_async",
            resolve,
        ),
        patch(
            "kb_mcp.tools.content_metadata.tool.ScopedContentTree",
            return_value=_make_mock_tree(),
        ),
    ):
        await content_metadata(folder_paths=[given], config=ContentMetadataToolConfig())

    _, kwargs = resolve.call_args
    assert kwargs["folder_path"] == expected


@pytest.mark.asyncio
async def test_folder_path_not_found_surfaces_as_tool_error():
    resolve = AsyncMock(
        side_effect=ValueError("Could not find a folder with folderPath: Nonexistent")
    )
    with patch(
        "kb_mcp.tools.content_metadata.tool.unique_sdk.Folder"
        ".resolve_scope_id_from_folder_path_async",
        resolve,
    ):
        result = await content_metadata(
            folder_paths=["Nonexistent"], config=ContentMetadataToolConfig()
        )

    assert result.is_error is True
    assert "Nonexistent" in result.content[0].text  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_folder_ids_and_folder_paths_together_errors_without_calling_service():
    with patch("kb_mcp.tools.content_metadata.tool.ContentTree") as mock_cls:
        result = await content_metadata(
            folder_ids=["scope_a"],
            folder_paths=["Contracts/2024"],
            config=ContentMetadataToolConfig(),
        )

    assert result.is_error is True
    assert "folder_ids" in result.content[0].text  # type: ignore[union-attr]
    assert "folder_paths" in result.content[0].text  # type: ignore[union-attr]
    mock_cls.assert_not_called()


@pytest.mark.asyncio
async def test_without_subfolders_needs_no_folder_clause_in_the_filter(applied_filter):
    """The walk is rooted and depth-capped, so the folder scope is already
    expressed by where it walks — repeating it as a filter clause is redundant."""
    mock_tree = _make_mock_tree()
    with patch(
        "kb_mcp.tools.content_metadata.tool.ScopedContentTree", return_value=mock_tree
    ):
        await content_metadata(
            folder_ids=["scope_a"],
            include_subfolders=False,
            config=ContentMetadataToolConfig(),
        )

    assert "['folderId']" not in str(_walk_filter(mock_tree))


@pytest.mark.asyncio
async def test_admin_configured_metadata_filter_is_the_base_for_folder_scoping(
    applied_filter,
):
    custom_filter = {"operator": "equals", "path": ["type"], "value": "pdf"}
    config = ContentMetadataToolConfig(metadata_filter=custom_filter)
    mock_tree = _make_mock_tree()
    with patch(
        "kb_mcp.tools.content_metadata.tool.ContentTree", return_value=mock_tree
    ):
        await content_metadata(config=config)

    assert _walk_filter(mock_tree) == custom_filter


@pytest.mark.asyncio
async def test_refresh_true_invalidates_caller_cache_only():
    mock_tree = _make_mock_tree()
    with patch(
        "kb_mcp.tools.content_metadata.tool.ContentTree", return_value=mock_tree
    ):
        await content_metadata(refresh=True, config=ContentMetadataToolConfig())

    mock_tree.invalidate_cache.assert_called_once_with()


@pytest.mark.asyncio
async def test_refresh_false_does_not_invalidate_cache():
    mock_tree = _make_mock_tree()
    with patch(
        "kb_mcp.tools.content_metadata.tool.ContentTree", return_value=mock_tree
    ):
        await content_metadata(refresh=False, config=ContentMetadataToolConfig())

    mock_tree.invalidate_cache.assert_not_called()


@pytest.mark.asyncio
async def test_cache_reuses_same_content_tree_instance_for_same_identity():
    mock_tree = _make_mock_tree()
    with patch(
        "kb_mcp.tools.content_metadata.tool.ContentTree", return_value=mock_tree
    ) as mock_cls:
        await content_metadata(config=ContentMetadataToolConfig())
        await content_metadata(config=ContentMetadataToolConfig())

    mock_cls.assert_called_once()
    assert mock_tree.resolve_visible_file_paths_via_folders_async.await_count == 2


@pytest.mark.asyncio
async def test_incomplete_snapshot_leads_with_notice():
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(files=_files({"department": "Legal"}), complete=False)
    )
    with patch(
        "kb_mcp.tools.content_metadata.tool.ContentTree", return_value=mock_tree
    ):
        result = await content_metadata(config=ContentMetadataToolConfig())

    assert len(result.content) == 2  # type: ignore[arg-type]
    assert result.content[0].text.startswith("This scan is incomplete.")  # type: ignore[union-attr]
    assert json.loads(result.content[1].text) == [{"department": ["Legal"]}]  # type: ignore[union-attr]


@pytest.mark.asyncio
@pytest.mark.parametrize("counts_only", [False, True])
async def test_incomplete_snapshot_does_not_claim_requested_fields_are_absent(
    counts_only: bool,
):
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(files=_files({"department": "Legal"}), complete=False)
    )
    with patch(
        "kb_mcp.tools.content_metadata.tool.ContentTree", return_value=mock_tree
    ):
        result = await content_metadata(
            fields=["department", "region"],
            counts_only=counts_only,
            config=ContentMetadataToolConfig(),
        )

    texts = [block.text for block in result.content]  # type: ignore[union-attr]
    assert len(texts) == 2
    assert texts[0].startswith("This scan is incomplete.")
    assert json.loads(texts[1]) == (
        [{"department": 1}] if counts_only else [{"department": ["Legal"]}]
    )
    assert not any("No values found" in text for text in texts)


@pytest.mark.asyncio
async def test_identity_refusal_surfaces_as_tool_error(identity):
    identity.side_effect = ValueError("Refusing UNIQUE_AUTH_* env fallback")
    result = await content_metadata(config=ContentMetadataToolConfig())

    assert result.is_error is True
    assert "UNIQUE_AUTH_" in result.content[0].text  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_logs_never_contain_raw_user_or_company_id(caplog):
    mock_tree = _make_mock_tree()
    with (
        caplog.at_level(logging.INFO, logger="kb_mcp"),
        patch("kb_mcp.tools.content_metadata.tool.ContentTree", return_value=mock_tree),
    ):
        await content_metadata(config=ContentMetadataToolConfig())

    assert caplog.records, "expected at least one log record"
    for record in caplog.records:
        assert "user-1" not in record.getMessage()
        assert "company-1" not in record.getMessage()


@pytest.mark.asyncio
async def test_unreadable_folder_id_surfaces_as_tool_error(readable_folders):
    """The walk cannot report this: unique_toolkit turns a failed listing into
    no children, so without the probe it renders as an empty catalog."""
    readable_folders.side_effect = unique_sdk.APIError("no folder with that scope id")

    with patch("kb_mcp.tools.content_metadata.tool.ScopedContentTree") as mock_cls:
        result = await content_metadata(
            folder_ids=["scope_denied"], config=ContentMetadataToolConfig()
        )

    assert result.is_error is True
    assert "scope_denied" in result.content[0].text  # type: ignore[union-attr]
    mock_cls.assert_not_called()


@pytest.mark.asyncio
async def test_a_backend_outage_does_not_claim_the_id_is_wrong(readable_folders):
    readable_folders.side_effect = unique_sdk.APIConnectionError("kb unreachable")

    result = await content_metadata(
        folder_ids=["scope_a"], config=ContentMetadataToolConfig()
    )

    assert result.is_error is True
    assert "temporarily unavailable" in result.content[0].text  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_forwards_the_clamped_timeout_and_configured_concurrency():
    """The clamp lives on Settings now; this pins that the tool actually uses it."""
    mock_tree = _make_mock_tree()
    with patch(
        "kb_mcp.tools.content_metadata.tool.ContentTree", return_value=mock_tree
    ):
        await content_metadata(timeout=300, config=ContentMetadataToolConfig())

    _, kwargs = mock_tree.resolve_visible_file_paths_via_folders_async.call_args
    assert kwargs["timeout"] == 45.0
    assert kwargs["max_concurrent_directory_listings"] == 25


@pytest.mark.asyncio
async def test_timeout_defaults_to_the_configured_wait():
    mock_tree = _make_mock_tree()
    with patch(
        "kb_mcp.tools.content_metadata.tool.ContentTree", return_value=mock_tree
    ):
        await content_metadata(config=ContentMetadataToolConfig())

    _, kwargs = mock_tree.resolve_visible_file_paths_via_folders_async.call_args
    assert kwargs["timeout"] == 30.0


@pytest.mark.asyncio
async def test_folder_path_resolving_to_nothing_errors_instead_of_widening():
    """A falsy resolve must not drop the restriction: scoping to one folder and
    silently getting the whole knowledge base's catalog is the worse answer."""
    resolve = AsyncMock(return_value=None)
    with (
        patch(
            "kb_mcp.tools.content_metadata.tool.unique_sdk.Folder"
            ".resolve_scope_id_from_folder_path_async",
            resolve,
        ),
        patch("kb_mcp.tools.content_metadata.tool.ContentTree") as unscoped,
    ):
        result = await content_metadata(
            folder_paths=["Contracts/2024"], config=ContentMetadataToolConfig()
        )

    assert result.is_error is True
    assert "Contracts/2024" in result.content[0].text  # type: ignore[union-attr]
    unscoped.assert_not_called()


@pytest.mark.asyncio
async def test_one_unresolvable_path_fails_the_call_rather_than_narrowing_it():
    """Two paths in, one resolvable: scoping to just the resolvable one would
    answer a question the caller did not ask."""
    resolve = AsyncMock(
        side_effect=lambda **kw: "scope_a" if "Good" in kw["folder_path"] else None
    )
    with (
        patch(
            "kb_mcp.tools.content_metadata.tool.unique_sdk.Folder"
            ".resolve_scope_id_from_folder_path_async",
            resolve,
        ),
        patch("kb_mcp.tools.content_metadata.tool.ScopedContentTree") as scoped,
    ):
        result = await content_metadata(
            folder_paths=["Good", "Bad"], config=ContentMetadataToolConfig()
        )

    assert result.is_error is True
    assert "Bad" in result.content[0].text  # type: ignore[union-attr]
    scoped.assert_not_called()


def _rich_snapshot() -> FakeSnapshot:
    return FakeSnapshot(
        files=_files(
            {"department": "Legal", "status": "draft", "region": "EU"},
            {"department": "Finance", "status": "approved"},
            {"department": "Legal"},
        )
    )


@pytest.mark.asyncio
async def test_fields_limits_the_catalog_to_the_requested_fields():
    mock_tree = _make_mock_tree(snapshot=_rich_snapshot())
    with patch(
        "kb_mcp.tools.content_metadata.tool.ContentTree", return_value=mock_tree
    ):
        result = await content_metadata(
            fields=["status", "region"], config=ContentMetadataToolConfig()
        )

    assert _payload(result) == [{"status": ["draft", "approved"]}, {"region": ["EU"]}]
    assert len(result.content) == 1


@pytest.mark.asyncio
async def test_counts_only_returns_distinct_value_counts_most_widely_used_first():
    mock_tree = _make_mock_tree(snapshot=_rich_snapshot())
    with patch(
        "kb_mcp.tools.content_metadata.tool.ContentTree", return_value=mock_tree
    ):
        result = await content_metadata(
            counts_only=True, config=ContentMetadataToolConfig()
        )

    assert _payload(result) == [{"department": 2}, {"status": 2}, {"region": 1}]


@pytest.mark.asyncio
async def test_counts_only_combines_with_fields():
    mock_tree = _make_mock_tree(snapshot=_rich_snapshot())
    with patch(
        "kb_mcp.tools.content_metadata.tool.ContentTree", return_value=mock_tree
    ):
        result = await content_metadata(
            fields=["region", "department"],
            counts_only=True,
            config=ContentMetadataToolConfig(),
        )

    assert _payload(result) == [{"department": 2}, {"region": 1}]


@pytest.mark.asyncio
async def test_counts_only_still_hides_admin_excluded_fields():
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(files=_files({"key": "a.pdf", "department": "Legal"}))
    )
    with patch(
        "kb_mcp.tools.content_metadata.tool.ContentTree", return_value=mock_tree
    ):
        result = await content_metadata(
            counts_only=True, config=ContentMetadataToolConfig()
        )

    assert _payload(result) == [{"department": 1}]


@pytest.mark.asyncio
async def test_requesting_an_admin_excluded_field_does_not_reveal_it():
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(files=_files({"key": "a.pdf", "department": "Legal"}))
    )
    with patch(
        "kb_mcp.tools.content_metadata.tool.ContentTree", return_value=mock_tree
    ):
        result = await content_metadata(
            fields=["key"], config=ContentMetadataToolConfig()
        )

    assert _payload(result) == []
    assert "'key'" in result.content[1].text  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_requested_fields_with_no_values_are_named_in_a_notice():
    mock_tree = _make_mock_tree(snapshot=_rich_snapshot())
    with patch(
        "kb_mcp.tools.content_metadata.tool.ContentTree", return_value=mock_tree
    ):
        result = await content_metadata(
            fields=["Department", "status", "Department"],
            config=ContentMetadataToolConfig(),
        )

    assert _payload(result) == [{"status": ["draft", "approved"]}]
    notice = result.content[1].text  # type: ignore[union-attr]
    assert "['Department']" in notice
    assert "counts_only=true" in notice


@pytest.mark.asyncio
@pytest.mark.parametrize("counts_only", [False, True])
async def test_empty_fields_list_returns_no_fields(counts_only: bool):
    mock_tree = _make_mock_tree(snapshot=_rich_snapshot())
    with patch(
        "kb_mcp.tools.content_metadata.tool.ContentTree", return_value=mock_tree
    ):
        result = await content_metadata(
            fields=[], counts_only=counts_only, config=ContentMetadataToolConfig()
        )

    assert _payload(result) == []
    assert len(result.content) == 1  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_omitted_fields_returns_every_field():
    mock_tree = _make_mock_tree(snapshot=_rich_snapshot())
    with patch(
        "kb_mcp.tools.content_metadata.tool.ContentTree", return_value=mock_tree
    ):
        result = await content_metadata(config=ContentMetadataToolConfig())

    assert [next(iter(entry)) for entry in _payload(result)] == [
        "department",
        "status",
        "region",
    ]


@pytest.mark.asyncio
async def test_counts_only_counts_each_list_element_as_a_distinct_value():
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(
            files=_files({"tags": ["a", "b"]}, {"tags": ["b", "c"]}, {"tags": "a"})
        )
    )
    with patch(
        "kb_mcp.tools.content_metadata.tool.ContentTree", return_value=mock_tree
    ):
        result = await content_metadata(
            counts_only=True, config=ContentMetadataToolConfig()
        )

    assert _payload(result) == [{"tags": 3}]
