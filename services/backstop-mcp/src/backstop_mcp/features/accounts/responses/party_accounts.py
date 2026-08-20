"""`get_accounts_for_party`-specific response shape: what a party holds, with figures.

This module owns the *wording* of the provenance caveat. `HoldingListingDto` carries facts —
which endpoint answered, which fields that endpoint cannot produce — and the sentence the model
reads is composed here, because phrasing is a wire concern and the fetch layer should not have an
opinion about it.
"""

from datetime import date
from typing import Literal, Self

from pydantic import Field

from backstop_mcp.features.accounts.internal_dto import (
    HoldingListingDto,
    HoldingRowDto,
    MoneyDto,
    ShareDto,
)
from backstop_mcp.features.accounts.responses.shared import closed_hint
from backstop_mcp.features.party_resolver import ResolvedPartyResponse
from backstop_mcp.models import OmitNoneModel

_TABLE_CAVEAT = (
    "Figures came from Backstop's account-table endpoint, which is one request for the whole "
    "table. `balance` there is the account's latest value with no as-of date and no "
    "ACTUAL/ESTIMATE label — it can be a mid-month estimate and this payload cannot say. When "
    "the date or the status matters, call `get_time_series` on that account's `values`."
)


def _accounts_walk_caveat(omitted: tuple[str, ...]) -> str:
    return (
        "Backstop's account-table endpoint was unavailable, so this came from the documented "
        "/accounts walk plus per-account series. Not available on that path and omitted rather "
        f"than set to zero: {', '.join(omitted)} — do not answer questions about those fields "
        "from this payload. `funded_date` here is the account's start date, a near neighbour of "
        "the table endpoint's funded date rather than the same field. `balance` is the latest "
        "point that carries a number, so check `balance_as_of`: it can be months old when the "
        "newest point has no value yet."
    )


class MoneyResponse(OmitNoneModel):
    """A money figure, with Backstop's own rendering alongside the number."""

    amount: float | None = Field(
        default=None,
        description="The figure. A published 0.0 is a real zero, not 'unknown'.",
    )
    currency: str | None = Field(default=None, description="ISO currency code, e.g. `USD`.")
    formatted: str | None = Field(
        default=None,
        description=(
            "Backstop's own rendering. `-` means no figure is recorded, which `$0.00` does not — "
            "`amount` is 0.0 in both cases, so this is the only way to tell them apart. Absent "
            "when the figure came from the series fallback, which has no rendering."
        ),
    )

    @classmethod
    def from_dto(cls, money: MoneyDto | None) -> Self | None:
        if money is None:
            return None
        return cls(amount=money.amount, currency=money.currency, formatted=money.formatted)


class ShareResponse(OmitNoneModel):
    """A share-of-fund figure, as a fraction."""

    fraction: float | None = Field(
        default=None,
        description="A fraction, not a percentage: 0.796 is 79.6%.",
    )
    formatted: str | None = Field(
        default=None, description="Backstop's own rendering, e.g. `79.60%`."
    )

    @classmethod
    def from_dto(cls, share: ShareDto | None) -> Self | None:
        if share is None:
            return None
        return cls(fraction=share.fraction, formatted=share.formatted)


class HoldingFigureErrorResponse(OmitNoneModel):
    """A figure that could not be fetched, and why."""

    figure: str = Field(description="Which field is missing because its request failed.")
    message: str = Field(description="The upstream failure, for the caller to relay or retry.")


