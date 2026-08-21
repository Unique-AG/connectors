from collections.abc import Sequence
from datetime import date
from typing import ClassVar, Literal, Self, cast, get_args

from pydantic import BaseModel, ConfigDict

from backstop_mcp.backstop_client import (
    IncludedResource,
    follow_included,
    included_resource,
)
from backstop_mcp.features.accounts.api_responses import (
    AccountApiResponse,
    AccountAttributes,
    AccountTableRowAttributes,
    InvestorQualificationAttributes,
    InvestorTypeAttributes,
    OwnerAttributes,
    ProductAttributes,
    SeriesPointAttributes,
    TableDataMoneyAttributes,
    TableDataShareAttributes,
)
from backstop_mcp.features.resolution import Candidate, Resolution

__all__ = [
    "ACCOUNT_SERIES",
    "AccountListingDto",
    "AccountOwnerDto",
    "AccountRecordDto",
    "AccountSeries",
    "CapitalFlowDto",
    "CapitalFlowPartyDto",
    "CapitalFlowWalkDto",
    "CapitalFlowsFetchDto",
    "HoldingFigureErrorDto",
    "HoldingListingDto",
    "HoldingRowDto",
    "HoldingsSource",
    "InvestorTypeDto",
    "MoneyDto",
    "PRODUCT_SERIES",
    "ProductCandidate",
    "ProductCatalogFetchDto",
    "ProductFetchDto",
    "ProductResolution",
    "ProductSeries",
    "ResolvedProductDto",
    "SeriesFigureDto",
    "SeriesPointDto",
    "ShareDto",
    "TimeSeriesEntityType",
    "TimeSeriesName",
]

_OWNER = "owner"
_INVESTOR_TYPE = "investorType"
_PRODUCT = "product"

# Swagger enums for `GET /{accounts|products}/{id}/{timeSeries}`. Keep Backstop's
# `currentMonthNetAssests` spelling. Membership sets are derived from the Literals so a
# typo cannot accept a path segment pydantic would reject, or the other way around.
type TimeSeriesEntityType = Literal["accounts", "products"]
type AccountSeries = Literal[
    "currentMonthIrrs",
    "currentMonthNetAssests",
    "earnings",
    "grossValues",
    "highwaterMarks",
    "incentiveFees",
    "incentiveFeesCharged",
    "irrs",
    "managementFees",
    "newIssueIncomes",
    "percentageOfFundHistory",
    "performanceFeeAccrued",
    "returns",
    "startingValues",
    "totalInvested",
    "totalRedemptions",
    "values",
]
type ProductSeries = Literal[
    "aums",
    "benchmarkAReturns",
    "benchmarkBReturns",
    "benchmarkCReturns",
    "benchmarkDReturns",
    "benchmarkEReturns",
    "benchmarkFReturns",
    "benchmarkGReturns",
    "benchmarkHReturns",
    "expenseDataPoints",
    "incomeDataPoints",
]
type TimeSeriesName = AccountSeries | ProductSeries


def _literal_strings(alias: object) -> frozenset[str]:
    """String members of a PEP 695 `Literal` alias."""
    value: object = getattr(alias, "__value__", alias)
    members = cast("tuple[object, ...]", get_args(value))
    names = tuple(member for member in members if isinstance(member, str))
    assert names and len(names) == len(members), f"{alias} is not a non-empty string Literal"
    return frozenset(names)


ACCOUNT_SERIES: frozenset[str] = _literal_strings(AccountSeries)
PRODUCT_SERIES: frozenset[str] = _literal_strings(ProductSeries)

# Plain assignments — `schema=` needs a real class object; a PEP 695 alias is not `type[T]`.
_OwnerInclude = IncludedResource[OwnerAttributes]
_InvestorTypeInclude = IncludedResource[InvestorTypeAttributes]
_ProductInclude = IncludedResource[ProductAttributes]


def _account_is_open(attributes: AccountAttributes) -> bool:
    """Open means the `closedDate` key was absent on the wire — a present null is still closed."""
    return "closed_date" not in attributes.model_fields_set


