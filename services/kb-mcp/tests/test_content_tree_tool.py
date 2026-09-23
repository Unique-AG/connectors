"""Tests for the content_tree tool — mode dispatch, validation, cache, filtering."""

import asyncio
import gc
import inspect
import logging
import weakref
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.server.providers.filesystem_discovery import import_module_from_file
from fastmcp.tools import ToolResult
from pydantic import SecretStr
from unique_toolkit.content.schemas import ContentInfo
from unique_toolkit.content.smart_rules import parse_uniqueql
from unique_toolkit.experimental.components.content_tree.schemas import (
    FolderWalkSnapshot,
)
from unique_toolkit.experimental.components.content_tree.schemas import (
    MatchTarget as ServiceMatchTarget,
)
from unique_toolkit.experimental.resources.feature_flags._ttl_cache import (
    AsyncTTLCache,
)

from kb_mcp.common import cached_walk
from kb_mcp.common import tree_cache as ct_cache
from kb_mcp.common.references import (
    INVALID_METADATA_FILTER_MESSAGE,
    METADATA_FILTER_ARG_DESCRIPTION,
    METADATA_FILTER_EMPTY_RETRY_HINT,
    UNIQUEQL_EQUALS_PDF,
    UNIQUEQL_EQUALS_PDF_WRAPPED,
    MetadataFilterArgument,
)
from kb_mcp.common.tree_cache import expire_idle_trees
from kb_mcp.settings import get_settings
from kb_mcp.tools.content_tree import (
    ContentTreeToolConfig,
    MatchTarget,
    content_tree,
)
from kb_mcp.tools.content_tree import tool as ct_module

pytestmark = pytest.mark.ai


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
        "kb_mcp.tools.content_tree.tool.get_unique_settings_async", mock
    )
    return mock


def _make_content_info(content_id: str, key: str = "", metadata: dict | None = None):
    info = MagicMock()
    info.id = content_id
    info.metadata = metadata
    info.owner_id = "user_123"
    info.key = key or content_id
    return info


def _make_fuzzy_match(path_segments: list[str], score: float, content_id: str):
    match = MagicMock()
    match.path_segments = path_segments
    match.score = score
    match.content_info = _make_content_info(content_id)
    return match


@dataclass
class FakeSnapshot:
    files: list[tuple[MagicMock, PurePosixPath]] = field(default_factory=list)
    folder_paths: list[PurePosixPath] = field(default_factory=list)
    complete: bool = True
    rendered: str = "tree output"
    render_calls: list[dict[str, object]] = field(default_factory=list)

    def render(self, **kwargs: object) -> str:
        self.render_calls.append(kwargs)
        return self.rendered

    def to_trie(self):
        # Real trie-building logic (sorting, sentinel/bracket handling) lives
        # on the toolkit's own snapshot type — delegate rather than refork it.
        return FolderWalkSnapshot(
            files=self.files, folder_paths=self.folder_paths, complete=self.complete
        ).to_trie()


def _make_mock_tree(*, snapshot: FakeSnapshot | None = None):
    tree = MagicMock()
    tree.metadata_filter = None
    tree.resolve_visible_file_paths_via_folders_async = AsyncMock(
        return_value=snapshot or FakeSnapshot()
    )
    tree.search_visible_files_fuzzy_async = AsyncMock(return_value=[])
    return tree


def _walk_filter(mock_tree):
    """The admin half rides in the walk; `applied_filter` sees the LLM half."""
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


@pytest.fixture(autouse=True)
def _reset_cache():
    ct_cache._tree_cache = None
    yield
    ct_cache._tree_cache = None


def test_match_target_matches_service_definition():
    assert set(MatchTarget.__args__) == set(ServiceMatchTarget.__args__)


def test_metadata_filter_arg_uses_locked_field_description():
    assert (
        inspect.signature(content_tree).parameters["metadata_filter"].annotation
        is MetadataFilterArgument
    )
    assert METADATA_FILTER_ARG_DESCRIPTION in str(MetadataFilterArgument.__value__)


def _make_dispatch_probe_tree():
    """A tree whose three views return distinguishable output."""
    tree = MagicMock()
    tree.metadata_filter = None
    tree.resolve_visible_file_paths_via_folders_async = AsyncMock(
        return_value=FakeSnapshot(
            files=[
                (_make_content_info("list-result"), PurePosixPath("LIST/VIEW")),
            ],
            rendered="TREE VIEW",
        )
    )
    tree.search_visible_files_fuzzy_async = AsyncMock(
        return_value=[_make_fuzzy_match(["SEARCH", "VIEW"], 0.9, "search-result")]
    )
    return tree


@pytest.mark.asyncio
async def test_mode_tree_returns_tree_view_only():
    mock_tree = _make_dispatch_probe_tree()
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="tree",
            config=ContentTreeToolConfig(),
        )

    assert isinstance(result, ToolResult)
    text = result.content[0].text  # type: ignore[union-attr]
    assert text == ".\n└── LIST\n    └── VIEW"
    assert "list-result" not in text
    assert "search-result" not in text


@pytest.mark.asyncio
async def test_logs_never_contain_raw_user_or_company_id(caplog):
    """user_id/company_id are confidential; logs must carry a correlation
    id derived from them, never the raw values."""
    mock_tree = _make_mock_tree()
    with (
        caplog.at_level(logging.INFO, logger="kb_mcp"),
        patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree),
    ):
        await content_tree(mode="tree", config=ContentTreeToolConfig())

    assert caplog.records, "expected at least one log record"
    for record in caplog.records:
        assert "user-1" not in record.getMessage()
        assert "company-1" not in record.getMessage()


@pytest.mark.asyncio
async def test_mode_list_returns_list_view_only():
    mock_tree = _make_dispatch_probe_tree()
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="list",
            config=ContentTreeToolConfig(),
        )

    assert isinstance(result, ToolResult)
    text = result.content[0].text  # type: ignore[union-attr]
    assert "[LIST/VIEW](unique://content/list-result) (content_id=list-result)" in text
    assert "TREE VIEW" not in text
    assert "search-result" not in text


