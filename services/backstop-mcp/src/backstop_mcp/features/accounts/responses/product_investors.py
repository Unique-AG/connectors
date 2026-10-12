"""`get_product_investors` response: each product's accounts, and each investor across them.

Two views of the same rows, so nothing has to be joined by the reader:

- `products` — one listing per vehicle, holding that vehicle's accounts. One product and ten
  products are the same shape.
- `investors` — one entry per owner, with a holding per vehicle they are in.

`longest_tenure_runs` and `longest_held_today` rank the investors' runs here, so a tenure
question is read off the response rather than sorted by the reader.

Figures appear only when the caller passed `include_latest_value`: each account's latest value,
and totals per holding and per investor, summed by currency. Totals never mix currencies.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Literal, Self

from pydantic import Field

from backstop_mcp.features.accounts.internal_dto import AccountSpanDto, TenureDto
from backstop_mcp.features.accounts.responses.shared import (
    TENURE_RUNS_DESCRIPTION,
    AccountRowResponse,
    OwnerResponse,
    ProductRefResponse,
    TenureRunResponse,
)
from backstop_mcp.models import OmitNoneModel


class ValueTotalResponse(OmitNoneModel):
    """Latest values in one currency, summed across some accounts."""

    currency: str | None = Field(
        default=None, description="ISO currency code. Omitted when the accounts carry none."
    )
    amount: float = Field(description="Sum of the valued accounts' latest `amount`.")
    account_count: int = Field(description="How many accounts carried a value in this sum.")
    oldest_as_of: date = Field(description="Earliest `as_of` among the summed accounts.")
    newest_as_of: date = Field(
        description=(
            "Latest `as_of` among the summed accounts. When it differs from `oldest_as_of`, "
            "the total mixes dates — say so."
        )
    )


_TOTALS_DESCRIPTION = (
    "Only with `include_latest_value=true`: latest values summed per currency. Accounts with no "
    "figure are not in the sum — check their `latest_value`."
)


class ProductListingResponse(OmitNoneModel):
    """One product and the accounts in it."""

    product: ProductRefResponse = Field(
        description=(
            "The vehicle. Echo `id` as `entity_id` with `entity_type='products'` on "
            "`get_time_series` for fund-level AUM — never invent one."
        )
    )
    accounts: tuple[AccountRowResponse, ...] = Field(
        description=(
            "Investor accounts in this product. Echo each `id` as `entity_id` with "
            "`entity_type='accounts'` on `get_time_series` for a dated figure."
        )
    )
    closed_omitted: int = Field(
        description=(
            "How many of this product's accounts were dropped because `include_closed` is "
            "false. Distinguishes a product with no investors from one whose accounts are all "
            "closed."
        )
    )
    include_closed_hint: str | None = Field(
        default=None,
        description=(
            "Set when closed accounts were omitted. Pass `include_closed=true` rather than "
            "treating an empty list as 'this product has no investors'."
        ),
    )


class ProductAccountsResponse(OmitNoneModel):
    """`GetAccountsForProductQuery`'s payload: the published listing, and the owners' spans.

    Not published itself. `get_product_investors` publishes `listing` and turns
    `spans_by_owner` into each investor's `tenure_runs`.
    """

    listing: ProductListingResponse = Field(
        description="The product's accounts after the open/closed split."
    )
    spans_by_owner: dict[str, tuple[AccountSpanDto, ...]] = Field(
        description=(
            "Every listed owner's account spans in this product, keyed by owner id and taken "
            "before the open/closed split, so closed accounts count toward tenure."
        )
    )
    owners: dict[str, OwnerResponse] = Field(
        description=(
            "Every owner of this product's accounts, keyed by owner id and taken before the "
            "open/closed split, so an owner whose accounts are all closed is still named."
        )
    )


class InvestorHoldingResponse(OmitNoneModel):
    """What one investor holds in one product."""

    product_id: str = Field(description="The product, as in `products[].product.id`.")
    product_short_name: str | None = Field(
        default=None, description="That product's short name, e.g. `NWON`."
    )
    account_ids: tuple[str, ...] = Field(
        description="This investor's accounts in that product, as in `products[].accounts[].id`."
    )
    latest_value_totals: tuple[ValueTotalResponse, ...] | None = Field(
        default=None, description=_TOTALS_DESCRIPTION
    )


class InvestorResponse(OmitNoneModel):
    """One owner across every product in this response."""

    id: str = Field(description="Backstop id of the owning person or organization.")
    name: str | None = Field(
        default=None,
        description="Display name of the owning person or organization. Omitted when unknown.",
    )
    resource_type: str | None = Field(
        default=None,
        description=(
            "What the owner is: `organizations`, `people`, or `contacts`. Echo it with `id` "
            "on a later party resolve."
        ),
    )
    has_open_account: bool = Field(
        description=(
            "Whether this investor has an open account in these products. False for an investor "
            "that has left: every account here is closed. An account with a "
            "closed date after today counts as closed here although its run is held today: "
            "read `tenure_runs` for that."
        )
    )
    holdings: tuple[InvestorHoldingResponse, ...] = Field(
        description=(
            "One entry per product this investor has listed accounts in, in `products` order. "
            "Empty for an investor with no open account here unless `include_closed=true`: its "
            "closed rows are omitted — read `has_open_account` and `tenure_runs`, not 'never "
            "held'."
        )
    )
    tenure_runs: tuple[TenureRunResponse, ...] | None = Field(
        default=None,
        description=(
            "Every unbroken stretch this investor held these products, from all its accounts in "
            "them — including a move from one product here to another. Covers only the products "
            f"in this call. {TENURE_RUNS_DESCRIPTION} One entry per Backstop owner: related "
            "parties are not merged. Omitted when no dated account has started."
        ),
    )
    tenure_undated_accounts: int | None = Field(
        default=None,
        description=(
            "This investor's accounts left out of `tenure_runs` because they have no start "
            "date, are closed with no closed date, or closed before they started. Say so when "
            "quoting tenure: they could make it longer. Omitted when none."
        ),
    )
    latest_value_totals: tuple[ValueTotalResponse, ...] | None = Field(
        default=None,
        description=(
            f"{_TOTALS_DESCRIPTION} Summed across every holding — rank investors by this "
            "rather than adding account figures yourself."
        ),
    )


def investors_from_listings(
    listings: Sequence[ProductListingResponse],
    *,
    tenure: Mapping[str, TenureDto],
    open_owner_ids: frozenset[str],
    owners_without_rows: Mapping[str, OwnerResponse],
) -> tuple[InvestorResponse, ...]:
    """One entry per owner id, first-seen order. Owners are not rolled up to a parent.

    Accounts with no owner stay in their product listing and are not an investor here.
    `owners_without_rows` are appended with no holdings unless their rows already listed them.
    Totals are set only when the rows carry `latest_value`. `tenure` and `open_owner_ids` are
    taken before the open/closed split, so they are not derived from these rows.
    """
    valued = any(
        account.latest_value is not None for listing in listings for account in listing.accounts
    )
    owners: dict[str, OwnerResponse] = {}
    holdings: dict[str, list[tuple[ProductRefResponse, list[AccountRowResponse]]]] = {}
    for listing in listings:
        for account in listing.accounts:
            owner = account.owner
            if owner is None:
                continue
            owners.setdefault(owner.id, owner)
            held = holdings.setdefault(owner.id, [])
            if not held or held[-1][0].id != listing.product.id:
                held.append((listing.product, []))
            held[-1][1].append(account)
    for owner_id, owner in owners_without_rows.items():
        owners.setdefault(owner_id, owner)
        holdings.setdefault(owner_id, [])
    return tuple(
        InvestorResponse(
            id=owner_id,
            name=owner.name,
            resource_type=owner.resource_type,
            has_open_account=owner_id in open_owner_ids,
            holdings=tuple(
                InvestorHoldingResponse(
                    product_id=product.id,
                    product_short_name=product.short_name,
                    account_ids=tuple(account.id for account in accounts),
                    latest_value_totals=_totals(accounts) if valued else None,
                )
                for product, accounts in holdings[owner_id]
            ),
            tenure_runs=_tenure_runs(_owner_tenure(tenure, owner_id)),
            tenure_undated_accounts=_owner_tenure(tenure, owner_id).undated_accounts or None,
            latest_value_totals=(
                _totals([account for _, accounts in holdings[owner_id] for account in accounts])
                if valued
                else None
            ),
        )
        for owner_id, owner in owners.items()
    )


class InvestorTenureRunResponse(TenureRunResponse):
    """One investor's run, ranked against the other investors' runs in this response."""

    investor_id: str = Field(description="The investor, as in `investors[].id`.")
    investor_name: str | None = Field(
        default=None, description="That investor's name. Omitted when unknown."
    )

    @classmethod
    def from_run(cls, investor: InvestorResponse, run: TenureRunResponse) -> Self:
        return cls(
            investor_id=investor.id,
            investor_name=investor.name,
            start=run.start,
            end=run.end,
            years=run.years,
            held_today=run.held_today,
        )


_LONGEST_TENURE_COUNT = 5


def longest_tenure_runs(
    investors: Sequence[InvestorResponse],
) -> tuple[InvestorTenureRunResponse, ...] | None:
    """Each investor's longest run, leavers included, longest first; the more recent on a tie."""
    runs = [
        InvestorTenureRunResponse.from_run(investor, investor.tenure_runs[0])
        for investor in investors
        if investor.tenure_runs
    ]
    ranked = sorted(runs, key=lambda run: (run.years, run.start), reverse=True)
    return tuple(ranked[:_LONGEST_TENURE_COUNT]) or None


