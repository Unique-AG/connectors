"""PATCH document metadata via `/documents/{id}`. The file blob is not replaced."""

import logging

from backstop_mcp.backstop_client import BackstopApiSingleResourceDocument, BackstopClient
from backstop_mcp.features.activity_writes.api_responses import DocumentAttributes
from backstop_mcp.features.activity_writes.commands._utils import (
    activity_target,
    isoformat,
    json_api_update,
    omit_none_values,
    relationship_replace,
)
from backstop_mcp.features.activity_writes.responses import UpdatedActivityResponse
from backstop_mcp.features.activity_writes.update_activity_input import UpdateDocumentInput

logger = logging.getLogger(__name__)

_Document = BackstopApiSingleResourceDocument[DocumentAttributes]


class UpdateDocumentCommand:
    """Update document metadata via `PATCH /documents/{id}`."""

    def __init__(self, *, client: BackstopClient) -> None:
        self._client: BackstopClient = client

    async def run(self, *, activity: UpdateDocumentInput) -> UpdatedActivityResponse:
        path, resource_id, collection = activity_target(
            kind=activity.kind, activity_id=activity.activity_id
        )
        tags = relationship_replace("activity-tags", activity.activity_tag_ids)
        payload = json_api_update(
            resource_type=collection,
            resource_id=resource_id,
            attributes=omit_none_values(
                {
                    "title": activity.title,
                    "description": activity.description,
                    "effectiveDate": isoformat(activity.effective_date),
                }
            ),
            relationships={"activityTags": tags} if tags is not None else None,
        )
        document = await self._client.patch(path, schema=_Document, json=payload)
        logger.info("activity_writes.document.updated", extra={"id": document.data.id})
        return UpdatedActivityResponse(id=document.data.id, resource_type="documents")