@pytest.mark.asyncio
async def test_mode_search_returns_search_view_only():
    mock_tree = _make_dispatch_probe_tree()
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="search",
            query="a.pdf",
            config=ContentTreeToolConfig(),
        )

    assert isinstance(result, ToolResult)
    text = result.content[0].text  # type: ignore[union-attr]
    assert (
        "[SEARCH/VIEW](unique://content/search-result) "
        "(score=0.90, content_id=search-result)"
    ) in text
    assert "TREE VIEW" not in text
    assert "list-result" not in text


@pytest.mark.asyncio
async def test_mode_search_without_query_returns_error_without_calling_service():
    with patch("kb_mcp.tools.content_tree.tool.ContentTree") as mock_cls:
        result = await content_tree(
            mode="search",
            query=None,
            config=ContentTreeToolConfig(),
        )

    assert isinstance(result, ToolResult)
    assert result.is_error is True
    assert result.content[0].text == "query is required when mode='search'"  # type: ignore[union-attr]
    mock_cls.assert_not_called()


@pytest.mark.asyncio
async def test_tree_mode_with_query_errors_instead_of_silently_ignoring_it():
    """A search-only param under mode='tree' used to be silently ignored,
    giving no signal the call did the wrong thing — must now error before
    ever reaching the service."""
    with patch("kb_mcp.tools.content_tree.tool.ContentTree") as mock_cls:
        result = await content_tree(
            mode="tree",
            query="reconciliation",
            match_on="both",
            config=ContentTreeToolConfig(),
        )

    assert isinstance(result, ToolResult)
    assert result.is_error is True
    text = result.content[0].text  # type: ignore[union-attr]
    assert "query" in text
    assert "match_on" in text
    assert "mode='search'" in text
    mock_cls.assert_not_called()


@pytest.mark.asyncio
async def test_list_mode_with_min_score_errors():
    with patch("kb_mcp.tools.content_tree.tool.ContentTree") as mock_cls:
        result = await content_tree(
            mode="list", min_score=0.5, config=ContentTreeToolConfig()
        )

    assert isinstance(result, ToolResult)
    assert result.is_error is True
    assert "min_score" in result.content[0].text  # type: ignore[union-attr]
    mock_cls.assert_not_called()


@pytest.mark.asyncio
async def test_list_mode_with_folders_only_errors_instead_of_ignoring_it():
    """folders_only has no effect outside mode='tree'; list has no folder
    concept at all, so silently ignoring it would hide the caller's mistake."""
    with patch("kb_mcp.tools.content_tree.tool.ContentTree") as mock_cls:
        result = await content_tree(
            mode="list", folders_only=True, config=ContentTreeToolConfig()
        )

    assert isinstance(result, ToolResult)
    assert result.is_error is True
    text = result.content[0].text  # type: ignore[union-attr]
    assert "folders_only" in text
    assert "mode='tree'" in text
    mock_cls.assert_not_called()


@pytest.mark.asyncio
async def test_search_mode_with_folders_only_errors_instead_of_ignoring_it():
    """Same gap as list: search has no folder concept either."""
    with patch("kb_mcp.tools.content_tree.tool.ContentTree") as mock_cls:
        result = await content_tree(
            mode="search",
            query="a.pdf",
            folders_only=True,
            config=ContentTreeToolConfig(),
        )

    assert isinstance(result, ToolResult)
    assert result.is_error is True
    text = result.content[0].text  # type: ignore[union-attr]
    assert "folders_only" in text
    assert "mode='tree'" in text
    mock_cls.assert_not_called()


@pytest.mark.asyncio
async def test_search_mode_accepts_folder_path():
    """folder_path scopes every mode now, not just list."""
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(
            files=[
                (_make_content_info("c1"), PurePosixPath("Contracts/a.pdf")),
                (_make_content_info("c2"), PurePosixPath("Other/a.pdf")),
            ]
        )
    )
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="search",
            query="a.pdf",
            folder_path="Contracts",
            config=ContentTreeToolConfig(),
        )

    assert isinstance(result, ToolResult)
    assert result.is_error is not True
    text = result.content[0].text  # type: ignore[union-attr]
    assert "content_id=c1" in text
    assert "content_id=c2" not in text


@pytest.mark.asyncio
async def test_tree_mode_accepts_folder_path():
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(
            files=[
                (_make_content_info("c1"), PurePosixPath("Contracts/a.pdf")),
                (_make_content_info("c2"), PurePosixPath("Other/b.pdf")),
            ]
        )
    )
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="tree", folder_path="Contracts", config=ContentTreeToolConfig()
        )

    assert isinstance(result, ToolResult)
    assert result.is_error is not True
    text = result.content[0].text  # type: ignore[union-attr]
    assert "a.pdf" in text
    assert "b.pdf" not in text


@pytest.mark.asyncio
async def test_folder_path_prefix_filter_is_case_sensitive_exact_match():
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(
            files=[
                (_make_content_info("c1"), PurePosixPath("Contracts/2024/a.pdf")),
                (_make_content_info("c2"), PurePosixPath("contracts/2024/b.pdf")),
                (_make_content_info("c3"), PurePosixPath("Other/c.pdf")),
            ]
        )
    )
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="list",
            folder_path="Contracts/2024",
            config=ContentTreeToolConfig(),
        )

    text = result.content[0].text  # type: ignore[union-attr]
    assert "content_id=c1" in text
    assert "content_id=c2" not in text
    assert "content_id=c3" not in text


@pytest.mark.asyncio
async def test_folder_path_filter_matches_display_path_with_brackets_stripped():
    """Filters use display paths so ``ORG/Alpha`` matches ``[ORG]/Alpha``."""
    bracketed_folder = "[ORG]"
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(
            files=[
                (
                    _make_content_info("c1"),
                    PurePosixPath(f"{bracketed_folder}/Alpha/a.pdf"),
                ),
                (
                    _make_content_info("c2"),
                    PurePosixPath(f"{bracketed_folder}/Other/b.pdf"),
                ),
                (_make_content_info("c3"), PurePosixPath("Contracts/c.pdf")),
            ]
        )
    )
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="list",
            folder_path="ORG/Alpha",
            config=ContentTreeToolConfig(),
        )

    text = result.content[0].text  # type: ignore[union-attr]
    assert "content_id=c1" in text
    assert "content_id=c2" not in text
    assert "content_id=c3" not in text


