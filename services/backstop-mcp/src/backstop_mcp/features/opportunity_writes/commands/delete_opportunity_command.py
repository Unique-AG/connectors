"""DELETE a CRM opportunity. Backstop hard-deletes; there is no recycle bin."""

import logging
from urllib.parse import quote

from mcp_observability import traced

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.opportunity_writes.delete_opportunity_input import DeleteOpportunityInput
from backstop_mcp.features.opportunity_writes.responses import DeletedOpportunityResponse

logger = logging.getLogger(__name__)

_RESOURCE_TYPE = "opportunities"


class DeleteOpportunityCommand:
    """Hard-delete via `DELETE /opportunities/{id}`. One command: the body is empty."""

    def __init__(self, *, client: BackstopClient) -> None:
        self._client: BackstopClient = client

    @traced(
        arguments=("opportunity.opportunity_id",),
        result=lambda response: {"id": response.id},
    )
    async def run(self, *, opportunity: DeleteOpportunityInput) -> DeletedOpportunityResponse:
        path = f"/{_RESOURCE_TYPE}/{quote(opportunity.opportunity_id, safe='')}"
        await self._client.delete(path)
        logger.warning(
            "Deleted opportunity",
            extra={"id": opportunity.opportunity_id, "collection": _RESOURCE_TYPE},
        )
        return DeletedOpportunityResponse(
            id=opportunity.opportunity_id, resource_type=_RESOURCE_TYPE
        )