def _first_included(
    included: Sequence[dict[str, object]],
    resource: AccountApiResponse,
    relationship: str,
) -> dict[str, object] | None:
    related = follow_included(included, resource, relationship)
    return related[0] if related else None


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

    @classmethod
    def from_included(cls, raw: dict[str, object] | None) -> "ResolvedProductDto | None":
        product = included_resource(raw, schema=_ProductInclude)
        if product is None:
            return None
        return cls.from_attributes(product.id, product.attributes)


type ProductCandidate = Candidate[ResolvedProductDto]
type ProductResolution = Resolution[ResolvedProductDto]


class ProductFetchDto(BaseModel):
    """A product identity plus the raw custom-field dump `get_product` joins to the catalog."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    product: ResolvedProductDto
    stored_custom_field_values: object = None


class AccountOwnerDto(BaseModel):
    """Identity of the party on an account — not the contact-card dump."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    name: str | None = None
    resource_type: str | None = None

    @classmethod
    def from_included(cls, raw: dict[str, object] | None) -> Self | None:
        """The `owner` side-load as an identity.

        `specificResource` wins over the JSON:API envelope: an organization owner arrives as a
        `contacts` resource, and `organizations` is the answer a caller can act on. The id is taken
        from the *same* reference as the type, never mixed — `resourceId` is what exists in the
        collection `resourceType` names, and every description tells the model to echo this id back
        as a `party_id`. On this instance the two happen to be equal; a projection that assumed so
        would hand back an unusable id the day they are not.
        """
        owner = included_resource(raw, schema=_OwnerInclude)
        if owner is None:
            return None
        specific = owner.attributes.specific_resource
        if specific is not None and specific.resource_type is not None:
            return cls(
                id=specific.resource_id,
                name=owner.attributes.name,
                resource_type=specific.resource_type,
            )
        return cls(id=owner.id, name=owner.attributes.name, resource_type=owner.type)


class InvestorTypeDto(BaseModel):
    """The side-loaded `investorType` include, identity only."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    name: str | None = None

    @classmethod
    def from_included(cls, raw: dict[str, object] | None) -> Self | None:
        investor_type = included_resource(raw, schema=_InvestorTypeInclude)
        if investor_type is None:
            return None
        return cls(id=investor_type.id, name=investor_type.attributes.name)


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

    @classmethod
    def from_resource(
        cls,
        resource: AccountApiResponse,
        *,
        included: Sequence[dict[str, object]],
    ) -> Self:
        """Project one `/accounts` resource and its `owner` / `investorType` / `product` includes.

        The account body is already `BackstopApiResource[AccountAttributes]` from the client.
        Side-loads are not: `paginate` keeps `included` as mixed JSON:API dicts (owners, investor
        types, and products in one array), so each is read as an `IncludedResource[...]` — one
        validation per side-load, identity kept.

        `features.includes` is the person/organization MCP include allowlist, not a projection
        utility, and does not fit. It plans a caller-selected set of include *names* (the three
        here are fixed and unconditional), it projects a by-id document (this is a collection walk
        over one shared `included` array), and it keeps `attributes` only — while the ids are part
        of the answer here, `product.id` being what `get_time_series` takes back. What the
        two do share is the layer below: `follow_included` and `IncludedResource`.
        """
        return cls.from_attributes(
            resource.id,
            resource.attributes,
            owner=AccountOwnerDto.from_included(_first_included(included, resource, _OWNER)),
            investor_type=InvestorTypeDto.from_included(
                _first_included(included, resource, _INVESTOR_TYPE)
            ),
            product=ResolvedProductDto.from_included(_first_included(included, resource, _PRODUCT)),
            is_open=_account_is_open(resource.attributes),
        )

    @classmethod
    def from_resources(
        cls,
        resources: Sequence[AccountApiResponse],
        *,
        included: Sequence[dict[str, object]],
    ) -> tuple[Self, ...]:
        return tuple(cls.from_resource(resource, included=included) for resource in resources)


class AccountListingDto(BaseModel):
    """Projected accounts after the open/closed split.

    `closed_omitted` is how many matching rows were dropped because `include_closed` is false.
    Distinguishes zero accounts from an all-closed product or party.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    accounts: tuple[AccountRecordDto, ...]
    closed_omitted: int = 0