@pytest.mark.asyncio
async def test_limit_none_falls_back_to_config_default_limit():
    rows = [
        (_make_content_info(f"c{i}"), PurePosixPath(f"file{i}.pdf")) for i in range(5)
    ]
    mock_tree = _make_mock_tree(snapshot=FakeSnapshot(files=rows))
    config = ContentTreeToolConfig(default_limit=2)
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="list",
            limit=None,
            config=config,
        )

    text = result.content[0].text  # type: ignore[union-attr]
    assert "first 2 of 5 files" in text
    assert len([line for line in text.splitlines() if "content_id=" in line]) == 2


@pytest.mark.asyncio
async def test_list_mode_below_limit_reports_no_truncation():
    rows = [(_make_content_info("c0"), PurePosixPath("file0.pdf"))]
    mock_tree = _make_mock_tree(snapshot=FakeSnapshot(files=rows))
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="list", limit=5, config=ContentTreeToolConfig()
        )

    text = result.content[0].text  # type: ignore[union-attr]
    assert "Raise `limit`" not in text


@pytest.mark.asyncio
async def test_cache_reuses_same_content_tree_instance_for_same_identity():
    mock_tree = _make_mock_tree()
    with patch(
        "kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree
    ) as mock_cls:
        await content_tree(mode="tree", config=ContentTreeToolConfig())
        await content_tree(mode="tree", config=ContentTreeToolConfig())

    mock_cls.assert_called_once()
    assert mock_tree.resolve_visible_file_paths_via_folders_async.await_count == 2


def test_cache_settings_default_and_env_override(monkeypatch):
    assert get_settings().tree_cache_max_entries == 24
    assert get_settings().tree_cache_ttl_seconds == 600

    monkeypatch.setenv("KB_MCP_TREE_CACHE_MAX_ENTRIES", "999")
    get_settings.cache_clear()
    assert get_settings().tree_cache_max_entries == 999

    monkeypatch.setenv("KB_MCP_TREE_CACHE_TTL_SECONDS", "60")
    get_settings.cache_clear()
    assert get_settings().tree_cache_ttl_seconds == 60


def test_expire_idle_trees_is_noop_when_cache_uninitialized():
    assert expire_idle_trees() == 0


@pytest.mark.asyncio
async def test_expire_idle_trees_releases_entries_after_ttl():
    """cachetools keeps expired values until expire(); a later .get() does not."""
    ct_cache._tree_cache = AsyncTTLCache(maxsize=8, ttl_ms=50, keep_stale=False)

    class _Tree:
        pass

    held = _Tree()
    ref = weakref.ref(held)

    async def fetch() -> object:
        value = ref()
        assert value is not None
        return value

    await ct_cache._tree_cache.get_or_fetch("k", fetch)
    del held
    del fetch
    gc.collect()
    assert ref() is not None

    await asyncio.sleep(0.08)
    gc.collect()
    assert ref() is not None

    assert expire_idle_trees() == 1
    gc.collect()
    assert ref() is None
    assert expire_idle_trees() == 0


def test_filesystem_provider_and_lifespan_share_tree_cache():
    tool_path = Path(ct_module.__file__)
    provider_module = import_module_from_file(
        tool_path, provider_root=tool_path.parent.parent
    )
    settings = get_settings()

    assert provider_module.get_tree_cache(settings) is ct_cache.get_tree_cache(settings)


@pytest.mark.asyncio
async def test_refresh_true_invalidates_caller_cache_only():
    mock_tree = _make_mock_tree()
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="tree",
            refresh=True,
            config=ContentTreeToolConfig(),
        )

    mock_tree.invalidate_cache.assert_called_once_with()
    mock_tree.resolve_visible_file_paths_via_folders_async.assert_called_once()
    assert isinstance(result, ToolResult)
    assert result.content[0].text == "."  # type: ignore[union-attr]  # empty snapshot


@pytest.mark.asyncio
async def test_refresh_false_does_not_invalidate_cache():
    mock_tree = _make_mock_tree()
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        await content_tree(
            mode="tree",
            refresh=False,
            config=ContentTreeToolConfig(),
        )

    mock_tree.invalidate_cache.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_reuses_cached_instance_then_invalidates():
    mock_tree = _make_mock_tree()
    with patch(
        "kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree
    ) as mock_cls:
        await content_tree(mode="tree", config=ContentTreeToolConfig())
        await content_tree(mode="tree", refresh=True, config=ContentTreeToolConfig())

    mock_cls.assert_called_once()
    mock_tree.invalidate_cache.assert_called_once_with()
    assert mock_tree.resolve_visible_file_paths_via_folders_async.await_count == 2


@pytest.mark.asyncio
async def test_default_metadata_filter_excludes_user_memory_folder(applied_filter):
    """With no config override, the admin default filter (excluding the
    system-generated user-memory folder) is what reaches the service calls."""
    mock_tree = _make_mock_tree()
    expected_filter = {
        "operator": "notContains",
        "path": ["folderIdPath"],
        "value": "user-memory",
    }
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        await content_tree(
            mode="tree",
            config=ContentTreeToolConfig(),
        )

    assert _walk_filter(mock_tree) == expected_filter
    assert applied_filter[-1] is None


@pytest.mark.asyncio
async def test_admin_configured_metadata_filter_flows_through_to_service_calls(
    identity,
    applied_filter,
):
    """Admins can override metadata_filter via ContentTreeToolConfig; the
    override (not the default) must reach the underlying ContentTree calls
    for tree, list, and search modes alike."""
    custom_filter = {"operator": "equals", "path": ["type"], "value": "pdf"}
    config = ContentTreeToolConfig(metadata_filter=custom_filter)

    mock_tree = _make_mock_tree()
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        identity.return_value = _make_settings(user_id="user-tree")
        await content_tree(mode="tree", config=config)
    assert _walk_filter(mock_tree) == custom_filter

    mock_tree = _make_mock_tree()
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        identity.return_value = _make_settings(user_id="user-list")
        await content_tree(mode="list", config=config)
    assert _walk_filter(mock_tree) == custom_filter

    mock_tree = _make_mock_tree()
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        identity.return_value = _make_settings(user_id="user-search")
        await content_tree(mode="search", query="a.pdf", config=config)
    assert _walk_filter(mock_tree) == custom_filter
    # Must match the walk's filter exactly, or the fuzzy search resolves a
    # second cache entry and silently pays for another whole walk.
    _, fuzzy_kwargs = mock_tree.search_visible_files_fuzzy_async.call_args
    assert fuzzy_kwargs["metadata_filter"] == _walk_filter(mock_tree)


