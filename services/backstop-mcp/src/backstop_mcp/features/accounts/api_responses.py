from typing import Annotated, ClassVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints

from backstop_mcp.backstop_client import ResourceRef
from backstop_mcp.dates import LenientDate
from backstop_mcp.lenient import LenientBool, LenientFloat

__all__ = [
    "AccountAttributes",
    "InvestorQualificationAttributes",
    "InvestorTypeAttributes",
    "OwnerAttributes",
    "ProductAttributes",
    "ProductConfigurationAttributes",
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


class ProductConfigurationAttributes(BaseModel):
    """`attributes.configuration` on a `products` resource (sparse fieldset)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    product_short_name: _StrippedStr | None = Field(default=None, alias="productShortName")


class ProductAttributes(BaseModel):
    """Wire shape of a `products` resource's `attributes` under `fields=name,configuration`."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    name: _StrippedStr | None = None
    configuration: ProductConfigurationAttributes | None = None


class InvestorQualificationAttributes(BaseModel):
    """`attributes.investorQualification` on an account: `{status?, option?}`."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    status: _CleanStr = None
    option: _CleanStr = None


class AccountAttributes(BaseModel):
    """Wire shape of an `accounts` resource's `attributes` used for listing."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    name: _StrippedStr | None = None
    currency: _StrippedStr | None = None
    account_start_date: LenientDate = Field(default=None, alias="accountStartDate")
    closed_date: LenientDate = Field(default=None, alias="closedDate")
    ownership_type: _StrippedStr | None = Field(default=None, alias="ownershipType")
    investor_qualification: InvestorQualificationAttributes | None = Field(
        default=None, alias="investorQualification"
    )
    is_employee_account: LenientBool = Field(default=None, alias="isEmployeeAccount")
    is_gp_account: LenientBool = Field(default=None, alias="isGpAccount")
    aml_check_complete: LenientBool = Field(default=None, alias="amlCheckComplete")
    new_issue_eligible: _StrippedStr | None = Field(default=None, alias="newIssueEligible")
    us_domiciled: LenientBool = Field(default=None, alias="usDomiciled")


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


class SeriesPointAttributes(BaseModel):
    """Wire shape of one dated point on `values` / `totalInvested` / `totalRedemptions` / `aums`."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    date: LenientDate = None
    value: LenientFloat = None
    value_status: _CleanStr = Field(default=None, alias="valueStatus")