def longest_held_today(investors: Sequence[InvestorResponse]) -> InvestorTenureRunResponse | None:
    """The longest run still held today, across every investor; the more recent on a tie."""
    held = [
        InvestorTenureRunResponse.from_run(investor, run)
        for investor in investors
        for run in investor.tenure_runs or ()
        if run.held_today
    ]
    return max(held, key=lambda run: (run.years, run.start), default=None)


def _owner_tenure(tenure: Mapping[str, TenureDto], owner_id: str) -> TenureDto:
    owner_tenure = tenure.get(owner_id)
    assert owner_tenure is not None, f"no tenure computed for listed owner {owner_id}"
    return owner_tenure


def _tenure_runs(tenure: TenureDto) -> tuple[TenureRunResponse, ...] | None:
    return tuple(TenureRunResponse.from_dto(run) for run in tenure.runs) or None


def _totals(accounts: Sequence[AccountRowResponse]) -> tuple[ValueTotalResponse, ...]:
    by_currency: dict[str | None, list[tuple[float, date]]] = {}
    for account in accounts:
        latest = account.latest_value
        if latest is None or latest.amount is None or latest.as_of is None:
            continue
        by_currency.setdefault(latest.currency, []).append((latest.amount, latest.as_of))
    return tuple(
        ValueTotalResponse(
            currency=currency,
            amount=sum(amount for amount, _ in points),
            account_count=len(points),
            oldest_as_of=min(as_of for _, as_of in points),
            newest_as_of=max(as_of for _, as_of in points),
        )
        for currency, points in by_currency.items()
    )