_DEFAULT_CONTENT_TREE_FILTER = {
    "operator": "notContains",
    "path": ["folderIdPath"],
    "value": "user-memory",
}


@pytest.mark.asyncio
async def test_llm_metadata_filter_ands_default_admin_filter(applied_filter):
    mock_tree = _make_mock_tree()
    expected_llm = parse_uniqueql(UNIQUEQL_EQUALS_PDF).to_dict()
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        await content_tree(
            mode="list",
            metadata_filter=UNIQUEQL_EQUALS_PDF,
            config=ContentTreeToolConfig(),
        )

    assert _walk_filter(mock_tree) == _DEFAULT_CONTENT_TREE_FILTER
    assert applied_filter[-1] == expected_llm


@pytest.mark.asyncio
async def test_llm_metadata_filter_ands_admin_configured_filter(applied_filter):
    custom_filter = {"operator": "equals", "path": ["type"], "value": "pdf"}
    config = ContentTreeToolConfig(metadata_filter=custom_filter)
    expected_llm = parse_uniqueql(UNIQUEQL_EQUALS_PDF).to_dict()
    mock_tree = _make_mock_tree()
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        await content_tree(
            mode="tree",
            metadata_filter=UNIQUEQL_EQUALS_PDF,
            config=config,
        )

    assert _walk_filter(mock_tree) == custom_filter
    assert applied_filter[-1] == expected_llm


@pytest.mark.asyncio
async def test_invalid_uniqueql_returns_tool_error_without_walking():
    with patch("kb_mcp.tools.content_tree.tool.ContentTree") as mock_cls:
        result = await content_tree(
            mode="list",
            metadata_filter=UNIQUEQL_EQUALS_PDF_WRAPPED,
            config=ContentTreeToolConfig(),
        )

    assert result.is_error is True
    assert result.content[0].text == INVALID_METADATA_FILTER_MESSAGE  # type: ignore[union-attr]
    mock_cls.assert_not_called()


@pytest.mark.asyncio
async def test_list_empty_hits_with_llm_filter_append_retry_hint():
    mock_tree = _make_mock_tree(snapshot=FakeSnapshot(files=[]))
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="list",
            metadata_filter=UNIQUEQL_EQUALS_PDF,
            config=ContentTreeToolConfig(),
        )

    text = result.content[0].text  # type: ignore[union-attr]
    assert text.startswith("No visible files match.")
    assert METADATA_FILTER_EMPTY_RETRY_HINT in text


@pytest.mark.asyncio
async def test_tree_empty_hits_with_llm_filter_append_retry_hint():
    mock_tree = _make_mock_tree(snapshot=FakeSnapshot(files=[]))
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="tree",
            metadata_filter=UNIQUEQL_EQUALS_PDF,
            config=ContentTreeToolConfig(),
        )

    text = result.content[0].text  # type: ignore[union-attr]
    assert METADATA_FILTER_EMPTY_RETRY_HINT in text


@pytest.mark.asyncio
async def test_incomplete_empty_list_does_not_append_retry_hint():
    mock_tree = _make_mock_tree(snapshot=FakeSnapshot(files=[], complete=False))
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="list",
            metadata_filter=UNIQUEQL_EQUALS_PDF,
            config=ContentTreeToolConfig(),
        )

    text = result.content[0].text  # type: ignore[union-attr]
    assert "incomplete" in text.lower()
    assert METADATA_FILTER_EMPTY_RETRY_HINT not in text


@pytest.mark.asyncio
async def test_cache_miss_for_different_identity_constructs_new_instance(identity):
    with patch(
        "kb_mcp.tools.content_tree.tool.ContentTree",
        side_effect=lambda **kwargs: _make_mock_tree(),
    ) as mock_cls:
        identity.return_value = _make_settings(company_id="company-1", user_id="user-1")
        await content_tree(mode="tree", config=ContentTreeToolConfig())
        identity.return_value = _make_settings(company_id="company-2", user_id="user-2")
        await content_tree(mode="tree", config=ContentTreeToolConfig())

    assert mock_cls.call_count == 2


@pytest.mark.asyncio
async def test_identity_refusal_surfaces_as_tool_error(identity):
    identity.side_effect = ValueError("Refusing UNIQUE_AUTH_* env fallback")
    result = await content_tree(mode="tree", config=ContentTreeToolConfig())

    assert result.is_error is True
    assert "UNIQUE_AUTH_" in result.content[0].text  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_list_uses_frontend_deep_link_when_scope_known(monkeypatch):
    monkeypatch.setenv("UNIQUE_MCP_FRONTEND_BASE_URL", "https://example.unique.app")
    info = _make_content_info("c1")
    info.metadata = {"folderIdPath": "uniquepathid://scope_root/scope_leaf"}
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(files=[(info, PurePosixPath("Contracts/a.pdf"))])
    )
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(mode="list", config=ContentTreeToolConfig())

    text = result.content[0].text  # type: ignore[union-attr]
    assert (
        "[Contracts/a.pdf]"
        "(https://example.unique.app/knowledge-upload/scope_leaf?file=c1)" in text
    )


@pytest.mark.asyncio
async def test_list_strips_brackets_from_bracketed_folder_path():
    """``[ORG]/Alpha/Audit_Report_….pdf`` must emit a clean markdown link."""
    info = _make_content_info("cont_ioi3voailf7hr011zcp6b7eh")
    bracketed_folder = "[ORG]"
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(
            files=[
                (
                    info,
                    PurePosixPath(f"{bracketed_folder}/Alpha/Audit_Report_FY2023.pdf"),
                )
            ]
        )
    )
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(mode="list", config=ContentTreeToolConfig())

    text = result.content[0].text  # type: ignore[union-attr]
    assert text == (
        "[ORG/Alpha/Audit_Report_FY2023.pdf]"
        "(unique://content/cont_ioi3voailf7hr011zcp6b7eh) "
        "(content_id=cont_ioi3voailf7hr011zcp6b7eh)"
    )
    assert "[ORG]" not in text


