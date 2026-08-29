"""`get_capital_flows`: subscriptions and redemptions in a mandatory date window."""

from collections.abc import Sequence
from datetime import date
from typing import Annotated, Literal, Self

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client_for_current_caller
from backstop_mcp.features.accounts import (
    MAX_CAPITAL_FLOW_SCAN_RECORDS,
    CapitalFlowDto,
    fetch_capital_flows,
)
from backstop_mcp.models import OmitNoneModel, published_output_schema

_DEFAULT_MAX_ROWS = 200
_MAX_ROWS = 1_000


class CapitalFlowPartyResponse(OmitNoneModel):
    """An account or owning party on a flow row."""

    id: str = Field(description="Backstop id. Echo it; never invent one.")
    name: str | None = Field(default=None, description="Name as published on the include.")
    resource_type: str | None = Field(
        default=None, description="JSON:API type: accounts, contacts, organizations, or people."
    )


class CapitalFlowRowResponse(OmitNoneModel):
    """One actual subscription or redemption."""

    id: str = Field(description="Backstop id of this subscription or redemption.")
    kind: Literal["subscription", "redemption"] = Field(
        description="Inflow or outflow. Share class lives on the subscription, not the account."
    )
    amount: float | None = Field(
        default=None, description="Transaction amount as Backstop stored it."
    )
    transaction_date: date | None = Field(default=None, description="Day the flow took effect.")
    notice_date: date | None = Field(default=None, description="Day notice was recorded, if any.")
    status: str | None = Field(
        default=None, description="Always COMPLETED — estimates are omitted."
    )
    description: str | None = Field(default=None, description="Backstop's description of the flow.")
    share_class: str | None = Field(
        default=None,
        description="Share class on the subscription. Omitted when Backstop has none.",
    )
    share_series: str | None = Field(
        default=None,
        description="Share series on the subscription. Omitted when Backstop has none.",
    )
    liquidating: bool | None = Field(
        default=None, description="True when a redemption is a full liquidating redemption."
    )
    account: CapitalFlowPartyResponse | None = Field(
        default=None, description="The account this flow belongs to, when the include resolved."
    )
    owner: CapitalFlowPartyResponse | None = Field(
        default=None, description="The party that owns that account, when the include resolved."
    )
    unattributed: bool = Field(
        description=(
            "True when this flow could not be tied to an account: a redemption whose "
            "originalSubscription.fundAccount chain is missing, or a subscription whose "
            "fundAccount include did not arrive. That is an orphan, not a dropped row, and it "
            "has no owner — so it drops out of both owner_id and account_ids."
        )
    )

    @classmethod
    def from_dto(cls, row: CapitalFlowDto) -> Self:
        return cls.model_validate(row.model_dump())


class CapitalFlowsResolvedResponse(OmitNoneModel):
    """Actual subscriptions and redemptions in the requested window."""

    status: Literal["resolved"] = Field(
        default="resolved",
        description=(
            "Always 'resolved': both collections were read. An empty list is none in window."
        ),
    )
    request_count: int = Field(
        description=(
            "Pages actually fetched across both collections. At least 2 — one page of each — "
            "and more whenever a window holds more than one page of either."
        )
    )
    flows: tuple[CapitalFlowRowResponse, ...] = Field(
        description="Actuals newest-first by transaction_date. Capped at max_rows."
    )
    total: int = Field(description="Actuals in the window before the row cap.")
    subscription_count: int = Field(description="How many of `total` are subscriptions.")
    redemption_count: int = Field(description="How many of `total` are redemptions.")
    unattributed_count: int = Field(
        description=(
            "Flows in `total` that could not be tied to an account — see `unattributed`. "
            "Included in `flows`."
        )
    )
    non_actual_count: int = Field(
        description=(
            "Rows in the window that were not actuals (status != COMPLETED) and are therefore "
            "absent from `flows` and from every count here. A window with pending "
            "subscriptions is not a window with none."
        )
    )
    truncated: bool = Field(
        description=(
            "True when matching actuals exceeded `max_rows`. Counts are over the matching "
            "set, not the truncated `flows` list."
        )
    )
    scan_truncated: bool = Field(
        description=(
            f"True when a walk stopped at the {MAX_CAPITAL_FLOW_SCAN_RECORDS}-row scan "
            "ceiling, so the window was read only in part and every count here is a floor. "
            "Narrow the date window; neither collection takes a server-side account or "
            "product filter."
        )
    )


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
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
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
    fetched = await fetch_capital_flows(client, start_date=start_date, end_date=end_date)
    wanted_accounts = frozenset(account_ids) if account_ids is not None else None
    matched = tuple(
        row
        for row in fetched.rows
        if _flow_matches(row, owner_id=owner_id, account_ids=wanted_accounts)
    )
    subscription_count = sum(1 for row in matched if row.kind == "subscription")
    redemption_count = sum(1 for row in matched if row.kind == "redemption")
    unattributed_count = sum(1 for row in matched if row.unattributed)
    return CapitalFlowsResolvedResponse(
        request_count=fetched.request_count,
        flows=tuple(CapitalFlowRowResponse.from_dto(row) for row in matched[:max_rows]),
        total=len(matched),
        subscription_count=subscription_count,
        redemption_count=redemption_count,
        unattributed_count=unattributed_count,
        non_actual_count=fetched.rows_dropped,
        truncated=len(matched) > max_rows,
        scan_truncated=fetched.scan_truncated,
    )


def _flow_matches(
    row: CapitalFlowDto,
    *,
    owner_id: str | None,
    account_ids: frozenset[str] | None,
) -> bool:
    if owner_id is not None and (row.owner is None or row.owner.id != owner_id):
        return False
    return account_ids is None or (row.account is not None and row.account.id in account_ids)
