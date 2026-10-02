from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from with_intelligence_mcp.features.funds.dependencies import get_fund_query_factory
from with_intelligence_mcp.features.funds.queries import GetFundQuery
from with_intelligence_mcp.features.funds.responses import (
    FundAmbiguousResponse,
    FundNotEntitledResponse,
    FundNotFoundResponse,
    FundProfileResponse,
)
from with_intelligence_mcp.models import published_output_schema

type GetFundResult = (
    FundProfileResponse | FundAmbiguousResponse | FundNotEntitledResponse | FundNotFoundResponse
)


@tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(GetFundResult),
)
async def get_fund(
    name: Annotated[
        str | None,
        Field(
            description=(
                "Fund name. Matching is partial, so a short name returns candidates to choose "
                "between. Omit when passing fund_id."
            )
        ),
    ] = None,
    fund_id: Annotated[
        int | None,
        Field(description="With Intelligence fund id, when it is already known."),
    ] = None,
    get_fund_query: GetFundQuery = Depends(get_fund_query_factory),
) -> GetFundResult:
    """Profile one fund: its manager, strategies, structure, fees, liquidity, and whether it is
    liquidated or only inferred.

    Pass a name and it is resolved first; several matches come back as candidates to choose
    between. Assets are in MILLIONS. The minimum investment is a currency amount, not millions.
    """
    return await get_fund_query.run(name=name, fund_id=fund_id)