@pytest.mark.asyncio
async def test_list_strips_no_folder_path_sentinel_keeps_unique_link():
    """Orphan rows must not leak ``_no_folder_path`` into the label."""
    info = _make_content_info("chat_orphan")
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(
            files=[
                (
                    info,
                    PurePosixPath(
                        "_no_folder_path/"
                        "Chat_1234567890123_Shareholder_Letter_H1_2024.pdf"
                    ),
                )
            ]
        )
    )
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(mode="list", config=ContentTreeToolConfig())

    text = result.content[0].text  # type: ignore[union-attr]
    assert "_no_folder_path" not in text
    assert (
        "[Chat_1234567890123_Shareholder_Letter_H1_2024.pdf]"
        "(unique://content/chat_orphan) (content_id=chat_orphan)" in text
    )


@pytest.mark.asyncio
async def test_search_strips_no_folder_path_sentinel_keeps_unique_link():
    mock_tree = _make_mock_tree()
    mock_tree.search_visible_files_fuzzy_async = AsyncMock(
        return_value=[
            _make_fuzzy_match(
                ["_no_folder_path", "Chat_orphan.pdf"],
                0.95,
                "c_orphan",
            )
        ]
    )
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="search",
            query="Chat_orphan",
            config=ContentTreeToolConfig(),
        )

    text = result.content[0].text  # type: ignore[union-attr]
    assert "_no_folder_path" not in text
    assert (
        "[Chat_orphan.pdf](unique://content/c_orphan) "
        "(score=0.95, content_id=c_orphan)" in text
    )


@pytest.mark.asyncio
async def test_list_orphan_with_scope_owner_keeps_deep_link(monkeypatch):
    monkeypatch.setenv("UNIQUE_MCP_FRONTEND_BASE_URL", "https://example.unique.app")
    info = _make_content_info("c_scope")
    info.metadata = None
    info.owner_id = "scope_leaf"
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(
            files=[(info, PurePosixPath("_no_folder_path/orphan.pdf"))]
        )
    )
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(mode="list", config=ContentTreeToolConfig())

    text = result.content[0].text  # type: ignore[union-attr]
    assert "_no_folder_path" not in text
    assert (
        "[orphan.pdf]"
        "(https://example.unique.app/knowledge-upload/scope_leaf?file=c_scope)" in text
    )
    assert "(content_id=c_scope)" in text


@pytest.mark.asyncio
async def test_tree_forwards_clamped_timeout_to_via_folders_api():
    mock_tree = _make_mock_tree()
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        await content_tree(mode="tree", timeout=300, config=ContentTreeToolConfig())

    _, kwargs = mock_tree.resolve_visible_file_paths_via_folders_async.call_args
    assert kwargs["timeout"] == 45.0
    assert kwargs["max_concurrent_directory_listings"] == 25


@pytest.mark.asyncio
async def test_tree_folders_only_hides_files_in_the_render():
    snapshot = FakeSnapshot(
        files=[(_make_content_info("f1"), PurePosixPath("Docs/a.pdf"))],
        folder_paths=[PurePosixPath("Docs")],
    )
    mock_tree = _make_mock_tree(snapshot=snapshot)
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="tree", folders_only=True, config=ContentTreeToolConfig()
        )

    text = result.content[0].text  # type: ignore[union-attr]
    assert "Docs" in text
    assert "a.pdf" not in text


@pytest.mark.asyncio
async def test_tree_folders_only_still_shows_folder_id():
    """folders_only only ever hides files — it must not also suppress the
    folder_id annotation (plan's "show ids regardless of folders_only")."""
    info = _make_content_info(
        "nda", metadata={"folderIdPath": "uniquepathid://scope_legal"}
    )
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(
            files=[(info, PurePosixPath("Legal/nda.pdf"))],
            folder_paths=[PurePosixPath("Legal")],
        )
    )
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="tree", folders_only=True, config=ContentTreeToolConfig()
        )

    text = result.content[0].text  # type: ignore[union-attr]
    assert "Legal (folder_id=scope_legal)" in text
    assert "nda.pdf" not in text


@pytest.mark.asyncio
async def test_tree_default_shows_files_in_the_render():
    snapshot = FakeSnapshot(
        files=[(_make_content_info("f1"), PurePosixPath("Docs/a.pdf"))]
    )
    mock_tree = _make_mock_tree(snapshot=snapshot)
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(mode="tree", config=ContentTreeToolConfig())

    text = result.content[0].text  # type: ignore[union-attr]
    assert "Docs" in text
    assert "a.pdf" in text


@pytest.mark.asyncio
async def test_tree_walks_one_level_past_the_rendered_max_depth():
    """A folder at exactly max_depth is only ever recorded via its parent's
    listing, never visited itself — so the walk must go one level deeper
    than what's rendered, or that boundary folder's own contents (and thus
    its folder_id) can never be discovered."""
    mock_tree = _make_mock_tree()
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        await content_tree(
            mode="tree",
            max_depth=2,
            config=ContentTreeToolConfig(),
        )

    _, kwargs = mock_tree.resolve_visible_file_paths_via_folders_async.call_args
    assert kwargs["max_depth"] == 3


@pytest.mark.asyncio
async def test_tree_unlimited_depth_still_walks_unlimited():
    mock_tree = _make_mock_tree()
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        await content_tree(mode="tree", config=ContentTreeToolConfig())

    _, kwargs = mock_tree.resolve_visible_file_paths_via_folders_async.call_args
    assert kwargs["max_depth"] is None


@pytest.mark.asyncio
async def test_tree_boundary_folder_gets_id_and_honest_summary_at_max_depth():
    """Simulates a real walk with max_depth=2 (render cutoff) but the +1
    fetch reaching one level further: ``Mid`` sits exactly at the render
    cutoff and has its own file plus a further subfolder. Without the extra
    walked level, ``Mid`` would show neither an id nor a "below" summary —
    indistinguishable from a genuinely empty folder."""
    info = _make_content_info(
        "b1", metadata={"folderIdPath": "uniquepathid://scope_top/scope_mid"}
    )
    snapshot = FakeSnapshot(
        files=[(info, PurePosixPath("Top/Mid/b1.txt"))],
        folder_paths=[PurePosixPath("Top"), PurePosixPath("Top/Mid/Deep")],
    )
    mock_tree = _make_mock_tree(snapshot=snapshot)
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="tree", max_depth=2, config=ContentTreeToolConfig()
        )

    text = result.content[0].text  # type: ignore[union-attr]
    assert "Mid (folder_id=scope_mid)" in text
    assert "dirs" in text and "files below" in text


