"""Handshake-only discover: an auto client must stay on the elicit back-channel era."""

import pytest
from fastmcp import Client, FastMCP
from mcp.types.version import LATEST_HANDSHAKE_VERSION, LATEST_MODERN_VERSION

from backstop_mcp.server.handshake_protocol import HandshakeOnlyProtocolMiddleware


@pytest.mark.asyncio
async def test_auto_client_negotiates_the_handshake_era() -> None:
    server = FastMCP("probe", middleware=[HandshakeOnlyProtocolMiddleware()])

    async with Client(server, mode="auto") as client:
        assert client.protocol_version == LATEST_HANDSHAKE_VERSION


@pytest.mark.asyncio
async def test_unpinned_server_still_offers_the_modern_era() -> None:
    async with Client(FastMCP("probe"), mode="auto") as client:
        assert client.protocol_version == LATEST_MODERN_VERSION
