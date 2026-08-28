from collections.abc import Mapping
from typing import Annotated, ClassVar, cast

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints

from backstop_mcp.backstop_client import BackstopApiResource, ResourceRef
from backstop_mcp.dates import LenientDate
from backstop_mcp.features.custom_fields import RegularCustomFieldValues
from backstop_mcp.lenient import LenientBool, LenientFloat, LenientInt

__all__ = [
    "ACCOUNT_LISTING_FIELDS",
    "AccountApiResponse",
    "AccountAttributes",
    "AccountTableDataAttributes",
    "AccountTableDataDocument",
    "AccountTableDataEntry",
    "AccountTableRowAttributes",
    "CapitalFlowAttributes",
    "InvestorQualificationAttributes",
    "InvestorTypeAttributes",
    "OwnerAttributes",
    "ProductAttributes",
    "ProductConfigurationAttributes",
    "SeriesPointAttributes",
    "TableDataMoneyAttributes",
    "TableDataProductAttributes",
    "TableDataShareAttributes",
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
    """Wire shape of a `products` resource's `attributes`.

    The catalog walk for name resolution uses `fields=name,configuration`. `get_product`
    omits that sparse fieldset so `regularCustomFieldValues` arrives.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    name: _StrippedStr | None = None
    configuration: ProductConfigurationAttributes | None = None
    regular_custom_field_values: RegularCustomFieldValues = Field(
        default_factory=list, alias="regularCustomFieldValues"
    )


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


# Exactly the attributes `AccountAttributes` reads, by wire name. Anything added there has to be
# added here too, or it arrives as `None` on every row instead of failing loudly.
#
# `closedDate` has to stay in this fieldset and stay meaningful: open is *the key was absent on
# the wire*, so a `fields=` set that materialized it as null would report every account closed.
# It does not — of 200 rows fetched this way the key was absent on 8 and null on 0, matching
# what the same accounts return unfiltered.
ACCOUNT_LISTING_FIELDS = ",".join(
    (
        "name",
        "currency",
        "accountStartDate",
        "closedDate",
        "ownershipType",
        "investorQualification",
        "isEmployeeAccount",
        "isGpAccount",
        "amlCheckComplete",
        "newIssueEligible",
        "usDomiciled",
    )
)


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
    """Wire shape of one dated point on an account or product time series.

    `valueStatus` is an account extra (`ESTIMATE` / `ACTUAL` on `values`); `source` is a product
    `aums` extra (`"AUM from Accounts"` here). Other series omit both.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    date: LenientDate = None
    value: LenientFloat = None
    value_status: _CleanStr = Field(default=None, alias="valueStatus")
    source: _CleanStr = None


def _scalar_str(value: object) -> str | None:
    """A scalar as a non-empty string, or `None`.

    An id or label that arrives as `90007828` rather than `"90007828"` is the same id, so it is
    coerced instead of failing the row. `bool` is excluded deliberately — `True` is not a label.
    """
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return str(value)
    return None


def _readable_ref(value: object) -> object:
    """A reference we can resolve, or `None`.

    `ResourceRef` requires a non-blank `resource_id`, which is right against a documented
    endpoint. Here anything unusable — a scalar where an object belongs, a missing id, a blank or
    whitespace id, a numeric id — would fail the whole document over one field on one row of an
    undocumented one. Each of those degrades to `None` instead, and a numeric id is coerced.
    """
    if not isinstance(value, Mapping):
        return None
    reference = dict(cast("Mapping[str, object]", value))
    resource_id = _scalar_str(reference.get("resourceId"))
    if resource_id is None:
        return None
    return reference | {"resourceId": resource_id}


def _object_or_none(value: object) -> object:
    """A nested object that arrived as a scalar is unreadable, so read it as absent.

    A figure published as `"$1.00"` or `1.0` instead of `{amount, currency, ...}` must cost that
    figure, not the whole holdings answer.
    """
    if value is None:
        return None
    if not isinstance(value, Mapping):
        return None
    return cast("Mapping[str, object]", value)


# Lenient scalars and objects, used only by the undocumented table-data models below. The
# documented endpoints keep the strict types: there, an off-type value is a bug worth seeing.
_TableDataStr = Annotated[str | None, BeforeValidator(_scalar_str)]
_OptionalRef = Annotated[ResourceRef | None, BeforeValidator(_readable_ref)]


class TableDataMoneyAttributes(BaseModel):
    """A money figure on a table-data row: `{amount, currency, currencySymbol, formattedValue}`.

    `formatted_value` is Backstop's own rendering and is `"-"` (not `"$0.00"`) for an unset
    figure, so it is carried rather than re-derived: `amount` `0.0` with `formattedValue` `"-"`
    means "no commitment recorded", while `0.0` with `"$0.00"` means a real zero.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    amount: LenientFloat = None
    currency: _TableDataStr = None
    currency_symbol: _TableDataStr = Field(default=None, alias="currencySymbol")
    formatted_value: _TableDataStr = Field(default=None, alias="formattedValue")


class TableDataShareAttributes(BaseModel):
    """A share-of-fund figure: `{value, formattedValue}`.

    `value` is a **fraction**, not a percentage — `0.796` renders as `79.6%` — matching the
    `percentageOfFundHistory` series rather than the label.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    value: LenientFloat = None
    formatted_value: _TableDataStr = Field(default=None, alias="formattedValue")


class TableDataProductAttributes(BaseModel):
    """The `product` object on a table-data row: a `ResourceRef` plus `shortName` inline.

    `shortName` is the tenant's own label (`CIO2`, `CGUP`, `Dispersion`) and is the only name on
    the row — there is no full product name here, so a caller who needs one resolves the id.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    resource_id: _TableDataStr = Field(default=None, alias="resourceId")
    resource_type: _TableDataStr = Field(default=None, alias="resourceType")
    short_name: _TableDataStr = Field(default=None, alias="shortName")


_OptionalMoney = Annotated[TableDataMoneyAttributes | None, BeforeValidator(_object_or_none)]
_OptionalShare = Annotated[TableDataShareAttributes | None, BeforeValidator(_object_or_none)]
_OptionalProduct = Annotated[TableDataProductAttributes | None, BeforeValidator(_object_or_none)]


class AccountTableRowAttributes(BaseModel):
    """One entry of `bsg-account-table-data`'s `attributes.accounts`.

    Undocumented UI endpoint, so every field is optional and every reference degrades: a shape
    change must lose a field, not the whole holdings answer. `product` carries `shortName`
    inline, which is why it is not a bare `ResourceRef`.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    investor: _OptionalRef = None
    account: _OptionalRef = None
    organization: _OptionalRef = None
    account_term: _OptionalRef = Field(default=None, alias="accountTerm")
    product: _OptionalProduct = None
    association_type: _TableDataStr = Field(default=None, alias="associationType")
    other_id: _TableDataStr = Field(default=None, alias="otherId")
    funded_date: LenientDate = Field(default=None, alias="fundedDate")
    closed_date: LenientDate = Field(default=None, alias="closedDate")
    closed: LenientBool = None
    balance: _OptionalMoney = None
    commitment: _OptionalMoney = None
    unfunded_commitment: _OptionalMoney = Field(default=None, alias="unfundedCommitment")
    percentage_of_product: _OptionalShare = Field(default=None, alias="percentageOfProduct")
    percentage_of_master: _OptionalShare = Field(default=None, alias="percentageOfMaster")


class AccountTableDataAttributes(BaseModel):
    """`data[0].attributes` of `bsg-account-table-data`.

    The counts are Backstop's own and are published rather than recomputed from `accounts`:
    they agree today, and a disagreement is worth surfacing rather than hiding.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    accounts: tuple[AccountTableRowAttributes, ...] = ()
    open_count: LenientInt = Field(default=None, alias="openCount")
    all_count: LenientInt = Field(default=None, alias="allCount")
    closed_count: LenientInt = Field(default=None, alias="closedCount")


class AccountTableDataEntry(BaseModel):
    """One element of the top-level `data` list. Its `id` is `null`, so this is not a resource.

    `attributes` is **required**, unlike the row fields. A row losing a field costs that field; the
    envelope losing a key means we are not reading the table at all, and defaulting it would report
    "this party owns nothing" instead. Every recorded response carries it, including the empty ones.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    attributes: AccountTableDataAttributes


class AccountTableDataDocument(BaseModel):
    """Whole `bsg-account-table-data` body.

    Deliberately not `BackstopApiResourceDocument`: `data` is a **list** whose single element has
    a `null` id, `links` is `null`, `included` is always `[]`, and `meta.totalResourceCount` is
    `0` regardless of how many rows came back. None of the JSON:API envelope means anything here.

    `data` is **required and non-empty** for the same reason `attributes` is. All four recorded
    responses carry exactly one element — including the two empty fail-open bodies — so an absent
    or renamed `data` is the endpoint having changed, not a party with no accounts. Failing here
    routes the caller to the documented walk; defaulting to `()` would have it answer "owns
    nothing" with total confidence.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    data: tuple[AccountTableDataEntry, ...] = Field(min_length=1)

    @property
    def table(self) -> AccountTableDataAttributes:
        """The single table. `data` is validated non-empty, so this cannot be a silent default."""
        return self.data[0].attributes


# Plain assignment — `schema=` needs a real class object; a PEP 695 alias is not `type[T]`.
AccountApiResponse = BackstopApiResource[AccountAttributes]


class CapitalFlowAttributes(BaseModel):
    """Wire attributes shared by subscriptions and redemptions (subset we publish)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    amount: LenientFloat = None
    transaction_date: LenientDate = Field(default=None, alias="transactionDate")
    notice_date: LenientDate = Field(default=None, alias="noticeDate")
    status: _CleanStr = None
    description: _CleanStr = None
    share_class: _CleanStr = Field(default=None, alias="shareClass")
    share_series: _CleanStr = Field(default=None, alias="shareSeries")
    liquidating: LenientBool = None
    legacy_transaction_type: _CleanStr = Field(default=None, alias="legacyTransactionType")