@pytest.mark.asyncio
async def test_list_does_not_pass_max_depth_into_the_walk():
    mock_tree = _make_mock_tree()
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        await content_tree(
            mode="list",
            max_depth=1,
            config=ContentTreeToolConfig(),
        )

    _, kwargs = mock_tree.resolve_visible_file_paths_via_folders_async.call_args
    assert kwargs["max_depth"] is None


@pytest.mark.asyncio
async def test_incomplete_tree_tells_the_model_the_listing_is_partial():
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(
            files=[(_make_content_info("nda"), PurePosixPath("Legal/nda.pdf"))],
            complete=False,
        )
    )
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(mode="tree", config=ContentTreeToolConfig())

    text = result.content[0].text  # type: ignore[union-attr]
    assert text.startswith("This listing is incomplete.")
    assert "call content_tree again" in text
    assert "Legal" in text
    assert "nda.pdf" in text


@pytest.mark.asyncio
async def test_incomplete_search_does_not_wait_on_fuzzy_and_still_matches():
    info = _make_content_info("c1", key="annual_report.pdf")
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(
            files=[
                (info, PurePosixPath("Finance/annual_report.pdf")),
                (_make_content_info("c2", key="other.pdf"), PurePosixPath("other.pdf")),
            ],
            complete=False,
        )
    )
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="search",
            query="annual",
            config=ContentTreeToolConfig(),
        )

    mock_tree.search_visible_files_fuzzy_async.assert_not_called()
    text = result.content[0].text  # type: ignore[union-attr]
    assert text.startswith("This listing is incomplete.")
    assert "content_id=c1" in text
    assert "content_id=c2" not in text


@pytest.mark.parametrize(
    ("match_on", "case_sensitive", "query", "min_score", "expected_content_id"),
    [
        ("key", False, "Finance", 0.6, None),
        ("path", False, "annual", 0.6, "c1"),
        ("key", True, "Annual", 0.6, None),
        ("path", False, "finance", 0.6, "c1"),
        ("both", False, "annual", 1.1, None),
    ],
)
@pytest.mark.asyncio
async def test_incomplete_search_respects_match_options(
    match_on: MatchTarget,
    case_sensitive: bool,
    query: str,
    min_score: float,
    expected_content_id: str | None,
):
    info = _make_content_info("c1", key="annual_report.pdf")
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(
            files=[(info, PurePosixPath("Finance/annual_report.pdf"))],
            complete=False,
        )
    )
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="search",
            query=query,
            min_score=min_score,
            match_on=match_on,
            case_sensitive=case_sensitive,
            config=ContentTreeToolConfig(),
        )

    text = result.content[0].text  # type: ignore[union-attr]
    if expected_content_id is None:
        assert "No matching files found." in text
    else:
        assert f"content_id={expected_content_id}" in text


@pytest.mark.asyncio
async def test_tree_shows_folder_id_for_a_folder_with_a_direct_file():
    info = _make_content_info(
        "nda", metadata={"folderIdPath": "uniquepathid://scope_legal"}
    )
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(files=[(info, PurePosixPath("Legal/nda.pdf"))])
    )
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(mode="tree", config=ContentTreeToolConfig())

    text = result.content[0].text  # type: ignore[union-attr]
    assert "Legal (folder_id=scope_legal)" in text
    assert "nda.pdf (folder_id" not in text


@pytest.mark.asyncio
async def test_tree_shows_folder_id_derived_from_a_nested_file_only():
    """``Archive`` itself has no direct file — its id must still be derivable
    from a file two levels down, via the full ancestor chain in that file's
    ``folderIdPath``."""
    info = _make_content_info(
        "report",
        metadata={"folderIdPath": "uniquepathid://scope_archive/scope_old"},
    )
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(files=[(info, PurePosixPath("Archive/Old/report.pdf"))])
    )
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(mode="tree", config=ContentTreeToolConfig())

    text = result.content[0].text  # type: ignore[union-attr]
    assert "Archive (folder_id=scope_archive)" in text
    assert "Old (folder_id=scope_old)" in text


@pytest.mark.asyncio
async def test_tree_folder_ids_align_from_leaf_when_folder_id_path_has_a_hidden_root():
    """``folderIdPath`` can carry a hidden ancestor above the walk's own
    root; ids must still align via the guaranteed leaf match, not position 0."""
    info = _make_content_info(
        "report",
        metadata={
            "folderIdPath": "uniquepathid://scope_hidden_root/scope_archive/scope_old"
        },
    )
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(files=[(info, PurePosixPath("Archive/Old/report.pdf"))])
    )
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(mode="tree", config=ContentTreeToolConfig())

    text = result.content[0].text  # type: ignore[union-attr]
    assert "Archive (folder_id=scope_archive)" in text
    assert "Old (folder_id=scope_old)" in text
    assert "scope_hidden_root" not in text


@pytest.mark.asyncio
async def test_tree_folder_with_nothing_beneath_renders_without_id():
    """An empty folder (no files anywhere under it) has no derivable id —
    its line renders with no ``(folder_id=...)`` suffix, and doesn't error."""
    info = _make_content_info(
        "nda", metadata={"folderIdPath": "uniquepathid://scope_legal"}
    )
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(
            files=[(info, PurePosixPath("Legal/nda.pdf"))],
            folder_paths=[PurePosixPath("Empty")],
        )
    )
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(mode="tree", config=ContentTreeToolConfig())

    text = result.content[0].text  # type: ignore[union-attr]
    assert "Empty" in text
    assert "Empty (folder_id" not in text


