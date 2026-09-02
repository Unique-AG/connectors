"""Tests for the content_tree tool — mode dispatch, validation, cache, filtering."""

import asyncio
import gc
import logging
import weakref
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.server.providers.filesystem_discovery import import_module_from_file
from fastmcp.tools import ToolResult
from pydantic import SecretStr
from unique_toolkit.experimental.components.content_tree.schemas import (
    FolderWalkSnapshot,
)
from unique_toolkit.experimental.components.content_tree.schemas import (
    MatchTarget as ServiceMatchTarget,
)
from unique_toolkit.experimental.resources.feature_flags._ttl_cache import (
    AsyncTTLCache,
)

from kb_mcp.settings import get_settings
from kb_mcp.tools.content_tree import (
    ContentTreeToolConfig,
    MatchTarget,
    content_tree,
)
from kb_mcp.tools.content_tree import cache as ct_cache
from kb_mcp.tools.content_tree import tool as ct_module
from kb_mcp.tools.content_tree.cache import expire_idle_trees
from kb_mcp.tools.content_tree.tool import clamped_content_tree_timeout

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
    tree.resolve_visible_file_paths_via_folders_async = AsyncMock(
        return_value=snapshot or FakeSnapshot()
    )
    tree.search_visible_files_fuzzy_async = AsyncMock(return_value=[])
    return tree


@pytest.fixture(autouse=True)
def _reset_cache():
    ct_cache._tree_cache = None
    yield
    ct_cache._tree_cache = None


def test_match_target_matches_service_definition():
    assert set(MatchTarget.__args__) == set(ServiceMatchTarget.__args__)


def _make_dispatch_probe_tree():
    """A tree whose three views return distinguishable output."""
    tree = MagicMock()
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
async def test_search_mode_with_folder_path_errors():
    with patch("kb_mcp.tools.content_tree.tool.ContentTree") as mock_cls:
        result = await content_tree(
            mode="search",
            query="a.pdf",
            folder_path="Contracts",
            config=ContentTreeToolConfig(),
        )

    assert isinstance(result, ToolResult)
    assert result.is_error is True
    text = result.content[0].text  # type: ignore[union-attr]
    assert "folder_path" in text
    assert "mode='list'" in text
    mock_cls.assert_not_called()


@pytest.mark.asyncio
async def test_tree_mode_with_folder_path_errors():
    with patch("kb_mcp.tools.content_tree.tool.ContentTree") as mock_cls:
        result = await content_tree(
            mode="tree", folder_path="Contracts", config=ContentTreeToolConfig()
        )

    assert isinstance(result, ToolResult)
    assert result.is_error is True
    mock_cls.assert_not_called()


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
    """Filters use display paths so ``SM/AlpenSys`` matches ``[SM]/AlpenSys``."""
    sm_folder = "[" + "SM" + "]"
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(
            files=[
                (
                    _make_content_info("c1"),
                    PurePosixPath(f"{sm_folder}/AlpenSys/a.pdf"),
                ),
                (
                    _make_content_info("c2"),
                    PurePosixPath(f"{sm_folder}/Other/b.pdf"),
                ),
                (_make_content_info("c3"), PurePosixPath("Contracts/c.pdf")),
            ]
        )
    )
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(
            mode="list",
            folder_path="SM/AlpenSys",
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
    assert len(text.splitlines()) == 2


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
    assert get_settings().content_tree_cache_max_entries == 24
    assert get_settings().content_tree_cache_ttl_seconds == 600

    monkeypatch.setenv("KB_MCP_CONTENT_TREE_CACHE_MAX_ENTRIES", "999")
    get_settings.cache_clear()
    assert get_settings().content_tree_cache_max_entries == 999

    monkeypatch.setenv("KB_MCP_CONTENT_TREE_CACHE_TTL_SECONDS", "60")
    get_settings.cache_clear()
    assert get_settings().content_tree_cache_ttl_seconds == 60


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
async def test_default_metadata_filter_excludes_user_memory_folder():
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

    _, kwargs = mock_tree.resolve_visible_file_paths_via_folders_async.call_args
    assert kwargs["metadata_filter"] == expected_filter


@pytest.mark.asyncio
async def test_admin_configured_metadata_filter_flows_through_to_service_calls(
    identity,
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
    _, kwargs = mock_tree.resolve_visible_file_paths_via_folders_async.call_args
    assert kwargs["metadata_filter"] == custom_filter

    mock_tree = _make_mock_tree()
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        identity.return_value = _make_settings(user_id="user-list")
        await content_tree(mode="list", config=config)
    _, kwargs = mock_tree.resolve_visible_file_paths_via_folders_async.call_args
    assert kwargs["metadata_filter"] == custom_filter

    mock_tree = _make_mock_tree()
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        identity.return_value = _make_settings(user_id="user-search")
        await content_tree(mode="search", query="a.pdf", config=config)
    _, kwargs = mock_tree.resolve_visible_file_paths_via_folders_async.call_args
    assert kwargs["metadata_filter"] == custom_filter
    _, fuzzy_kwargs = mock_tree.search_visible_files_fuzzy_async.call_args
    assert fuzzy_kwargs["metadata_filter"] == custom_filter


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
async def test_list_strips_brackets_from_sm_folder_path():
    """``[SM]/AlpenSys/Audit_Report_….pdf`` must emit a clean markdown link."""
    info = _make_content_info("cont_ioi3voailf7hr011zcp6b7eh")
    sm_folder = "[" + "SM" + "]"
    mock_tree = _make_mock_tree(
        snapshot=FakeSnapshot(
            files=[
                (
                    info,
                    PurePosixPath(
                        f"{sm_folder}/AlpenSys/Audit_Report_AlpenSys_FY2023.pdf"
                    ),
                )
            ]
        )
    )
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        result = await content_tree(mode="list", config=ContentTreeToolConfig())

    text = result.content[0].text  # type: ignore[union-attr]
    assert text == (
        "[SM/AlpenSys/Audit_Report_AlpenSys_FY2023.pdf]"
        "(unique://content/cont_ioi3voailf7hr011zcp6b7eh) "
        "(content_id=cont_ioi3voailf7hr011zcp6b7eh)"
    )
    assert "[" + "SM" + "]" not in text


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
                        "Chat_1780557337141_AlpenSys_Shareholder_Letter_H1_2024.pdf"
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
        "[Chat_1780557337141_AlpenSys_Shareholder_Letter_H1_2024.pdf]"
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


def test_clamped_timeout_uses_default_then_ceiling(monkeypatch):
    get_settings.cache_clear()
    settings = get_settings()
    assert clamped_content_tree_timeout(None, settings) == 30.0
    assert clamped_content_tree_timeout(12.0, settings) == 12.0
    assert clamped_content_tree_timeout(300.0, settings) == 45.0
    assert clamped_content_tree_timeout(-1.0, settings) == 0.0

    monkeypatch.setenv("KB_MCP_CONTENT_TREE_TIMEOUT_SECONDS", "20")
    monkeypatch.setenv("KB_MCP_CONTENT_TREE_MAX_TIMEOUT_SECONDS", "25")
    get_settings.cache_clear()
    settings = get_settings()
    assert clamped_content_tree_timeout(None, settings) == 20.0
    assert clamped_content_tree_timeout(40.0, settings) == 25.0


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
        files=[(_make_content_info("f1"), PurePosixPath("Docs/a.pdf"))]
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
        snapshot=FakeSnapshot(files=[(info, PurePosixPath("Legal/nda.pdf"))])
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
