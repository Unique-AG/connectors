"""Shared test fixtures for kb-mcp."""

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from unique_toolkit.content.schemas import ContentChunk, ContentReference

from kb_mcp.common.references import REFERENCE_META_KEY
from kb_mcp.settings import Settings, get_settings

# Fixed, committed test env — never the developer's real .env. Set as real
# process env vars too (not just the dotenv override below) so tests that
# construct Settings(_env_file=None) directly still get these defaults.
# Tests that care about a specific value (frontend_base_url, storage mode,
# ...) override it via monkeypatch.setenv + get_settings.cache_clear(), or
# patch get_settings directly at the call site.
_TEST_ENV_FILE = Path(__file__).parent.parent / "test.env"
_DEFAULT_TEST_ENV = {
    "ZITADEL_BASE_URL": "https://id.test.unique.app",
    "ZITADEL_CLIENT_ID": "test-client-id",
    "ZITADEL_JWT_SIGNING_KEY": "test-jwt-signing-key",
    "ALLOW_EPHEMERAL_OAUTH_STORAGE": "true",
}


@pytest.fixture(autouse=True)
def _reset_settings_cache(monkeypatch):
    # A real .env (e.g. a live DATABASE_URL added for manual Postgres
    # testing) must never change what Settings() resolves to in a test.
    monkeypatch.setitem(Settings.model_config, "env_file", _TEST_ENV_FILE)
    for key, value in _DEFAULT_TEST_ENV.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


type CallOnWire = Callable[[Any, dict[str, Any]], Awaitable[dict[str, Any]]]


@pytest.fixture
def call_on_wire() -> CallOnWire:
    """Call a tool through a FastMCP client and return the CallToolResult as
    the JSON a client receives, so ``_meta`` is checked as sent."""

    async def call(tool: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        mcp = FastMCP("kb-mcp-test")
        mcp.add_tool(tool)
        async with Client(mcp) as client:
            result = await client.call_tool_mcp(tool.__fastmcp__.name, arguments)
        return result.model_dump(mode="json", by_alias=True, exclude_none=True)

    return call


def unique_ai_source(item: dict[str, Any]) -> tuple[ContentChunk, ContentReference]:
    """Read a content item the way Unique AI does: the reference under
    ``unique.app/reference``, the chunk from the rest of ``_meta``."""
    meta = item["_meta"]
    reference = ContentReference.model_validate(meta[REFERENCE_META_KEY])
    chunk = ContentChunk.model_validate(
        {key: value for key, value in meta.items() if key != REFERENCE_META_KEY}
    )
    return chunk, reference