@pytest.mark.asyncio
async def test_resolvable_folder_path_roots_the_walk_instead_of_filtering():
    """The whole point: scope the walk, do not walk everything and filter after."""
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(
            files=[(_make_content_info("c1"), PurePosixPath("a.pdf"))]
        )
    )
    with (
        patch(
            "kb_mcp.tools.content_tree.tool.unique_sdk.Folder."
            "resolve_scope_id_from_folder_path_async",
            AsyncMock(return_value="scope_target"),
        ),
        patch(
            "kb_mcp.tools.content_tree.tool.ScopedContentTree", return_value=mock_tree
        ) as scoped_cls,
        patch("kb_mcp.tools.content_tree.tool.ContentTree") as unscoped_cls,
    ):
        result = await content_tree(
            mode="list", folder_path="Contracts/2024", config=ContentTreeToolConfig()
        )

    assert result.is_error is not True
    scoped_cls.assert_called_once()
    assert scoped_cls.call_args.kwargs["root_scope_ids"] == ("scope_target",)
    unscoped_cls.assert_not_called()


@pytest.mark.asyncio
async def test_unreadable_scope_id_is_an_error_not_an_empty_folder():
    with (
        patch(
            "kb_mcp.tools.content_tree.tool.unique_sdk.Folder.get_info_async",
            AsyncMock(side_effect=ValueError("nope")),
        ),
        patch("kb_mcp.tools.content_tree.tool.ContentTree") as unscoped_cls,
    ):
        result = await content_tree(
            mode="list", folder_path="scope_missing", config=ContentTreeToolConfig()
        )

    assert result.is_error is True
    assert "scope_missing" in result.content[0].text  # type: ignore[union-attr]
    unscoped_cls.assert_not_called()


@pytest.mark.asyncio
async def test_tree_mode_caps_files_and_says_it_truncated():
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(
            files=[
                (_make_content_info(f"c{i}"), PurePosixPath(f"f{i}.pdf"))
                for i in range(5)
            ]
        )
    )
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="tree", limit=2, config=ContentTreeToolConfig()
        )

    text = result.content[0].text  # type: ignore[union-attr]
    assert "first 2 of 5" in text
    assert "folders_only=true" not in text


@pytest.mark.asyncio
async def test_tree_limit_caps_folders_too_by_default():
    """A caller-supplied `limit` sizes the folder cap too, so a small ask for
    files doesn't come back wrapped in a near-unbounded folder tree."""
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(folder_paths=[PurePosixPath(f"d{i}") for i in range(5)])
    )
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="tree", limit=2, config=ContentTreeToolConfig()
        )

    text = result.content[0].text  # type: ignore[union-attr]
    assert "first 2 of 5 folders" in text


@pytest.mark.asyncio
async def test_tree_folders_only_limit_caps_folders():
    """Under folders_only, `limit` has no files to cap, so it caps folders."""
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(folder_paths=[PurePosixPath(f"d{i}") for i in range(5)])
    )
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="tree", folders_only=True, limit=2, config=ContentTreeToolConfig()
        )

    text = result.content[0].text  # type: ignore[union-attr]
    assert "first 2 of 5 folders" in text


@pytest.mark.asyncio
async def test_tree_mode_caps_folders_with_no_files_present():
    """folder_paths lists every visited directory regardless of `limit`, so it
    needs its own cap and its own notice, even with zero files to cap."""
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(folder_paths=[PurePosixPath(f"d{i}") for i in range(5)])
    )
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="tree",
            config=ContentTreeToolConfig(default_tree_limit=2),
        )

    text = result.content[0].text  # type: ignore[union-attr]
    assert "first 2 of 5 folders" in text
    assert "Raise `limit` or narrow `folder_path`" in text


@pytest.mark.asyncio
async def test_tree_folders_only_still_reports_folder_truncation():
    """Unlike the file cap, the folder cap keeps biting under folders_only=true:
    that mode exists to show folder structure, so it must still be capped."""
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(folder_paths=[PurePosixPath(f"d{i}") for i in range(5)])
    )
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="tree",
            folders_only=True,
            config=ContentTreeToolConfig(default_tree_limit=2),
        )

    text = result.content[0].text  # type: ignore[union-attr]
    assert "first 2 of 5 folders" in text


@pytest.mark.asyncio
async def test_tree_folders_only_files_do_not_resurrect_a_capped_folder():
    """Under folders_only, a file's own path must not pull a sliced-out
    folder back into the render: files are dropped there, not capped, since
    folder_paths already lists every folder, files or not."""
    snapshot = FakeSnapshot(
        files=[(_make_content_info("f0"), PurePosixPath("d4/f0.pdf"))],
        folder_paths=[PurePosixPath(f"d{i}") for i in range(5)],
    )
    mock_tree = _make_mock_tree(snapshot=snapshot)
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="tree",
            folders_only=True,
            config=ContentTreeToolConfig(default_tree_limit=2),
        )

    text = result.content[0].text  # type: ignore[union-attr]
    assert "first 2 of 5 folders" in text
    assert "d4" not in text


@pytest.mark.asyncio
async def test_tree_folder_notice_counts_dirs_a_surviving_file_still_renders():
    """A folder sliced out of folder_paths still renders if one of its files
    survives the file cap, so the notice must count it as shown, not hidden."""
    snapshot = FakeSnapshot(
        files=[(_make_content_info("c0"), PurePosixPath("d4/f.pdf"))],
        folder_paths=[PurePosixPath(f"d{i}") for i in range(5)],
    )
    mock_tree = _make_mock_tree(snapshot=snapshot)
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="tree",
            config=ContentTreeToolConfig(default_tree_limit=2),
        )

    text = result.content[0].text  # type: ignore[union-attr]
    assert "d4" in text
    assert "first 3 of 5 folders" in text


@pytest.mark.asyncio
async def test_search_does_not_filter_files_it_then_discards(applied_filter):
    """Search re-derives its hits from the fuzzy scorer and never reads the
    snapshot's files, so filtering them is a full pass over the corpus."""
    mock_tree = _make_mock_tree()
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        await content_tree(
            mode="search",
            query="a.pdf",
            metadata_filter=UNIQUEQL_EQUALS_PDF,
            config=ContentTreeToolConfig(),
        )

    assert applied_filter[-1] is None
    _, fuzzy_kwargs = mock_tree.search_visible_files_fuzzy_async.call_args
    assert fuzzy_kwargs["metadata_filter"] == _walk_filter(mock_tree)


