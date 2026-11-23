import asyncio

from fastmcp import Client
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
import pytest

from world_check_mcp.mcp.deadline import ToolDeadlineMiddleware


def _server() -> FastMCP:
    mcp = FastMCP(
        "deadline", middleware=[ToolDeadlineMiddleware(0.05, exempt=frozenset({"patient"}))]
    )

    @mcp.tool
    async def quick() -> str:
        """Answers at once."""
        return "done"

    @mcp.tool
    async def slow() -> str:
        """Outlasts the deadline."""
        await asyncio.sleep(1)
        return "late"

    @mcp.tool
    async def patient() -> str:
        """Outlasts the deadline, but waits for a person."""
        await asyncio.sleep(0.1)
        return "answered"

    return mcp


async def test_a_quick_tool_answers() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("quick", {})

    assert result.structured_content == {"result": "done"}


async def test_a_tool_that_outlasts_the_deadline_is_stopped_with_a_retry_warning() -> None:
    async with Client(_server()) as client:
        with pytest.raises(ToolError, match=r"slow did not finish within 0.05 seconds.*get_case"):
            await client.call_tool("slow", {})


async def test_a_tool_that_waits_for_a_person_is_not_stopped() -> None:
    async with Client(_server()) as client:
        result = await client.call_tool("patient", {})

    assert result.structured_content == {"result": "answered"}
