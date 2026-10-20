from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp_types import ToolAnnotations

from architecture_demo_mcp.contexts import assets
from architecture_demo_mcp.mcp.dependencies import get_upstream
from architecture_demo_mcp.mcp.inputs.ticker import Ticker
from architecture_demo_mcp.upstream import Upstream


@tool(
    title="Get Asset",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
async def get_asset(
    ticker: Ticker, upstream: Upstream = Depends(get_upstream)
) -> assets.AssetDetails:
    """Read an asset's name, description, exchange and the dates its price history covers."""
    return await assets.get_asset(upstream=upstream, ticker=ticker)
