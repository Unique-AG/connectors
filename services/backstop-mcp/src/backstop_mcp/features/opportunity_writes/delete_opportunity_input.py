"""`delete_opportunity` input: the opportunity id. Delete is permanent."""

from pydantic import BaseModel, Field

from backstop_mcp.models import NonEmptyStr

__all__ = [
    "DELETE_OPPORTUNITY_INPUT_DESCRIPTION",
    "DeleteOpportunityInput",
]

DELETE_OPPORTUNITY_INPUT_DESCRIPTION = (
    "Required. The opportunity to hard-delete. Needs `opportunity_id` from "
    "`get_opportunities` or `get_opportunities_by_ids`. Never invent an id. Deletion is "
    "permanent: Backstop has no recycle bin. The tool reads the record and asks the user "
    "to confirm when the client can elicit; otherwise it deletes immediately."
)


class DeleteOpportunityInput(BaseModel):
    """Hard-delete a CRM opportunity."""

    opportunity_id: NonEmptyStr = Field(
        description=(
            "Required. Backstop opportunity id from `get_opportunities` or "
            "`get_opportunities_by_ids`. Never invent or guess."
        )
    )
