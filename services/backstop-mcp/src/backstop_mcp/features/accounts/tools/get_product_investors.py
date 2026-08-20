"""`get_product_investors`: who holds a product, with no figures.

Step 1 of two. Dated NAV, IRR, and other series are `get_time_series` on a specific account
(or on this product's `aums` for the fund-level number). Do not call `get_time_series` once
per account in the fund — that reconstitutes the fan-out this connector removed.
"""

import logging
from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client
from backstop_mcp.features.accounts import (
    ProductAmbiguousResponse,
    ProductInvestorsResolvedResponse,
    fetch_accounts_for_product,
    resolve_product_query,
)
from backstop_mcp.features.resolution import NotFoundResponse, Resolved
from backstop_mcp.models import published_output_schema

logger = logging.getLogger(__name__)

type GetProductInvestorsResponse = (
    ProductAmbiguousResponse | NotFoundResponse | ProductInvestorsResolvedResponse
)


@tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    output_schema=published_output_schema(GetProductInvestorsResponse),
)
async def get_product_investors(
    ctx: Context,
    product_id: Annotated[
        str | None,
        Field(
            description=(
                "Trusted Backstop product id from a prior resolve echo. A short name here is "
                "resolved through the catalog rather than failing. Never invent one. Exactly "
                "one of `product_id` or `product` must be provided."
            ),
        ),
    ] = None,
    product: Annotated[
        str | None,
        Field(
            description=(
                "Product short name (`CGUP`) or display name. Same catalog resolve as "
                "`product_id`. Duplicate short names (`BLUC`, `Dispersion`) are ambiguous — "
                "pick from the candidates rather than guessing. Exactly one of `product_id` or "
                "`product` must be provided."
            ),
        ),
    ] = None,
    include_closed: Annotated[
        bool,
        Field(
            description=(
                "When false (default), only open accounts are returned (`closedDate` key "
                "absent). Pass true to include closed accounts."
            ),
        ),
    ] = False,
    client: BackstopClient = Depends(get_backstop_client),
) -> GetProductInvestorsResponse:
    """The accounts in one product, and who owns them. No balances, no series.

    Pass a trusted `product_id` or `product` (short name or display name). This is step 1 of
    two: identity and owners only. A dated figure is step 2 — `get_time_series` on that
    account. Figures cost one call per (account, series), so a fund with 200 accounts is
    not a question to answer account-by-account — that reconstitutes the fan-out this
    connector removed. Fund-level AUM is `get_time_series` on this product's `aums`, which
    is the product's total assets under management, not one investor's balance.

    Owner `resource_type` may be `contacts` even when the party is an organization — echo
    `id` and `resource_type` together as a later party resolve; do not assume `contacts`
    means a person. An empty list with `closed_omitted>0` means every account is closed —
    pass `include_closed=true` rather than reading that as "no investors".
    """
    if (product_id is None) == (product is None):
        raise ValueError("Exactly one of product_id or product must be provided")

    query = product_id if product_id is not None else product
    assert query is not None
    outcome = await resolve_product_query(ctx, client, query=query)
    if not isinstance(outcome, Resolved):
        return ProductAmbiguousResponse.from_unresolved(outcome)

    resolved = outcome.value
    logger.info(
        "accounts.product_investors.start",
        extra={"product_id": resolved.id, "include_closed": include_closed},
    )
    listing = await fetch_accounts_for_product(
        client, product_id=resolved.id, include_closed=include_closed
    )
    logger.info(
        "accounts.product_investors.completed",
        extra={
            "product_id": resolved.id,
            "returned": len(listing.accounts),
            "closed_omitted": listing.closed_omitted,
        },
    )
    return ProductInvestorsResolvedResponse.from_listing(listing, product=resolved)
