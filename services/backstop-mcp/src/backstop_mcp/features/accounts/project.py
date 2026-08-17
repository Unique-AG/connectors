"""Project `/accounts` resources and their `owner` / `investorType` / `product` includes.

The account body is already `BackstopApiResource[AccountAttributes]` from the client. Side-loads
are not: `paginate` keeps `included` as mixed JSON:API dicts (owners, investor types, and
products in one array), so each is read here as an `IncludedResource[...]` — one validation per
side-load, identity kept.

`features.includes` is the person/organization MCP include allowlist, not a projection utility,
and does not fit. It plans a caller-selected set of include *names* (the three here are fixed and
unconditional), it projects a by-id document (this is a collection walk over one shared `included`
array), and it keeps `attributes` only — while the ids are part of the answer here, `product.id`
being what `get_product_positions` takes back. What the two do share is the layer below:
`follow_included` and `IncludedResource`.
"""

from collections.abc import Sequence

from backstop_mcp.backstop_client import (
    BackstopApiResource,
    IncludedResource,
    follow_included,
    included_resource,
)
from backstop_mcp.features.accounts.types import (
    AccountAttributes,
    AccountListing,
    AccountOwner,
    AccountRecord,
    InvestorType,
    InvestorTypeAttributes,
    OwnerAttributes,
    ProductAttributes,
    ResolvedProduct,
)

_OWNER = "owner"
_INVESTOR_TYPE = "investorType"
_PRODUCT = "product"

AccountApiResponse = BackstopApiResource[AccountAttributes]

# Plain assignments — `schema=` needs a real class object; a PEP 695 alias is not `type[T]`.
_OwnerInclude = IncludedResource[OwnerAttributes]
_InvestorTypeInclude = IncludedResource[InvestorTypeAttributes]
_ProductInclude = IncludedResource[ProductAttributes]


def account_is_open(attributes: AccountAttributes) -> bool:
    """Open means the `closedDate` key was absent on the wire — a present null is still closed."""
    return "closed_date" not in attributes.model_fields_set


def project_owner(raw: dict[str, object] | None) -> AccountOwner | None:
    """The `owner` side-load as an identity.

    `specificResource.resourceType` wins over the JSON:API `type`: an organization owner arrives
    as a `contacts` resource, and `organizations` is the answer a caller can act on.
    """
    owner = included_resource(raw, schema=_OwnerInclude)
    if owner is None:
        return None
    specific = owner.attributes.specific_resource
    specific_type = None if specific is None else specific.resource_type
    return AccountOwner(
        id=owner.id,
        name=owner.attributes.name,
        resource_type=specific_type or owner.type,
    )


def project_investor_type(raw: dict[str, object] | None) -> InvestorType | None:
    investor_type = included_resource(raw, schema=_InvestorTypeInclude)
    if investor_type is None:
        return None
    return InvestorType(id=investor_type.id, name=investor_type.attributes.name)


def project_included_product(raw: dict[str, object] | None) -> ResolvedProduct | None:
    product = included_resource(raw, schema=_ProductInclude)
    if product is None:
        return None
    return ResolvedProduct.from_attributes(product.id, product.attributes)


def project_account(
    resource: AccountApiResponse,
    *,
    included: Sequence[dict[str, object]],
) -> AccountRecord:
    return AccountRecord.model_validate(
        {
            **resource.attributes.model_dump(),
            "id": resource.id,
            "owner": project_owner(_first_included(included, resource, _OWNER)),
            "investor_type": project_investor_type(
                _first_included(included, resource, _INVESTOR_TYPE)
            ),
            "product": project_included_product(_first_included(included, resource, _PRODUCT)),
            "is_open": account_is_open(resource.attributes),
        }
    )


def project_accounts(
    resources: Sequence[AccountApiResponse],
    *,
    included: Sequence[dict[str, object]],
) -> tuple[AccountRecord, ...]:
    return tuple(project_account(resource, included=included) for resource in resources)


def split_open(records: Sequence[AccountRecord], *, include_closed: bool) -> AccountListing:
    if include_closed:
        return AccountListing(accounts=tuple(records), closed_omitted=0)
    open_accounts = tuple(record for record in records if record.is_open)
    return AccountListing(
        accounts=open_accounts,
        closed_omitted=len(records) - len(open_accounts),
    )


def _first_included(
    included: Sequence[dict[str, object]],
    resource: AccountApiResponse,
    relationship: str,
) -> dict[str, object] | None:
    related = follow_included(included, resource, relationship)
    return related[0] if related else None
