"""MCP-facing account and product shapes for the two positions tools.

Every field carries a description so FastMCP can publish it. `OmitNoneModel` drops nulls:
a missing figure is absent, never `0.0`. A `0.0` Backstop published is a real point and is kept.
"""

from datetime import date as Date
from typing import Literal

from pydantic import Field

from backstop_mcp.features.accounts.types import (
    AccountOwner,
    AccountPosition,
    AccountRecord,
    InvestorType,
    ProductPositions,
    ResolvedProduct,
    SeriesError,
    SeriesName,
    SeriesPoint,
)
from backstop_mcp.features.resolution import (
    AmbiguousResponse,
    Candidate,
    CandidateResponse,
    NotFoundResponse,
    Unresolved,
    unresolved_response,
)
from backstop_mcp.models import OmitNoneModel


class ProductCandidateResponse(CandidateResponse):
    """One ambiguous product match. Echo `id` as `product_id` — never invent one."""

    key: str = Field(
        description=(
            "Stable identity for this candidate. Echo it only as part of picking this option "
            "— it is not a Backstop product id."
        )
    )
    label: str = Field(
        description=(
            "What to show the user when asking which product they meant, usually "
            "'Name (SHORT)' — e.g. 'Capstone Global Unconstrained Portfolio (CGUP)'."
        )
    )
    id: str = Field(
        description=(
            "Backstop product id. Echo it as `product_id` on the next call — never invent one."
        )
    )
    name: str | None = Field(
        default=None,
        description="Product name as Backstop stores it. Omitted when the index had none.",
    )
    short_name: str | None = Field(
        default=None,
        description="`productShortName` (e.g. 'CGUP'). Omitted when the product has none.",
    )


class ProductAmbiguousResponse(AmbiguousResponse[ProductCandidateResponse]):
    """Returned when more than one product matched and none was chosen.

    Show each candidate's `label` to the user, then retry with that `id` as `product_id`.
    """

    scope: str = Field(
        description="Collection the query was resolved against. Always 'products' for this tool."
    )
    candidates: list[ProductCandidateResponse] = Field(
        default_factory=list,
        description=(
            "The matching products. Show `label` to the user, then retry with that "
            "candidate's `id` as `product_id` — never invent one."
        ),
    )


class ProductRefResponse(OmitNoneModel):
    """A product identity: id, name, and short name."""

    id: str = Field(
        description=(
            "Backstop product id. Echo it as `product_id` on `get_product_positions` — never "
            "invent one."
        )
    )
    name: str | None = Field(default=None, description="Product name as Backstop stores it.")
    short_name: str | None = Field(
        default=None,
        description=(
            "`productShortName` (e.g. 'CGUP'). Tenants may call this a fund, vehicle, or "
            "share class."
        ),
    )


class OwnerResponse(OmitNoneModel):
    """The party on the account — identity only, not the contact-card dump."""

    id: str = Field(description="Backstop id of the owning person or organization.")
    name: str | None = Field(
        default=None,
        description="Display name of the owning person or organization. Omitted when unknown.",
    )
    resource_type: str | None = Field(
        default=None,
        description=(
            "What the owner is: `organizations`, `people`, or `contacts`. Organization owners "
            "arrive as contacts whose type is `organizations`."
        ),
    )


class InvestorTypeResponse(OmitNoneModel):
    """The account's investor type, identity only."""

    id: str = Field(description="Backstop investor-type id.")
    name: str | None = Field(default=None, description="Investor-type name, e.g. 'Fund of Funds'.")


class FigureResponse(OmitNoneModel):
    """One latest series point: the number, the day it is as-of, and status when Backstop sent it.

    `value_status` is omitted when Backstop omitted it — do not read that as `ACTUAL`. Recent
    `values` points are often `ESTIMATE`.
    """

    value: float | None = Field(
        default=None,
        description=(
            "The point's amount, in the account's `currency`. `0.0` is a real published zero, "
            "not a missing series."
        ),
    )
    date: Date = Field(description="The day this point is as-of. Each figure has its own date.")
    value_status: str | None = Field(
        default=None,
        description=(
            "Backstop's `valueStatus` when present (`ESTIMATE` / `ACTUAL`). Omitted when "
            "Backstop did not send one — not defaulted to `ACTUAL`."
        ),
    )


