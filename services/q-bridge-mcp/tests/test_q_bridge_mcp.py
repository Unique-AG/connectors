import asyncio

from q_bridge_mcp.main import hello_world, mcp


def test_hello_world_returns_greeting() -> None:
    assert hello_world() == "Hello, world!"


def test_registers_only_hello_world_tool() -> None:
    tools = asyncio.run(mcp.list_tools())

    assert [tool.name for tool in tools] == ["hello_world"]