# Which endpoint produced a holdings listing: the undocumented `bsg-account-table-data` or the
# documented `/accounts` walk plus series. They answer the same question with different
# completeness, and the name says which endpoint rather than passing judgement on it.
type HoldingsSource = Literal["table-api", "accounts-api"]


class MoneyDto(BaseModel):
    """A money figure carried with Backstop's own rendering.

    `formatted` is kept because it is the only thing that distinguishes "no figure recorded"
    from a real zero: Backstop renders the former as `"-"` and the latter as `"$0.00"`, while
    `amount` is `0.0` in both cases. Callers that need the distinction read `formatted`.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    amount: float | None = None
    currency: str | None = None
    formatted: str | None = None

    @classmethod
    def from_attributes(cls, attrs: TableDataMoneyAttributes | None) -> Self | None:
        if attrs is None:
            return None
        if attrs.amount is None and attrs.formatted_value is None:
            return None
        return cls(
            amount=attrs.amount,
            currency=attrs.currency,
            formatted=attrs.formatted_value,
        )


class ShareDto(BaseModel):
    """A share-of-fund figure. `fraction` is a fraction (`0.796`), not a percentage."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    fraction: float | None = None
    formatted: str | None = None

    @classmethod
    def from_attributes(cls, attrs: TableDataShareAttributes | None) -> Self | None:
        if attrs is None:
            return None
        if attrs.value is None and attrs.formatted_value is None:
            return None
        return cls(fraction=attrs.value, formatted=attrs.formatted_value)


class HoldingFigureErrorDto(BaseModel):
    """A figure that could not be fetched, and why.

    Without this, "we asked and the request failed" and "Backstop publishes no number" are the
    same `None`. The fallback holdings walk uses it per figure rather than dropping the row.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    figure: str
    message: str


class HoldingRowDto(BaseModel):
    """One account a party holds, with the snapshot figures from the UI table endpoint.

    `balance_as_of` and `balance_status` are the difference between the two source endpoints, and
    the reason they are published rather than smoothed over. On `table-api` both are `None`: the
    balance matched the **newest** `/accounts/{id}/values` point exactly on a measured account,
    including when that point was an `ESTIMATE`, and the endpoint does not say which. On
    `accounts-api` the balance is the newest point that carries a **number**, which can be months
    older than the newest point — so the same field means "current" on one path and "last known"
    on the other, and only the date says which. `figure_errors` separates "the request failed"
    from "Backstop publishes no number", which are otherwise the same `None`.

    `account_id` is the id every follow-up call needs, so a row without one is not projected at
    all: it cannot be used for anything a caller would do next.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    account_id: str
    product_id: str | None = None
    product_short_name: str | None = None
    investor_id: str | None = None
    investor_resource_type: str | None = None
    account_term_id: str | None = None
    other_id: str | None = None
    funded_date: date | None = None
    closed_date: date | None = None
    closed: bool = False
    balance: MoneyDto | None = None
    balance_as_of: date | None = None
    balance_status: str | None = None
    commitment: MoneyDto | None = None
    unfunded_commitment: MoneyDto | None = None
    percentage_of_product: ShareDto | None = None
    percentage_of_master: ShareDto | None = None
    figure_errors: tuple[HoldingFigureErrorDto, ...] = ()

    @classmethod
    def from_attributes(cls, attrs: AccountTableRowAttributes) -> Self | None:
        """Project one table row, or `None` when it carries no usable account id."""
        if attrs.account is None:
            return None
        return cls(
            account_id=attrs.account.resource_id,
            product_id=attrs.product.resource_id if attrs.product else None,
            product_short_name=attrs.product.short_name if attrs.product else None,
            investor_id=attrs.investor.resource_id if attrs.investor else None,
            investor_resource_type=attrs.investor.resource_type if attrs.investor else None,
            account_term_id=attrs.account_term.resource_id if attrs.account_term else None,
            other_id=attrs.other_id,
            funded_date=attrs.funded_date,
            closed_date=attrs.closed_date,
            closed=bool(attrs.closed),
            balance=MoneyDto.from_attributes(attrs.balance),
            commitment=MoneyDto.from_attributes(attrs.commitment),
            unfunded_commitment=MoneyDto.from_attributes(attrs.unfunded_commitment),
            percentage_of_product=ShareDto.from_attributes(attrs.percentage_of_product),
            percentage_of_master=ShareDto.from_attributes(attrs.percentage_of_master),
        )


