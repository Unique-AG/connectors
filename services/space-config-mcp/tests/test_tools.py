"""Tool smoke tests covering Unique AI, Conduct, and Magic Table space types.

Each test class targets one space kind and verifies the round-trip through the
tool → context → upstream chain without hitting a live API.
"""

import json
from typing import cast
from unittest.mock import AsyncMock
from unittest.mock import patch

from fastmcp import FastMCP
from fastmcp.client import Client
from fastmcp.client.client import CallToolResult
import mcp_types
import pytest
import unique_sdk

from tests.offline_server import build_server

# ---------------------------------------------------------------------------
# Factory helpers for unique_sdk objects
# ---------------------------------------------------------------------------


def _space(space_id: str = "assistant_testspace", name: str = "Test Space") -> unique_sdk.Space:
    s = unique_sdk.Space(user_id="user-test", company_id="company-test", id=space_id)
    s["name"] = name
    s["modules"] = []
    return s


def _module(
    module_id: str,
    name: str,
    configuration: dict[str, object],
) -> unique_sdk.Module:
    m = unique_sdk.Module(user_id="user-test", company_id="company-test", id=module_id)
    m["name"] = name
    m["configuration"] = configuration
    return m


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def server() -> FastMCP:
    return build_server(auth_settings=None)


@pytest.fixture(autouse=True)
def identity_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject env-var identity so get_caller/get_space_id resolve without _meta."""
    monkeypatch.setenv("ALLOW_EPHEMERAL_OAUTH_STORAGE", "true")
    monkeypatch.setenv("UNIQUE_AUTH_USER_ID", "user-test")
    monkeypatch.setenv("UNIQUE_AUTH_COMPANY_ID", "company-test")
    monkeypatch.setenv("UNIQUE_AUTH_ASSISTANT_ID", "assistant_testspace")
    monkeypatch.delenv("ZITADEL_BASE_URL", raising=False)


def _data(result: CallToolResult) -> dict[str, object]:
    """Extract the dict payload from a tool result."""
    if result.structured_content is not None:
        return cast(dict[str, object], result.structured_content)
    content = result.content[0]
    assert isinstance(content, mcp_types.TextContent)
    return cast(dict[str, object], json.loads(content.text))


# ---------------------------------------------------------------------------
# Unique AI space
# ---------------------------------------------------------------------------


class TestUniqueAISpace:
    async def test_get_space_returns_space_data(self, server: FastMCP) -> None:
        space = _space()
        with patch("unique_sdk.Space.get_space_async", new=AsyncMock(return_value=space)):
            async with Client(server) as client:
                result = await client.call_tool("get_space", {})
        assert not result.is_error
        data = _data(result)
        assert data["id"] == "assistant_testspace"
        assert data["name"] == "Test Space"

    async def test_list_language_models_returns_model_list(self, server: FastMCP) -> None:
        raw = {"models": ["gpt-4o", "gpt-4o-mini"]}
        with patch(
            "space_config_mcp.upstream.client.LLMModels.get_models_async",
            new=AsyncMock(return_value=raw),
        ):
            async with Client(server) as client:
                result = await client.call_tool("list_language_models", {})
        assert not result.is_error
        data = _data(result)
        assert "gpt-4o" in cast(list[str], data["models"])


# ---------------------------------------------------------------------------
# Conduct space
# ---------------------------------------------------------------------------


class TestConductSpace:
    async def test_get_conduct_config_returns_typed_config(self, server: FastMCP) -> None:
        mod = _module(
            "mod-conduct-1",
            "SwappableIntelligence",
            {"strategy": "claude_code", "maxTurns": 10},
        )
        with patch("unique_sdk.Module.list_async", new=AsyncMock(return_value=[mod])):
            async with Client(server) as client:
                result = await client.call_tool("get_conduct_config", {})
        assert not result.is_error
        data = _data(result)
        assert data["module_id"] == "mod-conduct-1"
        assert cast(dict[str, object], data["configuration"])["strategy"] == "claude_code"

    async def test_get_conduct_config_errors_when_no_swappable_intelligence_module(
        self, server: FastMCP
    ) -> None:
        with patch("unique_sdk.Module.list_async", new=AsyncMock(return_value=[])):
            async with Client(server) as client:
                result = await client.call_tool("get_conduct_config", {}, raise_on_error=False)
        assert result.is_error

    async def test_update_conduct_config_patches_strategy(self, server: FastMCP) -> None:
        mod = _module(
            "mod-conduct-1",
            "SwappableIntelligence",
            {"strategy": "claude_code", "maxTurns": 10},
        )
        updated = _module(
            "mod-conduct-1",
            "SwappableIntelligence",
            {"strategy": "pi_agent", "maxTurns": 10},
        )
        with (
            patch("space_config_mcp.contexts.modules.write.snapshot_space", new=AsyncMock()),
            patch("unique_sdk.Module.list_async", new=AsyncMock(return_value=[mod])),
            patch("unique_sdk.Module.modify_async", new=AsyncMock(return_value=updated)),
        ):
            async with Client(server) as client:
                result = await client.call_tool("update_conduct_config", {"strategy": "pi_agent"})
        assert not result.is_error
        data = _data(result)
        assert cast(dict[str, object], data["configuration"])["strategy"] == "pi_agent"

    async def test_update_conduct_config_patches_max_turns(self, server: FastMCP) -> None:
        config: dict[str, object] = {
            "strategy": "claude_code",
            "maxTurns": 10,
            "claude": {"maxTurns": 10},
        }
        mod = _module("mod-conduct-1", "SwappableIntelligence", config)
        updated_config: dict[str, object] = {
            "strategy": "claude_code",
            "maxTurns": 20,
            "claude": {"maxTurns": 20},
        }
        updated = _module("mod-conduct-1", "SwappableIntelligence", updated_config)
        with (
            patch("space_config_mcp.contexts.modules.write.snapshot_space", new=AsyncMock()),
            patch("unique_sdk.Module.list_async", new=AsyncMock(return_value=[mod])),
            patch("unique_sdk.Module.modify_async", new=AsyncMock(return_value=updated)),
        ):
            async with Client(server) as client:
                result = await client.call_tool("update_conduct_config", {"max_turns": 20})
        assert not result.is_error
        data = _data(result)
        assert cast(dict[str, object], data["configuration"])["maxTurns"] == 20


# ---------------------------------------------------------------------------
# Magic Table space
# ---------------------------------------------------------------------------


class TestMagicTableSpace:
    async def test_get_magic_table_config_returns_config(self, server: FastMCP) -> None:
        mod = _module("mod-rfp-1", "RfpAgent", {"languageModel": "gpt-4o", "columns": []})
        with patch("unique_sdk.Module.list_async", new=AsyncMock(return_value=[mod])):
            async with Client(server) as client:
                result = await client.call_tool("get_magic_table_config", {})
        assert not result.is_error
        data = _data(result)
        assert data["module_id"] == "mod-rfp-1"
        assert cast(dict[str, object], data["configuration"])["languageModel"] == "gpt-4o"

    async def test_get_magic_table_config_errors_when_no_rfp_agent_module(
        self, server: FastMCP
    ) -> None:
        with patch("unique_sdk.Module.list_async", new=AsyncMock(return_value=[])):
            async with Client(server) as client:
                result = await client.call_tool("get_magic_table_config", {}, raise_on_error=False)
        assert result.is_error

    async def test_update_magic_table_config_patches_language_model(self, server: FastMCP) -> None:
        mod = _module("mod-rfp-1", "RfpAgent", {"languageModel": "gpt-4o", "columns": []})
        updated = _module("mod-rfp-1", "RfpAgent", {"languageModel": "gpt-4o-mini", "columns": []})
        with (
            patch("space_config_mcp.contexts.modules.write.snapshot_space", new=AsyncMock()),
            patch("unique_sdk.Module.list_async", new=AsyncMock(return_value=[mod])),
            patch("unique_sdk.Module.modify_async", new=AsyncMock(return_value=updated)),
            patch(
                "space_config_mcp.upstream.client.LLMModels.get_models_async",
                new=AsyncMock(return_value={"models": ["gpt-4o", "gpt-4o-mini"]}),
            ),
        ):
            async with Client(server) as client:
                result = await client.call_tool(
                    "update_magic_table_config", {"language_model": "gpt-4o-mini"}
                )
        assert not result.is_error
        data = _data(result)
        assert cast(dict[str, object], data["configuration"])["languageModel"] == "gpt-4o-mini"