class SeriesErrorResponse(OmitNoneModel):
    """One series that failed for this account. Other figures on the row may still be present."""

    series: SeriesName = Field(
        description="Which series failed: `values`, `totalInvested`, or `totalRedemptions`."
    )
    message: str = Field(description="Why that series could not be read.")


class AccountRowResponse(OmitNoneModel):
    """One account: identity, owner, status, and the product when it was side-loaded."""

    id: str = Field(description="Backstop account id. Distinct from the owner's party id.")
    name: str | None = Field(default=None, description="Account name as Backstop stores it.")
    owner: OwnerResponse | None = Field(
        default=None,
        description="The party on this account. Omitted when the owner include was missing.",
    )
    investor_type: InvestorTypeResponse | None = Field(
        default=None,
        description=(
            "How Backstop classifies this investor (e.g. 'Fund of Funds'). Omitted when that "
            "include was missing."
        ),
    )
    product: ProductRefResponse | None = Field(
        default=None,
        description=(
            "The product this account is a position in. Present on `get_accounts_for_party`; "
            "omitted on `get_product_positions` (that call already named the product)."
        ),
    )
    currency: str | None = Field(
        default=None,
        description="ISO currency code the account's figures are in, e.g. 'USD'.",
    )
    account_start_date: Date | None = Field(
        default=None, description="Day the account opened, when Backstop has one."
    )
    closed_date: Date | None = Field(
        default=None,
        description=(
            "Day the account closed. Omitted when the account is open (`closedDate` absent)."
        ),
    )
    ownership_type: str | None = Field(
        default=None,
        description=(
            "How the investor holds the account, as Backstop stores it (e.g. 'Direct'). "
            "Omitted when unset."
        ),
    )
    investor_qualification: str | None = Field(
        default=None,
        description=(
            "Investor accreditation as Backstop stores it (e.g. 'QP' for qualified purchaser). "
            "Omitted when unset."
        ),
    )
    is_employee_account: bool | None = Field(
        default=None,
        description=(
            "True when Backstop marks this as an employee of the manager, not an external investor."
        ),
    )
    is_gp_account: bool | None = Field(
        default=None,
        description=(
            "True when Backstop marks this as a general-partner (GP) account — the manager's "
            "own capital, not an external investor."
        ),
    )
    aml_check_complete: bool | None = Field(
        default=None,
        description=("True when Backstop marks anti-money-laundering (AML) checks as complete."),
    )
    new_issue_eligible: bool | None = Field(
        default=None,
        description=(
            "True when Backstop marks the account eligible for new-issue securities (IPOs)."
        ),
    )
    us_domiciled: bool | None = Field(
        default=None,
        description="True when Backstop marks the account as domiciled in the United States.",
    )
    is_open: bool = Field(
        description="True when `closedDate` was absent on the account. A present null is closed."
    )


class PositionRowResponse(AccountRowResponse):
    """An account row plus current balance, lifetime invested, and lifetime redemptions."""

    balance: FigureResponse | None = Field(
        default=None,
        description=(
            "Latest `values` point (current balance). Omitted when the series has no points — "
            "never replaced with `0.0`."
        ),
    )
    invested: FigureResponse | None = Field(
        default=None,
        description=(
            "Latest `totalInvested` point (lifetime cumulative). Omitted when the series has "
            "no points — never replaced with `0.0`."
        ),
    )
    redemptions: FigureResponse | None = Field(
        default=None,
        description=(
            "Latest `totalRedemptions` point (lifetime cumulative). Omitted when the series "
            "has no points — never replaced with `0.0`."
        ),
    )
    errors: tuple[SeriesErrorResponse, ...] | None = Field(
        default=None,
        description=(
            "Series that failed for this account. Other figures on the row may still be present. "
            "Omitted when every requested series succeeded or was empty."
        ),
    )


def product_candidate_response(candidate: Candidate[ResolvedProduct]) -> ProductCandidateResponse:
    product = candidate.value
    return ProductCandidateResponse(
        key=candidate.key,
        label=candidate.label,
        id=product.id,
        name=product.name,
        short_name=product.short_name,
    )


def unresolved_product_response(
    result: Unresolved[ResolvedProduct],
) -> ProductAmbiguousResponse | NotFoundResponse:
    return unresolved_response(
        result,
        ambiguous_model=ProductAmbiguousResponse,
        to_candidate=product_candidate_response,
    )


