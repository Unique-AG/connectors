"""`get_time_series`: one dated series on one account or one product.

This is the only way to get a dated, status-labelled figure. Party snapshot balances without
a date come from `get_accounts_for_party`. Take `entity_id` from that listing (accounts) or
from a product resolve — never invent one. Do not iterate every account in a fund: a fund-level
number is this tool on the product's `aums`.
"""

import logging
from datetime import date
from http import HTTPStatus
from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.backstop_client import BackstopApiError, BackstopClient
from backstop_mcp.dependencies import get_backstop_client_for_current_caller
from backstop_mcp.features.accounts import (
    ProductAmbiguousResponse,
    TimeSeriesEntityType,
    TimeSeriesName,
    TimeSeriesResolvedResponse,
    fetch_time_series,
    require_series_for_entity,
    resolve_product_query,
)
from backstop_mcp.features.resolution import NotFoundResponse, Resolved
from backstop_mcp.models import published_output_schema

logger = logging.getLogger(__name__)

type GetTimeSeriesResponse = (
    ProductAmbiguousResponse | NotFoundResponse | TimeSeriesResolvedResponse
)

_SERIES_HELP = (
    "Which series to read. One per call. Pick from the meaning, not the name: `values` is "
    "not the answer to every money question. "
    "Accounts: "
    "`values` — ending NAV / balance (`valueStatus` ESTIMATE/ACTUAL; latest point matches "
    "table-data `balance`); "
    "`startingValues` — beginning-of-period value (differs from `values` when there was "
    "activity in the period); "
    "`currentMonthNetAssests` — current-month net assets (Backstop's spelling); "
    "`totalInvested` — lifetime capital in (cumulative subscriptions, not a period figure); "
    "`totalRedemptions` — lifetime capital out (cumulative redemptions); "
    "`earnings` — lifetime P&L (cumulative, not a one-month increment); "
    "`percentageOfFundHistory` — share of the product as a fraction (`0.796` = 79.6%), not "
    "a percent; "
    "`returns` — period performance as a decimal (`0.007` ≈ 0.7%), not a percent; "
    "`irrs` — life-to-date IRR as a decimal (`0.05` ≈ 5%); "
    "`currentMonthIrrs` — this period's IRR as a decimal; "
    "`grossValues` — gross value before fees (may be unused 0); "
    "`highwaterMarks` — incentive-fee high-water mark (may be unused 0); "
    "`incentiveFees` / `incentiveFeesCharged` — accrued / charged incentive fee; "
    "`performanceFeeAccrued` — accrued performance fee; "
    "`managementFees` — management fees; "
    "`newIssueIncomes` — new-issue (IPO) income. "
    "Products: "
    "`aums` — the product's total assets under management, not one investor's balance "
    "(carries `source`); "
    "`benchmarkAReturns`–`benchmarkHReturns` — product versus each benchmark; "
    "`incomeDataPoints` / `expenseDataPoints` — dated income / expense (`date`, `value` only). "
    "A series that is valid on the other entity type is an error, not a 404."
)


@tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    output_schema=published_output_schema(GetTimeSeriesResponse),
)
async def get_time_series(
    ctx: Context,
    entity_type: Annotated[
        TimeSeriesEntityType,
        Field(
            description=("`accounts` for one investor vehicle, `products` for a fund/vehicle."),
        ),
    ],
    entity_id: Annotated[
        str,
        Field(
            description=(
                "Trusted Backstop id of that account or product. For products, a "
                "`productShortName` or name is also accepted and resolved. Never invent or guess."
            ),
        ),
    ],
    series: Annotated[TimeSeriesName, Field(description=_SERIES_HELP)],
    start_date: Annotated[
        date | None,
        Field(
            default=None,
            description=(
                "Inclusive lower bound on `date` (`filter[date][ge]`). Omit with `end_date` to "
                "walk the whole series. Pass a window for a long daily history — the tool "
                "returns every point in range."
            ),
        ),
    ] = None,
    end_date: Annotated[
        date | None,
        Field(
            default=None,
            description=(
                "Inclusive upper bound on `date` (`filter[date][le]`). `start_date` after "
                "`end_date` is rejected before any request."
            ),
        ),
    ] = None,
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
) -> GetTimeSeriesResponse:
    """Dated points of one time series on one account or one product.

    Pass `entity_type`, a trusted `entity_id`, and `series`. Optional `start_date` / `end_date`
    are an inclusive window; omit both to paginate the whole series. Newest first. A long
    daily series belongs in a window, not an unbounded walk.

    **`values` is the balance.** It is not the answer to every money question —
    `startingValues`, `totalInvested`, and `earnings` are also money about an account.
    **`aums` is the product's total assets under management**, not one investor's balance.

    A dated point with no `value` is "not in yet" (Backstop's UI shows `-`), a published `0.0`
    is a real zero, and an unused fee series of zeroes is not "this account has no NAV".
    `valueStatus` (accounts) and `source` (product `aums`) are passed through when Backstop
    sends them and omitted when it does not.

    Do not call `/accounts/{id}/analytics` for these figures: on this API it returns empty
    envelopes. Do not loop this tool over every account in a fund — that reconstitutes the
    fan-out this connector removed. For a fund-level number, call this once on the product's
    `aums`.
    """
    entity_id = entity_id.strip()
    if not entity_id:
        raise ValueError("entity_id must not be blank")
    if "/" in entity_id:
        raise ValueError(f"entity_id {entity_id!r} must not contain '/'")
    if start_date is not None and end_date is not None and start_date > end_date:
        raise ValueError("start_date must not be after end_date")
    require_series_for_entity(entity_type, series)

    resolved_id = entity_id
    if entity_type == "products":
        outcome = await resolve_product_query(ctx, client, query=entity_id)
        if not isinstance(outcome, Resolved):
            return ProductAmbiguousResponse.from_unresolved(outcome)
        resolved_id = outcome.value.id

    logger.info(
        "accounts.time_series.start",
        extra={
            "entity_type": entity_type,
            "entity_id": resolved_id,
            "series": series,
            "start_date": None if start_date is None else start_date.isoformat(),
            "end_date": None if end_date is None else end_date.isoformat(),
        },
    )
    try:
        points = await fetch_time_series(
            client,
            entity_type=entity_type,
            entity_id=resolved_id,
            series=series,
            start_date=start_date,
            end_date=end_date,
        )
    except BackstopApiError as exc:
        if entity_type != "accounts" or exc.status_code != HTTPStatus.NOT_FOUND:
            raise
        return NotFoundResponse(query=entity_id, scope=entity_type)

    logger.info(
        "accounts.time_series.completed",
        extra={
            "entity_type": entity_type,
            "entity_id": resolved_id,
            "series": series,
            "points": len(points),
        },
    )
    return TimeSeriesResolvedResponse.from_points(
        entity_type=entity_type,
        entity_id=resolved_id,
        series=series,
        points=points,
    )
