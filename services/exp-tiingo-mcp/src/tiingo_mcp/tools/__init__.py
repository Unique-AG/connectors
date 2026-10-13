from fastmcp import FastMCP

from tiingo_mcp.tools import fundamentals, prices, returns


async def register_tools(mcp: FastMCP) -> None:
    # Base tools first, composites last, each after the tools it looks up with require_tool.
    # If dependencies get more complex, declare them per module and sort the registration.
    await prices.register(mcp)
    await fundamentals.register(mcp)
    await returns.register(mcp)
