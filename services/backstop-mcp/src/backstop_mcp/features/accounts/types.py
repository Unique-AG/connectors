from datetime import date
from typing import Annotated, ClassVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints

from backstop_mcp.backstop_client import ResourceRef
from backstop_mcp.dates import LenientDate
from backstop_mcp.features.resolution import Candidate, Resolution

__all__ = [
    "AccountListing",
    "AccountOwner",
    "AccountRecord",
    "InvestorType",
    "ProductCandidate",
    "ProductResolution",
    "ResolvedProduct",
    "SeriesPoint",
    "SeriesPointAttributes",
]

_StrippedStr = Annotated[str, StringConstraints(strip_whitespace=True)]


def _blank_to_none(value: object) -> object:
    """A name Backstop sends as `""` means unset, and reads as a real empty name if kept."""
    return (value.strip() or None) if isinstance(value, str) else value


# Annotated on the *union*, not on the `str` arm: a `BeforeValidator` inside
# `Annotated[str, ...] | None` still has its result checked against `str`, so returning None for
# a blank fails validation rather than selecting the None arm.
_CleanStr = Annotated[str | None, BeforeValidator(_blank_to_none)]


class ProductConfiguration(BaseModel):
    """`attributes.configuration` on a `products` resource (sparse fieldset)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    product_short_name: _StrippedStr | None = Field(default=None, alias="productShortName")


class ProductAttributes(BaseModel):
    """Wire shape of a `products` resource's `attributes` under `fields=name,configuration`."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    name: _StrippedStr | None = None
    configuration: ProductConfiguration | None = None


class ResolvedProduct(BaseModel):
    """A product identity, from the `/products` index or from an account's `product` side-load."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    name: str | None = None
    short_name: str | None = None

    @classmethod
    def from_attributes(cls, product_id: str, attributes: ProductAttributes) -> "ResolvedProduct":
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


type ProductCandidate = Candidate[ResolvedProduct]
type ProductResolution = Resolution[ResolvedProduct]


class AccountAttributes(BaseModel):
    """Wire shape of an `accounts` resource's `attributes` used for listing."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    name: _StrippedStr | None = None
    currency: _StrippedStr | None = None
    account_start_date: LenientDate = Field(default=None, alias="accountStartDate")
    closed_date: LenientDate = Field(default=None, alias="closedDate")
    ownership_type: _StrippedStr | None = Field(default=None, alias="ownershipType")
    investor_qualification: _StrippedStr | None = Field(default=None, alias="investorQualification")
    is_employee_account: bool | None = Field(default=None, alias="isEmployeeAccount")
    is_gp_account: bool | None = Field(default=None, alias="isGpAccount")
    aml_check_complete: bool | None = Field(default=None, alias="amlCheckComplete")
    new_issue_eligible: bool | None = Field(default=None, alias="newIssueEligible")
    us_domiciled: bool | None = Field(default=None, alias="usDomiciled")


class OwnerAttributes(BaseModel):
    """Wire shape of the `owner` side-load's `attributes`.

    Owners arrive on the polymorphic `contacts` view, and `specificResource` is Backstop's
    discriminator on it: an organization owner is a `contacts` resource whose
    `specificResource.resourceType` is `organizations`. That is `ResourceRef` — Backstop's inline
    reference format — rather than a shape of our own, so it is read the same way here as
    everywhere else it turns up.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    name: _CleanStr = None
    specific_resource: ResourceRef | None = Field(default=None, alias="specificResource")


class InvestorTypeAttributes(BaseModel):
    """Wire shape of the `investorType` side-load's `attributes`."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    name: _CleanStr = None


class AccountOwner(BaseModel):
    """Identity of the party on an account — not the contact-card dump."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    name: str | None = None
    resource_type: str | None = None


class InvestorType(BaseModel):
    """The side-loaded `investorType` include, identity only."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    name: str | None = None


class AccountRecord(BaseModel):
    """One account after listing: status fields plus projected includes."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    name: str | None = None
    owner: AccountOwner | None = None
    investor_type: InvestorType | None = None
    product: ResolvedProduct | None = None
    currency: str | None = None
    account_start_date: date | None = None
    closed_date: date | None = None
    ownership_type: str | None = None
    investor_qualification: str | None = None
    is_employee_account: bool | None = None
    is_gp_account: bool | None = None
    aml_check_complete: bool | None = None
    new_issue_eligible: bool | None = None
    us_domiciled: bool | None = None
    is_open: bool


class AccountListing(BaseModel):
    """Projected accounts after the open/closed split.

    `closed_omitted` is how many matching rows were dropped because `include_closed` is false.
    Distinguishes zero accounts from an all-closed product or party.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    accounts: tuple[AccountRecord, ...]
    closed_omitted: int = 0


class SeriesPointAttributes(BaseModel):
    """Wire shape of one dated point on `values` / `totalInvested` / `totalRedemptions` / `aums`."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    date: LenientDate = None
    value: float | None = None
    value_status: _CleanStr = Field(default=None, alias="valueStatus")


class SeriesPoint(BaseModel):
    """The latest usable point in a series: `max(date)`, never 'last of month'.

    `value_status` is whatever Backstop sent (`ESTIMATE` on recent `values`, often absent on
    `totalInvested` / `aums`). It is not defaulted to `ACTUAL`.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    date: date
    value: float | None = None
    value_status: str | None = None