class ProductInvestorsResolvedResponse(OmitNoneModel):
    """Each product's accounts, and each investor across them. Latest values only when asked."""

    status: Literal["resolved"] = Field(
        default="resolved",
        description="Always 'resolved': the products were found and their accounts listed.",
    )
    products: tuple[ProductListingResponse, ...] = Field(
        description=(
            "One listing per product, in the order resolved. A fund name covers every vehicle "
            "it matched, so one name can produce several listings."
        )
    )
    investors: tuple[InvestorResponse, ...] = Field(
        description=(
            "One entry per investor across every product here — use this to organize by "
            "investor rather than by account. An investor in two vehicles appears once, with a "
            "holding per vehicle. Investors who have left are listed too, with "
            "`has_open_account: false`: leave them out of a count of who holds these products "
            "today, but not out of tenure — see `longest_tenure_runs`."
        )
    )
    longest_tenure_runs: tuple[InvestorTenureRunResponse, ...] | None = Field(
        default=None,
        description=(
            f"Up to {_LONGEST_TENURE_COUNT} investors ranked by their longest unbroken run in "
            "these products, longest first. Investors who have left are ranked too: read "
            "`held_today`. Runs are already merged across closed and reopened accounts. Omitted "
            "when no investor has a dated run."
        ),
    )
    longest_held_today: InvestorTenureRunResponse | None = Field(
        default=None,
        description=(
            "The longest run still held today, across every investor here — the longest-standing "
            "current investor. Can differ from `longest_tenure_runs[0]` when that investor has "
            "left. Omitted when no run is held today."
        ),
    )
    latest_value_hint: str | None = Field(
        default=None,
        description=(
            "Set when `include_latest_value=true` was passed but no values were fetched: why, "
            "how to narrow the call, and which other tools can size the investors instead. Do "
            "not fall back to calling get_time_series on every account."
        ),
    )
    investor_ids_not_found: tuple[str, ...] | None = Field(
        default=None,
        description=(
            "Ids passed in `investor_ids` with no account here, open or closed: they never held "
            "these products, or hold them under another party record. One with only closed "
            "accounts is in `investors` with `has_open_account: false`. Omitted when "
            "`investor_ids` was not passed."
        ),
    )
