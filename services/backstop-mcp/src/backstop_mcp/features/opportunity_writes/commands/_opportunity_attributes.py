"""Opportunity write payload helpers.

Python-name → wire-key mapping for opportunity attributes and relationships.
JSON:API envelopes (`json_api_update`, `relationship_data`, …) live on
`backstop_client`.
"""

from backstop_mcp.backstop_client import isoformat, relationship_data, relationship_to_one
from backstop_mcp.features.opportunity_writes.update_opportunity_input import UpdateOpportunityInput

__all__ = [
    "opportunity_attributes",
    "opportunity_relationships",
]


def opportunity_attributes(opportunity: UpdateOpportunityInput) -> dict[str, object | None]:
    """Wire attributes for an opportunity write. Callers wrap with `omit_none_values`."""
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
        "stageEffectiveDate": isoformat(opportunity.stage_effective_date),
        "waitlistId": opportunity.waitlist_id,
    }


def opportunity_relationships(
    opportunity: UpdateOpportunityInput,
    *,
    owner: dict[str, object] | None,
    stage_id: str | None,
    add_notify: tuple[str, ...] | None,
    omit_empty: bool = False,
) -> dict[str, object | None]:
    """Wire relationships for an opportunity write.

    `owner` is the pre-resolved `representative` payload; `stage_id` and
    `add_notify` are already resolved ids. Creates pass `omit_empty=True` so `()`
    is not sent; updates leave `()` as a clear. Callers wrap with `omit_none_values`.
    """
    notify_ids = add_notify
    if omit_empty:
        notify_ids = notify_ids or None
    return {
        "stage": relationship_to_one("opportunity-stages", stage_id),
        "investor": relationship_to_one("contacts", opportunity.investor_id),
        "product": relationship_to_one("products", opportunity.product_id),
        "primaryContact": relationship_to_one("people", opportunity.primary_contact_id),
        "referralSource": relationship_to_one("contacts", opportunity.referral_source_id),
        "representative": owner,
        "investorType": relationship_to_one("investor-types", opportunity.investor_type_id),
        "ccedUsers": relationship_data("system-users", notify_ids),
    }
