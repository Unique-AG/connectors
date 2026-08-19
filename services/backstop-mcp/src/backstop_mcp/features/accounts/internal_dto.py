from datetime import date
from typing import ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict

from backstop_mcp.features.accounts.api_responses import (
    AccountAttributes,
    InvestorQualificationAttributes,
    ProductAttributes,
    SeriesPointAttributes,
)
from backstop_mcp.features.resolution import Candidate, Resolution

__all__ = [
    "AccountListingDto",
    "AccountOwnerDto",
    "AccountPositionDto",
    "AccountRecordDto",
    "AumReconciliationDto",
    "InvestorTypeDto",
    "ProductCandidate",
    "ProductPositionsDto",
    "ProductResolution",
    "ResolvedProductDto",
    "SeriesErrorDto",
    "SeriesFigureDto",
    "SeriesName",
    "SeriesPointDto",
]


class ResolvedProductDto(BaseModel):
    """A product identity, from the `/products` index or from an account's `product` side-load."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    name: str | None = None
    short_name: str | None = None

    @classmethod
    def from_attributes(
        cls, product_id: str, attributes: ProductAttributes
    ) -> "ResolvedProductDto":
        """Flatten the nested `configuration.productShortName` onto the identity.

        Takes an id and attributes rather than a resource, because the two sources are shaped
        differently — a `/products` page item is a `BackstopApiResource`, an account's `product`
        include is an `IncludedResource` — and only these two parts are common to both.
        """
        configuration = attributes.configuration
        return cls(
            id=product_id,
            name=attributes.name,
            short_name=None if configuration is None else configuration.product_short_name,
        )


type ProductCandidate = Candidate[ResolvedProductDto]
type ProductResolution = Resolution[ResolvedProductDto]


class AccountOwnerDto(BaseModel):
    """Identity of the party on an account — not the contact-card dump."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    name: str | None = None
    resource_type: str | None = None


class InvestorTypeDto(BaseModel):
    """The side-loaded `investorType` include, identity only."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    name: str | None = None


class AccountRecordDto(BaseModel):
    """One account after listing: status fields plus projected includes."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    name: str | None = None
    owner: AccountOwnerDto | None = None
    investor_type: InvestorTypeDto | None = None
    product: ResolvedProductDto | None = None
    currency: str | None = None
    account_start_date: date | None = None
    closed_date: date | None = None
    ownership_type: str | None = None
    investor_qualification: InvestorQualificationAttributes | None = None
    is_employee_account: bool | None = None
    is_gp_account: bool | None = None
    aml_check_complete: bool | None = None
    new_issue_eligible: str | None = None
    us_domiciled: bool | None = None
    is_open: bool

    @classmethod
    def from_attributes(
        cls,
        account_id: str,
        attributes: AccountAttributes,
        *,
        owner: AccountOwnerDto | None,
        investor_type: InvestorTypeDto | None,
        product: ResolvedProductDto | None,
        is_open: bool,
    ) -> Self:
        return cls(
            id=account_id,
            name=attributes.name,
            owner=owner,
            investor_type=investor_type,
            product=product,
            currency=attributes.currency,
            account_start_date=attributes.account_start_date,
            closed_date=attributes.closed_date,
            ownership_type=attributes.ownership_type,
            investor_qualification=attributes.investor_qualification,
            is_employee_account=attributes.is_employee_account,
            is_gp_account=attributes.is_gp_account,
            aml_check_complete=attributes.aml_check_complete,
            new_issue_eligible=attributes.new_issue_eligible,
            us_domiciled=attributes.us_domiciled,
            is_open=is_open,
        )


class AccountListingDto(BaseModel):
    """Projected accounts after the open/closed split.

    `closed_omitted` is how many matching rows were dropped because `include_closed` is false.
    Distinguishes zero accounts from an all-closed product or party.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    accounts: tuple[AccountRecordDto, ...]
    closed_omitted: int = 0


class SeriesPointDto(BaseModel):
    """The latest usable point in a series: `max(date)`, never 'last of month'.

    `value_status` is whatever Backstop sent (`ESTIMATE` on recent `values`, often absent on
    `totalInvested` / `aums`). It is not defaulted to `ACTUAL`.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    date: date
    value: float | None = None
    value_status: str | None = None

    @classmethod
    def from_attributes(cls, attributes: SeriesPointAttributes) -> Self | None:
        point_date = attributes.date
        if point_date is None:
            return None
        return cls(date=point_date, value=attributes.value, value_status=attributes.value_status)


class SeriesFigureDto(BaseModel):
    """What a series reported: its latest point, and the latest point carrying a value.

    The two are the same point whenever Backstop's newest row has a number. They differ when
    Backstop publishes a dated row ahead of the value — the UI shows `-` for it. Keeping only
    `latest` would report a live position as "no data"; keeping only `valued` would hide that
    Backstop has since moved the series on. Both are kept and the caller is told which is which.

    `valued` is `None` only when no point on the fetched page carries a value at all.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    latest: SeriesPointDto
    valued: SeriesPointDto | None = None


type SeriesName = Literal["values", "totalInvested", "totalRedemptions"]


class SeriesErrorDto(BaseModel):
    """One series that failed for an account — siblings on the same row still stand."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    series: SeriesName
    message: str


class AccountPositionDto(BaseModel):
    """One listed account with the three series attached.

    A missing figure is `None` (empty series), never `0.0`. A `0.0` that Backstop published is
    kept. Failures go in `errors` so one 500 does not drop the row or its siblings.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    account: AccountRecordDto
    balance: SeriesFigureDto | None = None
    invested: SeriesFigureDto | None = None
    redemptions: SeriesFigureDto | None = None
    errors: tuple[SeriesErrorDto, ...] = ()


class AumReconciliationDto(BaseModel):
    """Latest assets under management (AUM) against the sum of returned account balances.

    The two are never expected to agree to the cent: they are as-of different dates, the open
    default excludes closed-but-still-valued accounts, and balances are summed without currency
    conversion. So `diverges` is a *tolerance* verdict, not an equality test, and `difference`
    is published so the caller can judge the magnitude itself rather than trust a bare flag.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    balance_total: float | None = None
    difference: float | None = None
    diverges: bool = False


class ProductPositionsDto(BaseModel):
    """Listed accounts with figures, plus product assets under management (AUM).

    AUM is the product's total reported value, not one investor's balance. `accounts_omitted`
    is how many listed open accounts were dropped before the series fan-out because the product
    exceeded the per-call cap.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    product: ResolvedProductDto
    accounts: tuple[AccountPositionDto, ...]
    closed_omitted: int = 0
    accounts_omitted: int = 0
    aum: SeriesFigureDto | None = None
    reconciliation: AumReconciliationDto = AumReconciliationDto()
