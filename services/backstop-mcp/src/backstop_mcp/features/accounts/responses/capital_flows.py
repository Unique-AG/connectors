"""Subscriptions and redemptions in a date window — the `get_capital_flows` published shape."""

from datetime import date
from typing import Literal, Self

from pydantic import Field

from backstop_mcp.backstop_client import IncludedResource
from backstop_mcp.features.accounts.api_responses import AccountAttributes, OwnerAttributes
from backstop_mcp.models import OmitNoneModel

# Scan ceiling per collection. 1,244 subscriptions since 2020 on this instance, so this is
# ~8x headroom; past it the walk stops and says so rather than accumulating every row of a
# collection this tool cannot filter server-side.
MAX_CAPITAL_FLOW_SCAN_RECORDS = 10_000


class CapitalFlowPartyResponse(OmitNoneModel):
    """An account or owning party on a flow row."""

    id: str = Field(description="Backstop id. Echo it; never invent one.")
    name: str | None = Field(default=None, description="Name as published on the include.")
    resource_type: str | None = Field(
        default=None, description="JSON:API type: accounts, contacts, organizations, or people."
    )

    @classmethod
    def from_account(cls, account: IncludedResource[AccountAttributes] | None) -> Self | None:
        if account is None:
            return None
        return cls(id=account.id, name=account.attributes.name, resource_type=account.type)

    @classmethod
    def from_owner(cls, owner: IncludedResource[OwnerAttributes] | None) -> Self | None:
        if owner is None:
            return None
        return cls(id=owner.id, name=owner.attributes.name, resource_type=owner.type)


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
