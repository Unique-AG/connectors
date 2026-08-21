"""`get_capital_flows`: subscriptions and redemptions in a mandatory date window."""

from datetime import date
from typing import Annotated, Literal, Self

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client
from backstop_mcp.features.accounts import CapitalFlowDto, fetch_capital_flows
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
            "True when a redemption could not be tied to an account through "
            "originalSubscription.fundAccount. That is an orphan, not a dropped row."
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
        description="Always 2: one subscriptions walk and one redemptions walk."
    )
    flows: tuple[CapitalFlowRowResponse, ...] = Field(
        description="Actuals newest-first by transaction_date. Capped at max_rows."
    )
    total: int = Field(description="Actuals in the window before the row cap.")
    subscription_count: int = Field(description="How many of `total` are subscriptions.")
    redemption_count: int = Field(description="How many of `total` are redemptions.")
    unattributed_count: int = Field(
        description="Redemptions that could not be tied to an account. Included in `flows`."
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
                "Inclusive start of filter[transactionDate]. Required — an unfiltered read "
                "is 400."
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
            description="Row cap. Counts on the response are over the uncapped actuals.",
        ),
    ] = _DEFAULT_MAX_ROWS,
    client: BackstopClient = Depends(get_backstop_client),
) -> CapitalFlowsResolvedResponse:
    """Subscriptions and redemptions in a date window — also the only share-class source.

    Always pass `start_date` and `end_date`; Backstop refuses an unfiltered read. Two calls.
    Actuals only (`COMPLETED`). A redemption has no account of its own and is attributed
    through `originalSubscription`; when that chain is missing the row is `unattributed`,
    not omitted. `share_class` / `share_series` live on the subscription, not the account.
    """
    if start_date > end_date:
        raise ValueError("start_date must not be after end_date")
    fetched = await fetch_capital_flows(client, start_date=start_date, end_date=end_date)
    subscription_count = sum(1 for row in fetched.rows if row.kind == "subscription")
    redemption_count = sum(1 for row in fetched.rows if row.kind == "redemption")
    unattributed_count = sum(1 for row in fetched.rows if row.unattributed)
    return CapitalFlowsResolvedResponse(
        request_count=fetched.request_count,
        flows=tuple(CapitalFlowRowResponse.from_dto(row) for row in fetched.rows[:max_rows]),
        total=len(fetched.rows),
        subscription_count=subscription_count,
        redemption_count=redemption_count,
        unattributed_count=unattributed_count,
    )
