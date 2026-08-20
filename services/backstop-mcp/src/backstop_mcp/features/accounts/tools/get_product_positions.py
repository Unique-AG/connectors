"""`get_product_positions`: current balances and lifetime totals for a Backstop product.

A product is what many tenants call a fund, vehicle, or share class — that mapping lives here,
not in a `fund` parameter. Figures come from three series (`values`, `totalInvested`,
`totalRedemptions`), each the latest valued point on the first 10 rows of `sort=-date`.
"""

import logging
from typing import Annotated

from fastmcp import Context
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.features.accounts import (
    ProductAmbiguousResponse,
    ProductPositionsResolvedResponse,
    fetch_accounts_for_product,
    fetch_product_positions,
    resolve_product,
)
from backstop_mcp.features.resolution import NotFoundResponse, Resolved
from backstop_mcp.models import published_output_schema
from backstop_mcp.server.runtime import get_backstop_client

logger = logging.getLogger(__name__)

type GetProductPositionsResponse = (
    ProductAmbiguousResponse | NotFoundResponse | ProductPositionsResolvedResponse
)


@tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    output_schema=published_output_schema(GetProductPositionsResponse),
)
async def get_product_positions(
    ctx: Context,
    product_id: Annotated[
        str | None,
        Field(
            description=(
                "Trusted Backstop product id from a prior resolve echo. Never invent or guess. "
                "Exactly one of `product_id` or `product` must be provided."
            ),
        ),
    ] = None,
    product: Annotated[
        str | None,
        Field(
            description=(
                "Product id, `productShortName` (e.g. 'CGUP'), or name. Tenants may call this "
                "a fund, vehicle, or share class — the Backstop name is still `product`. "
                "Exactly one of `product_id` or `product` must be provided."
            ),
        ),
    ] = None,
    include_closed: Annotated[
        bool,
        Field(
            description=(
                "When false (default), only open accounts are returned (`closedDate` key "
                "absent). Closed accounts still publish `values` of `0.0` through today; "
                "including them by default looks like empty live positions."
            ),
        ),
    ] = False,
) -> GetProductPositionsResponse:
    """Current balances, lifetime invested/redeemed, and account status for a Backstop product.

    A product is the investment product (tenants may say fund, vehicle, or share class). Pass a
    trusted `product_id` or `product` (short name or name). Duplicate short names elicit a choice.

    Each open account is returned with:
    - `balance` from `values` (current NAV / market value)
    - `invested` from `totalInvested` (lifetime cumulative)
    - `redemptions` from `totalRedemptions` (lifetime cumulative)

    Each figure is `{value, date, valueStatus?}` with that series' own date, and is the latest
    point that carries a number — Backstop publishes a dated row before the value lands, and
    `newer_point_without_value` names that row when it exists, so a stale figure is reported as
    stale rather than as current. `valueStatus` is passed through when Backstop sends it (recent
    `values` are often `ESTIMATE`) and omitted when it does not — do not invent `ACTUAL`. A
    missing series is omitted, never `0.0`.

    `aum` is assets under management: the product's latest `/aums` point, not one investor's
    balance. `balance_total` and `aum_difference` show it against the sum of returned balances;
    `aum_diverges` is a 0.5% tolerance verdict, not a failure — the open default excludes
    closed-but-still-valued accounts.

    An empty `accounts` list with `closed_omitted>0` means every account is closed — pass
    `include_closed=true` rather than reading that as "no investors". `accounts_omitted>0`
    means the product exceeded the per-call fan-out cap and `accounts` is a partial list.
    """
    if (product_id is None) == (product is None):
        raise ValueError("Exactly one of product_id or product must be provided")

    client = await get_backstop_client()
    outcome = await resolve_product(ctx, client, product_id=product_id, product=product)
    if not isinstance(outcome, Resolved):
        return ProductAmbiguousResponse.from_unresolved(outcome)

    resolved = outcome.value
    logger.info(
        "accounts.product_positions.start",
        extra={"product_id": resolved.id, "include_closed": include_closed},
    )
    listing = await fetch_accounts_for_product(
        client, product_id=resolved.id, include_closed=include_closed
    )
    positions = await fetch_product_positions(client, listing, product=resolved)
    logger.info(
        "accounts.product_positions.completed",
        extra={
            "product_id": resolved.id,
            "returned": len(positions.accounts),
            "closed_omitted": positions.closed_omitted,
            "accounts_omitted": positions.accounts_omitted,
            "aum_diverges": positions.reconciliation.diverges,
        },
    )
    return ProductPositionsResolvedResponse.from_positions(positions)
