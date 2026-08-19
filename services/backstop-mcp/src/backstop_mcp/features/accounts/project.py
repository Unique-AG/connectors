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
from backstop_mcp.features.accounts.api_responses import (
    AccountAttributes,
    InvestorTypeAttributes,
    OwnerAttributes,
    ProductAttributes,
)
from backstop_mcp.features.accounts.internal_dto import (
    AccountListingDto,
    AccountOwnerDto,
    AccountRecordDto,
    InvestorTypeDto,
    ResolvedProductDto,
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


def project_owner(raw: dict[str, object] | None) -> AccountOwnerDto | None:
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
        return AccountOwnerDto(
            id=specific.resource_id,
            name=owner.attributes.name,
            resource_type=specific.resource_type,
        )
    return AccountOwnerDto(id=owner.id, name=owner.attributes.name, resource_type=owner.type)


def account_owner(
    resource: AccountApiResponse, *, included: Sequence[dict[str, object]]
) -> AccountOwnerDto | None:
    """The projected owner of one account, or `None` when the include is absent."""
    return project_owner(_first_included(included, resource, _OWNER))


def project_investor_type(raw: dict[str, object] | None) -> InvestorTypeDto | None:
    investor_type = included_resource(raw, schema=_InvestorTypeInclude)
    if investor_type is None:
        return None
    return InvestorTypeDto(id=investor_type.id, name=investor_type.attributes.name)


def project_included_product(raw: dict[str, object] | None) -> ResolvedProductDto | None:
    product = included_resource(raw, schema=_ProductInclude)
    if product is None:
        return None
    return ResolvedProductDto.from_attributes(product.id, product.attributes)


def project_account(
    resource: AccountApiResponse,
    *,
    included: Sequence[dict[str, object]],
) -> AccountRecordDto:
    return AccountRecordDto.model_validate(
        {
            **resource.attributes.model_dump(),
            "id": resource.id,
            "owner": account_owner(resource, included=included),
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
) -> tuple[AccountRecordDto, ...]:
    return tuple(project_account(resource, included=included) for resource in resources)


def split_open(records: Sequence[AccountRecordDto], *, include_closed: bool) -> AccountListingDto:
    if include_closed:
        return AccountListingDto(accounts=tuple(records), closed_omitted=0)
    open_accounts = tuple(record for record in records if record.is_open)
    return AccountListingDto(
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
