"""Tests for the content_tree tool — mode dispatch, validation, cache, filtering."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.tools import ToolResult
from pydantic import SecretStr
from unique_toolkit.experimental.components.content_tree.schemas import (
    MatchTarget as ServiceMatchTarget,
)

from kb_mcp.tools.content_tree import (
    ContentTreeToolConfig,
    MatchTarget,
    content_tree,
)

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


def _make_content_info(content_id: str):
    info = MagicMock()
    info.id = content_id
    info.metadata = None
    info.owner_id = "user_123"
    return info


def _make_fuzzy_match(path_segments: list[str], score: float, content_id: str):
    match = MagicMock()
    match.path_segments = path_segments
    match.score = score
    match.content_info = _make_content_info(content_id)
    return match


def _make_mock_tree():
    tree = MagicMock()
    tree.render_visible_tree_async = AsyncMock(return_value="tree output")
    tree.resolve_visible_file_paths_async = AsyncMock(return_value=[])
    tree.search_visible_files_fuzzy_async = AsyncMock(return_value=[])
    return tree


@pytest.fixture(autouse=True)
def _reset_cache():
    import kb_mcp.tools.content_tree.tool as ct_module

    ct_module._tree_cache = None
    yield
    ct_module._tree_cache = None


def test_match_target_matches_service_definition():
    assert set(MatchTarget.__args__) == set(ServiceMatchTarget.__args__)


def _make_dispatch_probe_tree():
    """A tree whose three view methods return distinguishable output, so a
    test can prove the right view was returned without asserting which
    method got called."""
    tree = MagicMock()
    tree.render_visible_tree_async = AsyncMock(return_value="TREE VIEW")
    tree.resolve_visible_file_paths_async = AsyncMock(
        return_value=[(_make_content_info("list-result"), ["LIST", "VIEW"])]
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
    assert text == "TREE VIEW"
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
async def test_folder_path_prefix_filter_is_case_sensitive_exact_match():
    mock_tree = _make_mock_tree()
    mock_tree.resolve_visible_file_paths_async = AsyncMock(
        return_value=[
            (_make_content_info("c1"), ["Contracts", "2024", "a.pdf"]),
            (_make_content_info("c2"), ["contracts", "2024", "b.pdf"]),
            (_make_content_info("c3"), ["Other", "c.pdf"]),
        ]
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
    mock_tree = _make_mock_tree()
    mock_tree.resolve_visible_file_paths_async = AsyncMock(
        return_value=[
            (
                _make_content_info("c1"),
                [sm_folder, "AlpenSys", "a.pdf"],
            ),
            (
                _make_content_info("c2"),
                [sm_folder, "Other", "b.pdf"],
            ),
            (_make_content_info("c3"), ["Contracts", "c.pdf"]),
        ]
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
    rows = [(_make_content_info(f"c{i}"), [f"file{i}.pdf"]) for i in range(5)]
    mock_tree = _make_mock_tree()
    mock_tree.resolve_visible_file_paths_async = AsyncMock(return_value=rows)
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
    assert mock_tree.render_visible_tree_async.await_count == 2


def test_cache_settings_default_and_env_override(monkeypatch):
    from kb_mcp.settings import get_settings

    assert get_settings().content_tree_cache_max_entries == 128
    assert get_settings().content_tree_cache_ttl_seconds == 1800

    monkeypatch.setenv("KB_SEARCH_CONTENT_TREE_CACHE_MAX_ENTRIES", "999")
    get_settings.cache_clear()
    assert get_settings().content_tree_cache_max_entries == 999

    monkeypatch.setenv("KB_SEARCH_CONTENT_TREE_CACHE_TTL_SECONDS", "60")
    get_settings.cache_clear()
    assert get_settings().content_tree_cache_ttl_seconds == 60


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
    mock_tree.render_visible_tree_async.assert_called_once()
    assert isinstance(result, ToolResult)
    assert result.content[0].text == "tree output"  # type: ignore[union-attr]


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
    assert mock_tree.render_visible_tree_async.await_count == 2


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

    _, kwargs = mock_tree.render_visible_tree_async.call_args
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
    _, kwargs = mock_tree.render_visible_tree_async.call_args
    assert kwargs["metadata_filter"] == custom_filter

    mock_tree = _make_mock_tree()
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        identity.return_value = _make_settings(user_id="user-list")
        await content_tree(mode="list", config=config)
    _, kwargs = mock_tree.resolve_visible_file_paths_async.call_args
    assert kwargs["metadata_filter"] == custom_filter

    mock_tree = _make_mock_tree()
    with patch("kb_mcp.tools.content_tree.tool.ContentTree", return_value=mock_tree):
        identity.return_value = _make_settings(user_id="user-search")
        await content_tree(mode="search", query="a.pdf", config=config)
    _, kwargs = mock_tree.search_visible_files_fuzzy_async.call_args
    assert kwargs["metadata_filter"] == custom_filter


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
    mock_tree = _make_mock_tree()
    mock_tree.resolve_visible_file_paths_async = AsyncMock(
        return_value=[(info, ["Contracts", "a.pdf"])]
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
    mock_tree = _make_mock_tree()
    mock_tree.resolve_visible_file_paths_async = AsyncMock(
        return_value=[
            (
                info,
                [sm_folder, "AlpenSys", "Audit_Report_AlpenSys_FY2023.pdf"],
            )
        ]
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
    mock_tree = _make_mock_tree()
    mock_tree.resolve_visible_file_paths_async = AsyncMock(
        return_value=[
            (
                info,
                [
                    "_no_folder_path",
                    "Chat_1780557337141_AlpenSys_Shareholder_Letter_H1_2024.pdf",
                ],
            )
        ]
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
    mock_tree = _make_mock_tree()
    mock_tree.resolve_visible_file_paths_async = AsyncMock(
        return_value=[(info, ["_no_folder_path", "orphan.pdf"])]
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
