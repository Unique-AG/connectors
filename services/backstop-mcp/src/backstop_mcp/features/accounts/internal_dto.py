from collections.abc import Sequence
from datetime import date
from typing import ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict

from backstop_mcp.backstop_client import (
    BackstopApiResource,
    Included,
    IncludedResource,
    included_resource,
)
from backstop_mcp.features.accounts.api_responses import (
    AccountApiResource,
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
from backstop_mcp.features.custom_fields import CustomFieldValueAttributes
from backstop_mcp.features.resolution import Resolution

__all__ = [
    "AccountListingDto",
    "AccountOwnerDto",
    "AccountRecordDto",
    "HoldingFigureErrorDto",
    "HoldingListingDto",
    "HoldingRowDto",
    "InvestorTypeDto",
    "MoneyDto",
    "ProductCatalogFetchDto",
    "ProductFetchDto",
    "ProductResolution",
    "ResolvedProductDto",
    "SeriesFigureDto",
    "SeriesPointDto",
    "ShareDto",
]

_OWNER = "owner"
_INVESTOR_TYPE = "investorType"
_PRODUCT = "product"

# Plain assignments — `schema=` needs a real class object; a PEP 695 alias is not `type[T]`.
_OwnerInclude = IncludedResource[OwnerAttributes]
_InvestorTypeInclude = IncludedResource[InvestorTypeAttributes]
_ProductInclude = IncludedResource[ProductAttributes]


def _account_is_open(attributes: AccountAttributes) -> bool:
    """Open means the `closedDate` key was absent on the wire — a present null is still closed."""
    return "closed_date" not in attributes.model_fields_set


class ResolvedProductDto(BaseModel):
    """A product identity, from the `/products` index or from an account's `product` side-load."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    name: str | None = None
    short_name: str | None = None

    @classmethod
    def from_attributes(cls, product_id: str, attributes: ProductAttributes) -> ResolvedProductDto:
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
    def from_included(
        cls, product: _ProductInclude | dict[str, object] | None
    ) -> ResolvedProductDto | None:
        parsed = (
            product
            if product is None or not isinstance(product, dict)
            else included_resource(product, schema=_ProductInclude)
        )
        if parsed is None:
            return None
        return cls.from_attributes(parsed.id, parsed.attributes)


type ProductResolution = Resolution[ResolvedProductDto]


class ProductFetchDto(BaseModel):
    """A product identity plus the custom-field dump `get_product` joins to the catalog."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    product: ResolvedProductDto
    stored_custom_field_values: tuple[CustomFieldValueAttributes, ...] = ()

    @classmethod
    def from_resource(cls, resource: BackstopApiResource[ProductAttributes]) -> Self:
        return cls(
            product=ResolvedProductDto.from_attributes(resource.id, resource.attributes),
            stored_custom_field_values=tuple(resource.attributes.regular_custom_field_values),
        )


class AccountOwnerDto(BaseModel):
    """Identity of the party on an account — not the contact-card dump."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    name: str | None = None
    resource_type: str | None = None

    @classmethod
    def from_included(cls, owner: _OwnerInclude | dict[str, object] | None) -> Self | None:
        """The `owner` side-load as an identity.

        `specificResource` wins over the JSON:API envelope: an organization owner arrives as a
        `contacts` resource, and `organizations` is the answer a caller can act on. The id is taken
        from the *same* reference as the type, never mixed — `resourceId` is what exists in the
        collection `resourceType` names, and every description tells the model to echo this id back
        as a `party_id`. On this instance the two happen to be equal; a projection that assumed so
        would hand back an unusable id the day they are not.
        """
        parsed = (
            owner
            if owner is None or not isinstance(owner, dict)
            else included_resource(owner, schema=_OwnerInclude)
        )
        if parsed is None:
            return None
        owner = parsed
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
    def from_included(
        cls, investor_type: _InvestorTypeInclude | dict[str, object] | None
    ) -> Self | None:
        parsed = (
            investor_type
            if investor_type is None or not isinstance(investor_type, dict)
            else included_resource(investor_type, schema=_InvestorTypeInclude)
        )
        if parsed is None:
            return None
        return cls(id=parsed.id, name=parsed.attributes.name)


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
        resource: AccountApiResource,
        *,
        included: Included,
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
        two do share is the layer below: `Included` and `IncludedResource`.
        """
        return cls.from_attributes(
            resource.id,
            resource.attributes,
            owner=AccountOwnerDto.from_included(
                included.first(resource, _OWNER, schema=_OwnerInclude)
            ),
            investor_type=InvestorTypeDto.from_included(
                included.first(resource, _INVESTOR_TYPE, schema=_InvestorTypeInclude)
            ),
            product=ResolvedProductDto.from_included(
                included.first(resource, _PRODUCT, schema=_ProductInclude)
            ),
            is_open=_account_is_open(resource.attributes),
        )

    @classmethod
    def from_resources(
        cls,
        resources: Sequence[AccountApiResource],
        *,
        included: Sequence[dict[str, object]],
    ) -> tuple[Self, ...]:
        side_loads = Included(included)
        return tuple(cls.from_resource(resource, included=side_loads) for resource in resources)


class AccountListingDto(BaseModel):
    """Projected accounts after the open/closed split.

    `closed_omitted` is how many matching rows were dropped because `include_closed` is false.
    Distinguishes zero accounts from an all-closed product or party.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    accounts: tuple[AccountRecordDto, ...]
    closed_omitted: int = 0


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

    `account_id` is the id every follow-up call needs. A table row without an account is skipped
    by the query, not projected as a hollow row.
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
    def from_attributes(cls, attrs: AccountTableRowAttributes) -> Self:
        """Project one table row that already carries an account id."""
        account = attrs.account
        assert account is not None
        return cls(
            account_id=account.resource_id,
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
    source: Literal["table-api", "accounts-api"] = "table-api"
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


class ProductCatalogFetchDto(BaseModel):
    """The product catalog walk, and whether it read all of it.

    `scan_truncated` is the walk's scan ceiling firing, which turns "the catalog" into "the
    first N products" — the difference between "no product has this Strategy" and "none of the
    ones I looked at did".
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    products: tuple[ProductFetchDto, ...]
    scan_truncated: bool = False
