"""Account-row vocabulary and product-resolution shapes shared by the holdings tools.

`get_accounts_for_party` publishes `HoldingRowResponse`, not `AccountRowResponse`. The
account-row tree (`AccountRowResponse` and its nested owner / investor-type refs) is the
listing `get_product_investors` publishes — identity and owner, no figures. The product
itself sits once on that tool's resolved response, not on every row.

`OmitNoneModel` drops nulls: a missing figure is absent, never `0.0`. A `0.0` Backstop
published is a real point and is kept.
"""

from datetime import date as Date
from typing import Self

from pydantic import Field

from backstop_mcp.backstop_client import Included, IncludedResource
from backstop_mcp.features.accounts.api_responses import (
    AccountApiResource,
    InvestorQualificationAttributes,
    InvestorTypeAttributes,
    OwnerAttributes,
)
from backstop_mcp.features.accounts.internal_dto import (
    AccountOwnerDto,
    AccountRecordDto,
    InvestorTypeDto,
    ResolvedProductDto,
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


class ProductRefResponse(OmitNoneModel):
    """A product identity: id, name, and short name."""

    id: str = Field(
        description=(
            "Backstop product id. Echo it as `entity_id` on `get_time_series` with "
            "`entity_type='products'` — never invent one."
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

    @classmethod
    def from_product(cls, product: ResolvedProductDto) -> Self:
        return cls(id=product.id, name=product.name, short_name=product.short_name)


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

    @classmethod
    def from_owner(cls, owner: AccountOwnerDto | None) -> Self | None:
        if owner is None:
            return None
        return cls(id=owner.id, name=owner.name, resource_type=owner.resource_type)

    @classmethod
    def from_included(cls, owner: IncludedResource[OwnerAttributes] | None) -> Self | None:
        """The `owner` include as an identity.

        `specificResource` wins over the JSON:API envelope: an organization owner arrives as a
        `contacts` resource, and `organizations` is the answer a caller can act on. The id is taken
        from the *same* reference as the type, never mixed.
        """
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


class InvestorTypeResponse(OmitNoneModel):
    """The account's investor type, identity only."""

    id: str = Field(description="Backstop investor-type id.")
    name: str | None = Field(default=None, description="Investor-type name, e.g. 'Fund of Funds'.")

    @classmethod
    def from_investor_type(cls, investor_type: InvestorTypeDto | None) -> Self | None:
        if investor_type is None:
            return None
        return cls(id=investor_type.id, name=investor_type.name)

    @classmethod
    def from_included(
        cls, investor_type: IncludedResource[InvestorTypeAttributes] | None
    ) -> Self | None:
        if investor_type is None:
            return None
        return cls(id=investor_type.id, name=investor_type.attributes.name)


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

    @classmethod
    def from_attributes(cls, qualification: InvestorQualificationAttributes | None) -> Self | None:
        if qualification is None or (qualification.status is None and qualification.option is None):
            return None
        return cls(status=qualification.status, option=qualification.option)


class AccountRowResponse(OmitNoneModel):
    """One account: identity, owner, status, and the product when it was side-loaded."""

    id: str = Field(
        description=(
            "Backstop account id. Distinct from the owner's party id. Echo it as `entity_id` "
            "with `entity_type='accounts'` on `get_time_series` — never invent one."
        )
    )
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

    @classmethod
    def from_record(cls, account: AccountRecordDto) -> Self:
        return cls(
            id=account.id,
            name=account.name,
            owner=OwnerResponse.from_owner(account.owner),
            investor_type=InvestorTypeResponse.from_investor_type(account.investor_type),
            currency=account.currency,
            account_start_date=account.account_start_date,
            closed_date=account.closed_date,
            ownership_type=account.ownership_type,
            investor_qualification=InvestorQualificationResponse.from_attributes(
                account.investor_qualification
            ),
            is_employee_account=account.is_employee_account,
            is_gp_account=account.is_gp_account,
            aml_check_complete=account.aml_check_complete,
            new_issue_eligible=account.new_issue_eligible,
            us_domiciled=account.us_domiciled,
            is_open=account.is_open,
        )

    @classmethod
    def from_resource(
        cls,
        resource: AccountApiResource,
        *,
        included: Included,
    ) -> Self:
        attributes = resource.attributes
        return cls(
            id=resource.id,
            name=attributes.name,
            owner=OwnerResponse.from_included(
                included.first(resource, "owner", schema=IncludedResource[OwnerAttributes])
            ),
            investor_type=InvestorTypeResponse.from_included(
                included.first(
                    resource, "investorType", schema=IncludedResource[InvestorTypeAttributes]
                )
            ),
            currency=attributes.currency,
            account_start_date=attributes.account_start_date,
            closed_date=attributes.closed_date,
            ownership_type=attributes.ownership_type,
            investor_qualification=InvestorQualificationResponse.from_attributes(
                attributes.investor_qualification
            ),
            is_employee_account=attributes.is_employee_account,
            is_gp_account=attributes.is_gp_account,
            aml_check_complete=attributes.aml_check_complete,
            new_issue_eligible=attributes.new_issue_eligible,
            us_domiciled=attributes.us_domiciled,
            is_open="closed_date" not in attributes.model_fields_set,
        )


class ProductCandidateResponse(CandidateResponse):
    """One ambiguous product match. Echo `id` as `entity_id` — never invent one."""

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
            "Backstop product id. Echo it as `product_id` on `get_product_investors`, or as "
            "`entity_id` with `entity_type='products'` on `get_time_series` — never invent one."
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

    @classmethod
    def from_candidate(cls, candidate: Candidate[ResolvedProductDto]) -> Self:
        product = candidate.value
        return cls(
            key=candidate.key,
            label=candidate.label,
            id=product.id,
            name=product.name,
            short_name=product.short_name,
        )


class ProductAmbiguousResponse(AmbiguousResponse[ProductCandidateResponse]):
    """Returned when more than one product matched and none was chosen.

    Show each candidate's `label` to the user, then retry with that `id` as `product_id`
    on `get_product_investors`, or as `entity_id` with `entity_type='products'` on
    `get_time_series`. Never invent one.
    """

    scope: str = Field(description="Collection the query was resolved against. Always 'products'.")
    candidates: list[ProductCandidateResponse] = Field(
        default_factory=list,
        description=(
            "The matching products. Show `label` to the user, then retry with that "
            "candidate's `id` as `product_id` on `get_product_investors`, or as `entity_id` "
            "with `entity_type='products'` on `get_time_series` — never invent one."
        ),
    )

    @classmethod
    def from_unresolved(cls, result: Unresolved[ResolvedProductDto]) -> Self | NotFoundResponse:
        return unresolved_response(
            result,
            ambiguous_model=cls,
            to_candidate=ProductCandidateResponse.from_candidate,
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