class HoldingRowResponse(OmitNoneModel):
    """One account this party holds, with its snapshot figures."""

    account_id: str = Field(
        description=(
            "Backstop account id. Pass this — never a product id — when asking for this "
            "account's series history."
        )
    )
    product_id: str | None = Field(
        default=None, description="The product this account is invested in."
    )
    product_short_name: str | None = Field(
        default=None,
        description=(
            "The tenant's own label for the product, e.g. `CIO2`. This is what the IR team says "
            "out loud; there is no full product name on this row."
        ),
    )
    investor_id: str | None = Field(
        default=None,
        description="The owning party. Echo with `investor_resource_type` as a later `party_id`.",
    )
    investor_resource_type: str | None = Field(
        default=None,
        description="Which collection `investor_id` belongs to: `organizations` or `people`.",
    )
    account_term_id: str | None = Field(
        default=None,
        description="The account-terms record, when the source path publishes one.",
    )
    other_id: str | None = Field(
        default=None, description="The tenant's own account reference, when recorded."
    )
    funded_date: date | None = Field(
        default=None,
        description=(
            "When the account was funded. Tenure is today minus this. Read the provenance "
            "caveat: on the fallback path this is the account's start date instead."
        ),
    )
    closed_date: date | None = Field(
        default=None, description="When the account closed. Absent while it is open."
    )
    closed: bool = Field(description="Whether this account is closed.")
    balance: MoneyResponse | None = Field(
        default=None,
        description=(
            "Current value of this holding. Omitted, never zeroed, when no figure is available — "
            "check `figure_errors` to tell a failed request from a genuinely unpublished number."
        ),
    )
    balance_as_of: date | None = Field(
        default=None,
        description=(
            "The date `balance` is for. Absent on the account-table path, which publishes no "
            "date at all; present on the fallback, where the figure can be months old."
        ),
    )
    balance_status: str | None = Field(
        default=None,
        description="`ACTUAL` or `ESTIMATE`, when the source path says which.",
    )
    commitment: MoneyResponse | None = Field(
        default=None, description="Total committed capital. Private-equity style accounts only."
    )
    unfunded_commitment: MoneyResponse | None = Field(
        default=None, description="Committed but not yet drawn."
    )
    percentage_of_product: ShareResponse | None = Field(
        default=None, description="This account's share of the product it is invested in."
    )
    percentage_of_master: ShareResponse | None = Field(
        default=None, description="This account's share of the master fund, when applicable."
    )
    figure_errors: tuple[HoldingFigureErrorResponse, ...] = Field(
        default=(),
        description=(
            "Figures whose request failed. An empty list with a missing figure means Backstop "
            "publishes no number for it, which is a different answer."
        ),
    )

    @classmethod
    def from_dto(cls, row: HoldingRowDto) -> Self:
        return cls(
            account_id=row.account_id,
            product_id=row.product_id,
            product_short_name=row.product_short_name,
            investor_id=row.investor_id,
            investor_resource_type=row.investor_resource_type,
            account_term_id=row.account_term_id,
            other_id=row.other_id,
            funded_date=row.funded_date,
            closed_date=row.closed_date,
            closed=row.closed,
            balance=MoneyResponse.from_dto(row.balance),
            balance_as_of=row.balance_as_of,
            balance_status=row.balance_status,
            commitment=MoneyResponse.from_dto(row.commitment),
            unfunded_commitment=MoneyResponse.from_dto(row.unfunded_commitment),
            percentage_of_product=ShareResponse.from_dto(row.percentage_of_product),
            percentage_of_master=ShareResponse.from_dto(row.percentage_of_master),
            figure_errors=tuple(
                HoldingFigureErrorResponse(figure=error.figure, message=error.message)
                for error in row.figure_errors
            ),
        )


class PartyAccountsResolvedResponse(OmitNoneModel):
    """`get_accounts_for_party` after the party was found and its holdings listed."""

    status: Literal["resolved"] = Field(
        default="resolved",
        description="Always 'resolved': the party was found and its holdings listed.",
    )
    resolved: ResolvedPartyResponse = Field(
        description=(
            "The identity this call settled on. Echo `id` / `search_type` / `name` as "
            "`party_id` later — never invent them."
        )
    )
    holdings: tuple[HoldingRowResponse, ...] = Field(
        description="The accounts this party owns, across products, with their snapshot figures."
    )
    source: Literal["table-api", "accounts-api"] = Field(
        description=(
            "Which Backstop endpoint answered. `table-api` is the account-table endpoint, one "
            "request with every figure. `accounts-api` is the documented fallback, which carries "
            "fewer fields — `data_caveat` says which."
        )
    )
    data_caveat: str = Field(
        description=(
            "What this payload can and cannot be used to answer, given `source`. Read it before "
            "reporting a figure as current or a missing figure as zero."
        )
    )
    open_count: int | None = Field(
        default=None,
        description="Open accounts this party holds, as Backstop counts them.",
    )
    all_count: int | None = Field(
        default=None,
        description=(
            "All accounts this party holds, open and closed, before `include_closed` filtering. "
            "Can legitimately exceed the number of rows returned."
        ),
    )
    closed_count: int | None = Field(
        default=None, description="Closed accounts this party holds, as Backstop counts them."
    )
    closed_omitted: int = Field(
        description=(
            "How many owned accounts were dropped because `include_closed` is false. "
            "Distinguishes a party with no accounts from one whose accounts are all closed."
        )
    )
    include_closed_hint: str | None = Field(
        default=None,
        description=(
            "Set when closed accounts were omitted. Pass `include_closed=true` rather than "
            "treating an empty list as 'this party owns nothing'."
        ),
    )
    rows_dropped: int | None = Field(
        default=None,
        description=(
            "Rows the account-table endpoint returned that carried no account id and were "
            "skipped. Non-zero means its shape has moved and this listing is incomplete."
        ),
    )

    @classmethod
    def from_holdings(cls, listing: HoldingListingDto, *, resolved: ResolvedPartyResponse) -> Self:
        return cls(
            resolved=resolved,
            holdings=tuple(HoldingRowResponse.from_dto(row) for row in listing.rows),
            source=listing.source,
            data_caveat=(
                _TABLE_CAVEAT
                if listing.source == "table-api"
                else _accounts_walk_caveat(listing.omitted_fields)
            ),
            open_count=listing.open_count,
            all_count=listing.all_count,
            closed_count=listing.closed_count,
            closed_omitted=listing.closed_omitted,
            include_closed_hint=closed_hint(
                closed_omitted=listing.closed_omitted,
                returned=len(listing.rows),
                subject="party",
            ),
            rows_dropped=listing.rows_dropped or None,
        )
