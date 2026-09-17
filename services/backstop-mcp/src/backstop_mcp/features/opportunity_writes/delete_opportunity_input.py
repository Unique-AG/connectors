"""`delete_opportunity` input: the opportunity id. Delete is permanent."""

from pydantic import BaseModel, Field

from backstop_mcp.features.elicitation_utils import CONFIRM_FIELD_DESCRIPTION, REFUSE_BULK_DELETE
from backstop_mcp.models import NonEmptyStr

__all__ = [
    "DELETE_OPPORTUNITY_INPUT_DESCRIPTION",
    "DeleteOpportunityInput",
]

DELETE_OPPORTUNITY_INPUT_DESCRIPTION = (
    "Required. The opportunity to hard-delete. Needs `opportunity_id` from "
    + "`get_opportunities` or `get_opportunities_by_ids`. Never invent an id. Deletion is "
    + "permanent: Backstop has no recycle bin. The tool asks the user to confirm when the "
    + "client can show a form (MCP 2026-07-28+). On an older protocol it returns "
    + "`needs_confirmation` so the model can ask in chat and retry with `confirm=true`. "
    + "When the client never advertised elicitation, it deletes immediately. "
    + REFUSE_BULK_DELETE
)


class DeleteOpportunityInput(BaseModel):
    """Hard-delete a CRM opportunity."""

    opportunity_id: NonEmptyStr = Field(
        description=(
            "Required. Backstop opportunity id from `get_opportunities` or "
            "`get_opportunities_by_ids`. Never invent or guess."
        )
    )
    confirm: bool = Field(default=False, description=CONFIRM_FIELD_DESCRIPTION)
