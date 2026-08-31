"""`get_capital_flows`: subscriptions and redemptions in a mandatory date window."""

from collections.abc import Sequence
from datetime import date
from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.features.accounts import (
    CapitalFlowsResolvedResponse,
    GetCapitalFlowsQuery,
)
from backstop_mcp.features.accounts.dependencies import get_capital_flows_query_factory
from backstop_mcp.models import published_output_schema

_DEFAULT_MAX_ROWS = 200
_MAX_ROWS = 1_000


@tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    output_schema=published_output_schema(CapitalFlowsResolvedResponse),
)
async def get_capital_flows(
    start_date: Annotated[
        date,
        Field(
            description=(
                "Inclusive start of filter[transactionDate]. Required — an unfiltered read is 400."
            )
        ),
    ],
    end_date: Annotated[
        date,
        Field(description="Inclusive end of filter[transactionDate]. Required."),
    ],
    max_rows: Annotated[
        int,
        Field(
            ge=1,
            le=_MAX_ROWS,
            description="Row cap applied after owner/account filters. Counts are over the match.",
        ),
    ] = _DEFAULT_MAX_ROWS,
    owner_id: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Keep flows whose included owner id matches. Echo from get_accounts_for_party "
                "or a prior resolve. Unattributed rows have no owner and drop out."
            ),
        ),
    ] = None,
    account_ids: Annotated[
        Sequence[str] | None,
        Field(
            default=None,
            description=(
                "Keep flows whose account id is in this list. Echo account ids from "
                "get_accounts_for_party or get_product_investors. Rows have no product — join "
                "this way. Unattributed rows drop out."
            ),
        ),
    ] = None,
    get_capital_flows_query: GetCapitalFlowsQuery = Depends(get_capital_flows_query_factory),
) -> CapitalFlowsResolvedResponse:
    """Subscriptions and redemptions in a date window — also the only share-class source.

    Always pass `start_date` and `end_date`; Backstop refuses an unfiltered read. Two collection
    walks, one per direction — `request_count` is what they actually cost, and `scan_truncated`
    says when a window was too big to read whole. Actuals only (`COMPLETED`); `non_actual_count`
    is how many rows that excluded. A redemption has no account of its own and is attributed
    through `originalSubscription`; when that chain is missing the row is `unattributed`,
    not omitted. `share_class` / `share_series` live on the subscription, not the account.

    Rows carry no product. For "which share class is X in within Fund Y", take that party's
    account ids from `get_accounts_for_party` (or `get_product_investors`) and pass them as
    `account_ids` **before** `max_rows` cuts the list. Share class lives on the original
    subscription, so the window must include that subscription's `transaction_date`, not only
    the period you are asking about.
    """
    if start_date > end_date:
        raise ValueError("start_date must not be after end_date")
    return await get_capital_flows_query.run(
        start_date=start_date,
        end_date=end_date,
        max_rows=max_rows,
        owner_id=owner_id,
        account_ids=account_ids,
    )
