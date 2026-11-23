import functools
from collections.abc import Mapping

import pytest
from fastmcp import Client, FastMCP
from fastmcp.client.transports import FastMCPTransport

from tests.e2e.test_scenarios import Person, build_server, patch_obo
from tests.graph_fixtures import response, serve

__all__ = ["Person", "call", "response", "serve"]


@functools.cache
def _server() -> FastMCP[None]:
    return build_server()


async def call(
    tool: str, /, *, person: Person | None = None, **arguments: object
) -> Mapping[str, object]:
    with pytest.MonkeyPatch.context() as patch:
        patch_obo(patch)
        handler = person or Person()
        async with Client(
            FastMCPTransport(_server()), elicitation_handler=handler, mode="legacy"
        ) as client:
            answer = await client.call_tool(tool, arguments)
    assert answer.structured_content is not None, f"{tool} answered with text only"
    return answer.structured_content
