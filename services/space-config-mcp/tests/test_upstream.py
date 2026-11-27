"""Tests for the unique_sdk-backed Upstream wrapper."""

from typing import cast
from unittest.mock import AsyncMock
from unittest.mock import patch

from pydantic import SecretStr
import pytest
import unique_sdk

from space_config_mcp.upstream import open_upstream
from space_config_mcp.upstream import Upstream
from space_config_mcp.upstream import UpstreamSettings


def make_settings() -> UpstreamSettings:
    return UpstreamSettings(
        unique_api_key=SecretStr("dummy-key"),
        unique_app_id="dummy-app",
    )


async def test_open_upstream_bootstraps_unique_sdk() -> None:
    settings = make_settings()
    async with open_upstream(settings) as upstream:
        assert isinstance(upstream, Upstream)
        assert unique_sdk.api_key == "dummy-key"
        assert unique_sdk.app_id == "dummy-app"


async def test_get_spaces_calls_sdk(upstream_settings: UpstreamSettings) -> None:
    result_data: unique_sdk.Space.Spaces = {"data": []}

    with patch(
        "unique_sdk.Space.get_spaces_async",
        new=AsyncMock(return_value=result_data),
    ):
        async with open_upstream(upstream_settings) as upstream:
            result = await upstream.get_spaces("u1", "c1")

    assert result == result_data


async def test_get_space_calls_sdk(upstream_settings: UpstreamSettings) -> None:
    space = cast(unique_sdk.Space, {"id": "space-1", "name": "Test Space"})

    with patch(
        "unique_sdk.Space.get_space_async",
        new=AsyncMock(return_value=space),
    ):
        async with open_upstream(upstream_settings) as upstream:
            result = await upstream.get_space("u1", "c1", "space-1")

    assert result is space


async def test_list_modules_calls_sdk(upstream_settings: UpstreamSettings) -> None:
    mod = cast(unique_sdk.Module, {"id": "mod-1", "name": "Module1"})
    modules = [mod]

    with patch(
        "unique_sdk.Module.list_async",
        new=AsyncMock(return_value=modules),
    ):
        async with open_upstream(upstream_settings) as upstream:
            result = await upstream.list_modules("u1", "c1", "space-1")

    assert result == modules


async def test_get_module_calls_sdk(upstream_settings: UpstreamSettings) -> None:
    mod = cast(unique_sdk.Module, {"id": "mod-1", "name": "Module1", "configuration": {}})

    with patch(
        "unique_sdk.Module.retrieve_async",
        new=AsyncMock(return_value=mod),
    ):
        async with open_upstream(upstream_settings) as upstream:
            result = await upstream.get_module("u1", "c1", "mod-1")

    assert result is mod


async def test_modify_module_calls_sdk(upstream_settings: UpstreamSettings) -> None:
    mod = cast(unique_sdk.Module, {"id": "mod-1", "configuration": {"maxTurns": 5}})

    with patch(
        "unique_sdk.Module.modify_async",
        new=AsyncMock(return_value=mod),
    ):
        async with open_upstream(upstream_settings) as upstream:
            result = await upstream.modify_module(
                "u1", "c1", "mod-1", configuration={"maxTurns": 5}
            )

    assert result is mod


@pytest.fixture
def upstream_settings() -> UpstreamSettings:
    return make_settings()
