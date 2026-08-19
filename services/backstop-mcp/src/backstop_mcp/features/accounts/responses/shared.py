"""The account-row and figure vocabulary shared by both positions tools.

A caller comparing `get_product_positions` to `get_accounts_for_party` is reading one
vocabulary: the account row, the closed-account hint, and the figure shape live here rather
than being duplicated per tool. `OmitNoneModel` drops nulls: a missing figure is absent, never
`0.0`. A `0.0` Backstop published is a real point and is kept.
"""

from datetime import date as Date

from pydantic import Field

from backstop_mcp.features.accounts.api_responses import InvestorQualificationAttributes
from backstop_mcp.features.accounts.internal_dto import (
    AccountOwnerDto,
    AccountPositionDto,
    AccountRecordDto,
    InvestorTypeDto,
    ResolvedProductDto,
    SeriesErrorDto,
    SeriesFigureDto,
    SeriesName,
)
from backstop_mcp.models import OmitNoneModel


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


class InvestorQualificationResponse(OmitNoneModel):
    """Backstop's `investorQualification` object on the account."""

    status: str | None = Field(
        default=None,
        description=(
            "Regulatory status Backstop stored (e.g. 'REG_UNKNOWN'). Omitted when Backstop "
            "did not send one."
        ),
    )
    option: str | None = Field(
        default=None,
        description=(
            "Qualification option Backstop stored (e.g. 'UNKNOWN'). Omitted when Backstop "
            "did not send one."
        ),
    )


class UnvaluedPointResponse(OmitNoneModel):
    """A dated point Backstop has published without a number yet (its UI shows `-`)."""

    date: Date = Field(description="The day Backstop has a point for but no value on.")
    value_status: str | None = Field(
        default=None,
        description="Backstop's `valueStatus` on that point when it sent one.",
    )


class FigureResponse(OmitNoneModel):
    """One series figure: the number, the day it is as-of, and status when Backstop sent it.

    This is the latest point on the series that carries a value — not blindly the latest point.
    Backstop publishes a dated row before the number lands, and reporting that row would turn a
    live position into "no data". When the newest row is one of those, it is reported separately
    as `newer_point_without_value` and this figure stays the last real number.

    `value_status` is omitted when Backstop omitted it — do not read that as `ACTUAL`. Recent
    `values` points are often `ESTIMATE`.
    """

    value: float | None = Field(
        default=None,
        description=(
            "The point's amount, in the account's `currency`. `0.0` is a real published zero, "
            "not a missing series. Absent means no point in the fetched page carries a number "
            "yet — `date` is then the newest dated point, not an amount you can report."
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
    newer_point_without_value: UnvaluedPointResponse | None = Field(
        default=None,
        description=(
            "Set when Backstop has a *newer* dated point on this series with no number on it "
            "yet. `value` and `date` above are the latest point that does carry a number, so "
            "the figure is real but stale — say so rather than reporting it as current."
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
    investor_qualification: InvestorQualificationResponse | None = Field(
        default=None,
        description=(
            "Investor accreditation as `{status?, option?}`. Omitted when Backstop did not "
            "send the object."
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
    new_issue_eligible: str | None = Field(
        default=None,
        description=(
            "New-issue (IPO) eligibility as Backstop stores it (`ELIGIBLE`, `NOT_ELIGIBLE`, "
            "`N/A`, `UNKNOWN`). Omitted when unset."
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


def product_ref_response(product: ResolvedProductDto) -> ProductRefResponse:
    return ProductRefResponse(id=product.id, name=product.name, short_name=product.short_name)


def figure_response(figure: SeriesFigureDto | None) -> FigureResponse | None:
    """Report the latest valued point, naming the newer valueless one when there is one."""
    if figure is None:
        return None
    reported = figure.valued if figure.valued is not None else figure.latest
    newer = (
        UnvaluedPointResponse(date=figure.latest.date, value_status=figure.latest.value_status)
        if figure.valued is not None and figure.latest.value is None
        else None
    )
    return FigureResponse(
        value=reported.value,
        date=reported.date,
        value_status=reported.value_status,
        newer_point_without_value=newer,
    )


def owner_response(owner: AccountOwnerDto | None) -> OwnerResponse | None:
    if owner is None:
        return None
    return OwnerResponse(id=owner.id, name=owner.name, resource_type=owner.resource_type)


def investor_type_response(investor_type: InvestorTypeDto | None) -> InvestorTypeResponse | None:
    if investor_type is None:
        return None
    return InvestorTypeResponse(id=investor_type.id, name=investor_type.name)


def investor_qualification_response(
    qualification: InvestorQualificationAttributes | None,
) -> InvestorQualificationResponse | None:
    if qualification is None or (qualification.status is None and qualification.option is None):
        return None
    return InvestorQualificationResponse(status=qualification.status, option=qualification.option)


def account_row_response(account: AccountRecordDto) -> AccountRowResponse:
    return AccountRowResponse.model_validate(
        {
            **account.model_dump(),
            "owner": owner_response(account.owner),
            "investor_type": investor_type_response(account.investor_type),
            "product": product_ref_response(account.product) if account.product else None,
            "investor_qualification": investor_qualification_response(
                account.investor_qualification
            ),
        }
    )


def _series_errors(errors: tuple[SeriesErrorDto, ...]) -> tuple[SeriesErrorResponse, ...] | None:
    if not errors:
        return None
    return tuple(
        SeriesErrorResponse(series=error.series, message=error.message) for error in errors
    )


def position_row_response(position: AccountPositionDto) -> PositionRowResponse:
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


def closed_hint(*, closed_omitted: int, returned: int, subject: str) -> str | None:
    """Why an empty or short account list is not "owns nothing".

    A bare `[]` reads as "this product has no investors". `subject` is the noun the sentence is
    about — the two tools differ only in that word.
    """
    if not closed_omitted:
        return None
    if not returned:
        return (
            f"This {subject} has accounts, but all of them are closed. Pass include_closed=true "
            "to list them."
        )
    return (
        f"{closed_omitted} closed account(s) were omitted. Pass include_closed=true "
        "to include them."
    )