def product_ref_response(product: ResolvedProduct) -> ProductRefResponse:
    return ProductRefResponse(id=product.id, name=product.name, short_name=product.short_name)


def figure_response(point: SeriesPoint | None) -> FigureResponse | None:
    if point is None:
        return None
    return FigureResponse(value=point.value, date=point.date, value_status=point.value_status)


def owner_response(owner: AccountOwner | None) -> OwnerResponse | None:
    if owner is None:
        return None
    return OwnerResponse(id=owner.id, name=owner.name, resource_type=owner.resource_type)


def investor_type_response(investor_type: InvestorType | None) -> InvestorTypeResponse | None:
    if investor_type is None:
        return None
    return InvestorTypeResponse(id=investor_type.id, name=investor_type.name)


def account_row_response(account: AccountRecord) -> AccountRowResponse:
    return AccountRowResponse.model_validate(
        {
            **account.model_dump(),
            "owner": owner_response(account.owner),
            "investor_type": investor_type_response(account.investor_type),
            "product": product_ref_response(account.product) if account.product else None,
        }
    )


def _series_errors(errors: tuple[SeriesError, ...]) -> tuple[SeriesErrorResponse, ...] | None:
    if not errors:
        return None
    return tuple(
        SeriesErrorResponse(series=error.series, message=error.message) for error in errors
    )


def position_row_response(position: AccountPosition) -> PositionRowResponse:
    row = account_row_response(position.account)
    return PositionRowResponse.model_validate(
        {
            **row.model_dump(),
            "balance": figure_response(position.balance),
            "invested": figure_response(position.invested),
            "redemptions": figure_response(position.redemptions),
            "errors": _series_errors(position.errors),
        }
    )


def product_positions_response(result: ProductPositions) -> "ProductPositionsResolvedResponse":
    hint = None
    if result.closed_omitted and not result.accounts:
        hint = (
            "This product has accounts, but all of them are closed. Pass include_closed=true "
            "to list them."
        )
    elif result.closed_omitted:
        hint = (
            f"{result.closed_omitted} closed account(s) were omitted. Pass include_closed=true "
            "to include them."
        )
    return ProductPositionsResolvedResponse(
        product=product_ref_response(result.product),
        accounts=tuple(position_row_response(position) for position in result.accounts),
        closed_omitted=result.closed_omitted,
        aum=figure_response(result.aum),
        aum_diverges=result.aum_diverges,
        include_closed_hint=hint,
    )


class ProductPositionsResolvedResponse(OmitNoneModel):
    """`get_product_positions` after the product was found and its accounts fetched.

    An empty `accounts` list with `closed_omitted=0` means the product has no accounts. An empty
    list with `closed_omitted>0` means every account is closed — read `include_closed_hint`.
    """

    status: Literal["resolved"] = Field(
        default="resolved",
        description="Always 'resolved': the product was found and its accounts fetched.",
    )
    product: ProductRefResponse = Field(
        description=(
            "The product this call settled on. Echo `id` as `product_id` later — never invent one."
        )
    )
    accounts: tuple[PositionRowResponse, ...] = Field(
        description=(
            "Positions in this product. Each figure is `{value, date, valueStatus?}` from "
            "`values` (balance), `totalInvested`, and `totalRedemptions`. Omitted figures "
            "had no points, not a zero."
        )
    )
    closed_omitted: int = Field(
        description=(
            "How many matching accounts were dropped because `include_closed` is false. "
            "Distinguishes a product with no accounts from one whose accounts are all closed."
        )
    )
    aum: FigureResponse | None = Field(
        default=None,
        description=(
            "Latest assets under management (AUM) for the product: the product's total reported "
            "value, not one investor's balance. From `/products/{id}/aums`. Omitted when none "
            "was found."
        ),
    )
    aum_diverges: bool = Field(
        description=(
            "True when a latest assets-under-management (AUM) figure exists and does not match "
            "the sum of returned account balances. Usually closed-but-still-valued accounts "
            "excluded by the open default. Not a hard failure."
        )
    )
    include_closed_hint: str | None = Field(
        default=None,
        description=(
            "Set when closed accounts were omitted. Tells the caller to pass "
            "`include_closed=true` rather than treating an empty list as 'no investors'."
        ),
    )
