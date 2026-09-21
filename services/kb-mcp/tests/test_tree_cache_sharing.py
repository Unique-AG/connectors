"""content_tree and content_metadata are different views over one walk, so
scoping both to the same folder must reuse one cached ContentTree."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from kb_mcp.common import tree_cache as ct_cache
from kb_mcp.tools.content_metadata import ContentMetadataToolConfig, content_metadata
from kb_mcp.tools.content_tree import ContentTreeToolConfig, content_tree

pytestmark = [pytest.mark.ai, pytest.mark.asyncio]

SCOPE = "scope_docs"


def _settings():
    s = MagicMock()
    s.authcontext.get_confidential_company_id.return_value = "company-1"
    s.authcontext.get_confidential_user_id.return_value = "user-1"
    s.authcontext.company_id = SecretStr("company-1")
    s.authcontext.user_id = SecretStr("user-1")
    return s


@pytest.fixture(autouse=True)
def _shared_cache():
    ct_cache._tree_cache = None
    yield
    ct_cache._tree_cache = None


@pytest.fixture(autouse=True)
def _identity(monkeypatch):
    for module in (
        "kb_mcp.tools.content_tree.tool",
        "kb_mcp.tools.content_metadata.tool",
    ):
        monkeypatch.setattr(
            f"{module}.get_unique_settings_async", AsyncMock(return_value=_settings())
        )
        monkeypatch.setattr(
            f"{module}.unique_sdk.Folder.get_info_async",
            AsyncMock(return_value={"id": SCOPE}),
        )


def _tree_stub():
    snapshot = MagicMock(files=[], folder_paths=[], complete=True)
    tree = MagicMock()
    tree.metadata_filter = None
    tree.resolve_visible_file_paths_via_folders_async = AsyncMock(return_value=snapshot)
    return tree


async def test_both_tools_scoped_to_one_folder_share_a_cached_tree():
    """The cache key carried a bare str for one tool and a 1-tuple for the
    other, so the same folder hashed to two entries and the second tool paid
    for a whole second walk."""
    scoped = MagicMock(return_value=_tree_stub())
    with (
        patch("kb_mcp.tools.content_tree.tool.ScopedContentTree", scoped),
        patch("kb_mcp.tools.content_metadata.tool.ScopedContentTree", scoped),
    ):
        await content_tree(
            mode="list", folder_path=SCOPE, config=ContentTreeToolConfig()
        )
        await content_metadata(folder_ids=[SCOPE], config=ContentMetadataToolConfig())

    assert scoped.call_count == 1, (
        f"expected one shared ContentTree, built {scoped.call_count}"
    )


async def test_the_two_tools_agree_on_the_cache_key_for_one_folder():
    """Pins the shape itself, so a future edit to either key is caught here
    rather than as a silent extra walk in production."""
    keys: list[tuple[object, ...]] = []
    real = ct_cache.get_tree_cache

    def _spy(settings):
        cache = real(settings)
        original = cache.get_or_fetch

        async def _capture(key, factory):
            keys.append(key)
            return await original(key, factory)

        cache.get_or_fetch = _capture
        return cache

    scoped = MagicMock(return_value=_tree_stub())
    with (
        patch("kb_mcp.tools.content_tree.tool.get_tree_cache", _spy),
        patch("kb_mcp.tools.content_metadata.tool.get_tree_cache", _spy),
        patch("kb_mcp.tools.content_tree.tool.ScopedContentTree", scoped),
        patch("kb_mcp.tools.content_metadata.tool.ScopedContentTree", scoped),
    ):
        await content_tree(
            mode="list", folder_path=SCOPE, config=ContentTreeToolConfig()
        )
        await content_metadata(folder_ids=[SCOPE], config=ContentMetadataToolConfig())

    assert keys, "no cache lookup was made"
    assert len(set(keys)) == 1, f"tools disagreed on the key: {set(keys)!r}"