_PDF_ONLY_FILTER = {
    "operator": "equals",
    "path": ["mimeType"],
    "value": "application/pdf",
}


def _real_content(content_id: str, key: str, mime_type: str) -> ContentInfo:
    """A real ContentInfo — a MagicMock dumps to an empty record, which makes
    every UniqueQL filter a silent no-op and the assertion meaningless."""
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return ContentInfo(
        id=content_id,
        object="content",
        key=key,
        byteSize=1,
        mimeType=mime_type,
        ownerId="scope_a",
        createdAt=now,
        updatedAt=now,
    )


def _real_fuzzy_match(info: ContentInfo, score: float):
    match = MagicMock()
    match.path_segments = [info.key]
    match.score = score
    match.content_info = info
    return match


@pytest.mark.asyncio
async def test_search_drops_fuzzy_hits_the_llm_filter_excludes():
    """The fast path filters the scorer's hits, not the snapshot."""
    pdf = _real_content("c_pdf", "report.pdf", "application/pdf")
    txt = _real_content("c_txt", "report.txt", "text/plain")
    mock_tree = _make_mock_tree()
    mock_tree.search_visible_files_fuzzy_async = AsyncMock(
        return_value=[_real_fuzzy_match(pdf, 0.9), _real_fuzzy_match(txt, 0.9)]
    )
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="search",
            query="report",
            metadata_filter=_PDF_ONLY_FILTER,
            config=ContentTreeToolConfig(),
        )

    text = result.content[0].text  # type: ignore[union-attr]
    assert "c_pdf" in text
    assert "c_txt" not in text


@pytest.mark.asyncio
async def test_incomplete_search_still_applies_the_llm_filter():
    """The fallback branch is the only one reading snapshot.files, and search
    resolves that snapshot unfiltered — so it has to filter its own rows."""
    pdf = _real_content("c_pdf", "report.pdf", "application/pdf")
    txt = _real_content("c_txt", "report.txt", "text/plain")
    snapshot = FakeSnapshot(
        files=[(pdf, PurePosixPath("report.pdf")), (txt, PurePosixPath("report.txt"))],
        complete=False,
    )
    mock_tree = _make_mock_tree(snapshot=snapshot)
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="search",
            query="report",
            metadata_filter=_PDF_ONLY_FILTER,
            config=ContentTreeToolConfig(),
        )

    text = result.content[0].text  # type: ignore[union-attr]
    assert "c_pdf" in text
    assert "c_txt" not in text


@pytest.mark.asyncio
async def test_search_mode_reports_limit_reached_without_a_false_total():
    """The SDK-bounded fast path only ever returns up to `limit`, so it can
    never claim an exact total: the notice must say "may be more", not a
    number it doesn't actually know."""
    matches = [
        _real_fuzzy_match(_real_content(f"c{i}", f"f{i}.pdf", "application/pdf"), 0.9)
        for i in range(3)
    ]
    mock_tree = _make_mock_tree()
    mock_tree.search_visible_files_fuzzy_async = AsyncMock(return_value=matches)
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="search", query="f", limit=3, config=ContentTreeToolConfig()
        )

    text = result.content[0].text  # type: ignore[union-attr]
    assert "Showing 3 matches. Raise `limit` to see more." in text
    assert " of " not in text


@pytest.mark.asyncio
async def test_search_mode_below_limit_reports_nothing():
    """Fewer matches than `limit` means that's genuinely everything: no
    notice, since there is nothing more to raise `limit` for."""
    matches = [_real_fuzzy_match(_real_content("c0", "f0.pdf", "application/pdf"), 0.9)]
    mock_tree = _make_mock_tree()
    mock_tree.search_visible_files_fuzzy_async = AsyncMock(return_value=matches)
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="search", query="f", limit=3, config=ContentTreeToolConfig()
        )

    text = result.content[0].text  # type: ignore[union-attr]
    assert "Raise `limit`" not in text


@pytest.mark.asyncio
async def test_tree_folders_only_never_reports_truncation():
    """folders_only renders no files, so the cap cannot bite and claiming it did
    would send the model chasing a limit that changes nothing."""
    snapshot = FakeSnapshot(
        files=[
            (_make_content_info(f"f{i}"), PurePosixPath(f"Docs/f{i}.pdf"))
            for i in range(5)
        ],
        folder_paths=[PurePosixPath("Docs")],
    )
    mock_tree = _make_mock_tree(snapshot=snapshot)
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="tree", folders_only=True, limit=2, config=ContentTreeToolConfig()
        )

    text = result.content[0].text  # type: ignore[union-attr]
    assert "Showing the first" not in text


def _bracketed_folder_snapshot() -> FakeSnapshot:
    """A folder whose stored name carries brackets, e.g. ``[ORG]``."""
    return FakeSnapshot(
        files=[
            (_make_content_info("c1"), PurePosixPath("[ORG]/Alpha/a.pdf")),
            (_make_content_info("c2"), PurePosixPath("[ORG]/Beta/b.pdf")),
            (_make_content_info("c3"), PurePosixPath("Gamma/c.pdf")),
        ]
    )


@pytest.mark.asyncio
async def test_search_scopes_to_a_bracket_stripped_folder_path():
    """An [ORG] folder renders as ORG, so ORG/Alpha cannot resolve to a scope id
    and search falls back to matching the prefix-filtered rows. It must still
    scope, and must not reach outside the folder."""
    mock_tree = _make_mock_tree(snapshot=_bracketed_folder_snapshot())
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="search",
            query="a.pdf",
            folder_path="ORG/Alpha",
            config=ContentTreeToolConfig(),
        )

    assert result.is_error is not True
    text = result.content[0].text  # type: ignore[union-attr]
    assert "content_id=c1" in text
    assert "content_id=c2" not in text
    assert "content_id=c3" not in text


@pytest.mark.asyncio
async def test_tree_scopes_to_a_bracket_stripped_folder_path():
    mock_tree = _make_mock_tree(snapshot=_bracketed_folder_snapshot())
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="tree", folder_path="ORG/Alpha", config=ContentTreeToolConfig()
        )

    assert result.is_error is not True
    text = result.content[0].text  # type: ignore[union-attr]
    assert "a.pdf" in text
    assert "b.pdf" not in text
    assert "c.pdf" not in text
