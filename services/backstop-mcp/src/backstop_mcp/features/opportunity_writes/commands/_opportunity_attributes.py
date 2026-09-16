"""Opportunity write payload helpers.

Python-name → wire-key mapping for opportunity attributes and relationships.
JSON:API envelopes (`json_api_update`, `relationship_data`, …) live on
`backstop_client`.
"""

from backstop_mcp.backstop_client import (
    BackstopApiSingleResourceDocument,
    isoformat,
    relationship_data,
    relationship_to_one,
)
from backstop_mcp.features.opportunities import (
    OpportunityResourceAttributes,
    OpportunityStageResponse,
)
from backstop_mcp.features.opportunity_writes.create_opportunity_input import (
    CreateOpportunityInput,
)
from backstop_mcp.features.opportunity_writes.update_opportunity_input import UpdateOpportunityInput
from backstop_mcp.utils import first_item

__all__ = [
    "OPPORTUNITY_READ_INCLUDE",
    "opportunity_attributes",
    "opportunity_entity_type_id",
    "opportunity_relationships",
    "unique_catalog_entity_type_id",
]

OPPORTUNITY_READ_INCLUDE = "stage,clientDefinedEntityType"
_OpportunityDocument = BackstopApiSingleResourceDocument[OpportunityResourceAttributes]


def opportunity_attributes(
    opportunity: CreateOpportunityInput | UpdateOpportunityInput,
) -> dict[str, object | None]:
    """Wire attributes for an opportunity write. Callers wrap with `omit_none_values`."""
    stage_effective_date = (
        opportunity.stage_effective_date
        if isinstance(opportunity, UpdateOpportunityInput)
        else None
    )
    return {
        "name": opportunity.name,
        "description": opportunity.description,
        "aliases": opportunity.aliases,
        "otherId": opportunity.other_id,
        "type": opportunity.classification,
        "currencyCode": opportunity.currency_code,
        "isErisa": opportunity.is_erisa,
        "requestedAmount": opportunity.requested_amount,
        "allocatedAmount": opportunity.allocated_amount,
        "probability": opportunity.probability,
        "expectedInvestmentDate": isoformat(opportunity.expected_investment_date),
        "stageEffectiveDate": isoformat(stage_effective_date),
        "waitlistId": opportunity.waitlist_id,
    }


def opportunity_relationships(
    opportunity: CreateOpportunityInput | UpdateOpportunityInput,
    *,
    owner: dict[str, object] | None,
    stage_id: str | None,
    add_notify: tuple[str, ...] | None,
    omit_empty: bool = False,
    investor_id: str | None = None,
) -> dict[str, object | None]:
    """Wire relationships for an opportunity write.

    `owner` is the pre-resolved `representative` payload; `stage_id` and
    `add_notify` are already resolved ids. Creates pass `omit_empty=True` so `()`
    is not sent; updates leave `()` as a clear. Creates pass the resolved
    `investor_id` keyword; updates read `investor_id` from the input. Callers
    wrap with `omit_none_values`.
    """
    if isinstance(opportunity, UpdateOpportunityInput):
        notify_ids = add_notify
        resolved_investor_id = opportunity.investor_id
    else:
        notify_ids = None
        resolved_investor_id = investor_id
    if omit_empty:
        notify_ids = notify_ids or None
    return {
        "stage": relationship_to_one("opportunity-stages", stage_id),
        "investor": relationship_to_one("contacts", resolved_investor_id),
        "product": relationship_to_one("products", opportunity.product_id),
        "primaryContact": relationship_to_one("people", opportunity.primary_contact_id),
        "referralSource": relationship_to_one("contacts", opportunity.referral_source_id),
        "representative": owner,
        "investorType": relationship_to_one("investor-types", opportunity.investor_type_id),
        "ccedUsers": relationship_data("system-users", notify_ids),
    }


def opportunity_entity_type_id(document: _OpportunityDocument) -> str | None:
    related = first_item(document.data.related_ids("clientDefinedEntityType"))
    if related is not None:
        return related
    value = document.data.attributes.client_defined_entity_type
    return str(value) if value is not None else None


def unique_catalog_entity_type_id(catalog: dict[str, OpportunityStageResponse]) -> str | None:
    type_ids = {type_id for stage in catalog.values() for type_id in stage.opportunity_type_ids}
    if len(type_ids) != 1:
        return None
    return next(iter(type_ids))
