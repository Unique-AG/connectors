"""`get_product_investors` response: each product's accounts, and each investor across them.

Two views of the same rows, so nothing has to be joined by the reader:

- `products` — one listing per vehicle, holding that vehicle's accounts. One product and ten
  products are the same shape.
- `investors` — one entry per owner, with a holding per vehicle they are in.

Figures appear only when the caller passed `include_latest_value`: each account's latest value,
and totals per holding and per investor, summed by currency. Totals never mix currencies.
"""

from collections.abc import Sequence
from datetime import date
from typing import Literal

from pydantic import Field

from backstop_mcp.features.accounts.responses.shared import (
    AccountRowResponse,
    OwnerResponse,
    ProductRefResponse,
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
    holdings: tuple[InvestorHoldingResponse, ...] = Field(
        description="One entry per product this investor is in, in `products` order."
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
) -> tuple[InvestorResponse, ...]:
    """One entry per owner id, first-seen order. Owners are not rolled up to a parent.

    Accounts with no owner stay in their product listing and are not an investor here.
    Totals are set only when the rows carry `latest_value`.
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
    return tuple(
        InvestorResponse(
            id=owner_id,
            name=owner.name,
            resource_type=owner.resource_type,
            holdings=tuple(
                InvestorHoldingResponse(
                    product_id=product.id,
                    product_short_name=product.short_name,
                    account_ids=tuple(account.id for account in accounts),
                    latest_value_totals=_totals(accounts) if valued else None,
                )
                for product, accounts in holdings[owner_id]
            ),
            latest_value_totals=(
                _totals([account for _, accounts in holdings[owner_id] for account in accounts])
                if valued
                else None
            ),
        )
        for owner_id, owner in owners.items()
    )


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
            "holding per vehicle."
        )
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
            "Ids passed in `investor_ids` with no account listed here: they hold none of these "
            "products, only closed accounts (see `closed_omitted`), or hold them under another "
            "party record. Not a zero balance. Omitted when `investor_ids` was not passed."
        ),
    )