class HoldingListingDto(BaseModel):
    """A party's holdings after the open/closed split.

    The three counts are Backstop's own, covering the **whole** table before `include_closed`
    filtering — so `all_count` can exceed `len(rows)` legitimately. `rows_dropped` is how many
    rows carried no account id and were skipped; non-zero means the endpoint's shape moved and is
    worth surfacing rather than silently under-reporting.

    `source` and `omitted_fields` are facts about which path produced this, not the sentence a
    caller reads: the response layer turns them into the caveat the model is shown. `omitted_fields`
    is empty on the table path and names what the documented walk cannot produce on the other.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    rows: tuple[HoldingRowDto, ...]
    source: HoldingsSource = "table-api"
    omitted_fields: tuple[str, ...] = ()
    closed_omitted: int = 0
    rows_dropped: int = 0
    open_count: int | None = None
    all_count: int | None = None
    closed_count: int | None = None


class SeriesPointDto(BaseModel):
    """One dated point on a series. A missing `value` is "not in yet", never a silent skip.

    `value_status` is whatever Backstop sent (`ESTIMATE` on recent `values`, often absent on
    `totalInvested` / `aums`). It is not defaulted to `ACTUAL`. `source` is the product-`aums`
    extra and is omitted on every other series.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    date: date
    value: float | None = None
    value_status: str | None = None
    source: str | None = None

    @classmethod
    def from_attributes(cls, attributes: SeriesPointAttributes) -> Self | None:
        point_date = attributes.date
        if point_date is None:
            return None
        return cls(
            date=point_date,
            value=attributes.value,
            value_status=attributes.value_status,
            source=attributes.source,
        )


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


class CapitalFlowPartyDto(BaseModel):
    """Account or owner chip on a capital-flow row."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    name: str | None = None
    resource_type: str | None = None


class CapitalFlowDto(BaseModel):
    """One subscription or redemption after includes are resolved."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    kind: Literal["subscription", "redemption"]
    amount: float | None = None
    transaction_date: date | None = None
    notice_date: date | None = None
    status: str | None = None
    description: str | None = None
    share_class: str | None = None
    share_series: str | None = None
    liquidating: bool | None = None
    account: CapitalFlowPartyDto | None = None
    owner: CapitalFlowPartyDto | None = None
    unattributed: bool = False


class ProductCatalogFetchDto(BaseModel):
    """The product catalog walk, and whether it read all of it.

    `scan_truncated` is the walk's scan ceiling firing, which turns "the catalog" into "the
    first N products" — the difference between "no product has this Strategy" and "none of the
    ones I looked at did".
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    products: tuple[ProductFetchDto, ...]
    scan_truncated: bool = False


class CapitalFlowWalkDto(BaseModel):
    """One capital-flow collection walk: what it kept, what it cost, and what it missed."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    rows: tuple[CapitalFlowDto, ...]
    non_actuals_dropped: int
    request_count: int
    scan_truncated: bool


class CapitalFlowsFetchDto(BaseModel):
    """Both walks, merged newest-first, with the cost and the coverage of the pair.

    `rows_dropped` is how many rows in the window were not actuals (`status != COMPLETED`) and
    so are absent from `rows` and from every count derived from it. `request_count` is pages
    actually fetched across both collections, not a constant. `scan_truncated` is true when
    either walk stopped at its scan ceiling, which makes `rows` a prefix of the window rather
    than the window.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    rows: tuple[CapitalFlowDto, ...]
    rows_dropped: int
    request_count: int
    scan_truncated: bool = False
