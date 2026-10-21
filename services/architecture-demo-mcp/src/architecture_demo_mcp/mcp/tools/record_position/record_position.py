from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp_types import ToolAnnotations

from architecture_demo_mcp import contexts
from architecture_demo_mcp.mcp.dependencies import get_owner
from architecture_demo_mcp.mcp.dependencies import get_persistence
from architecture_demo_mcp.mcp.dependencies import get_upstream
from architecture_demo_mcp.mcp.inputs.ticker import Ticker
from architecture_demo_mcp.mcp.tools.record_position.record_position_inputs import CostBasis
from architecture_demo_mcp.mcp.tools.record_position.record_position_inputs import PortfolioName
from architecture_demo_mcp.mcp.tools.record_position.record_position_inputs import Quantity
from architecture_demo_mcp.persistence import Persistence
from architecture_demo_mcp.upstream import Upstream


@tool(
    title="Record Position",
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=True
    ),
)
async def record_position(
    portfolio: PortfolioName,
    ticker: Ticker,
    quantity: Quantity,
    cost_basis: CostBasis,
    upstream: Upstream = Depends(get_upstream),
    persistence: Persistence = Depends(get_persistence),
    owner: str = Depends(get_owner),
) -> contexts.PortfolioValuation:
    """Record how much of a ticker the user holds in one of their portfolios, then value the
    whole portfolio at the latest closes: market value, unrealized P&L and each position's weight.

    Recording a ticker again replaces its quantity and cost basis. Only the signed-in user sees
    their portfolios. Tiingo must have prices for the ticker.
    """
    position = contexts.PositionInput(
        portfolio=portfolio, ticker=ticker, quantity=quantity, cost_basis=cost_basis
    )
    try:
        return await contexts.record_position(
            upstream=upstream, persistence=persistence, owner=owner, position=position
        )
    except contexts.PositionRejectedError as error:
        raise ToolError(str(error)) from error
