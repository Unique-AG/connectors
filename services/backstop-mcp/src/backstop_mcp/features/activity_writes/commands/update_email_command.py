"""PATCH email metadata via `/emails/{id}`. Parsed subject/from/to are not writable."""

import logging

from backstop_mcp.backstop_client import BackstopApiSingleResourceDocument, BackstopClient
from backstop_mcp.features.activity_writes.api_responses import EmailAttributes
from backstop_mcp.features.activity_writes.commands._utils import (
    activity_target,
    json_api_update,
    omit_none_values,
    relationship_replace,
)
from backstop_mcp.features.activity_writes.responses import UpdatedActivityResponse
from backstop_mcp.features.activity_writes.update_activity_input import UpdateEmailInput

logger = logging.getLogger(__name__)

_Document = BackstopApiSingleResourceDocument[EmailAttributes]


class UpdateEmailCommand:
    """Update email metadata via `PATCH /emails/{id}`.

    Backstop accepts only `displaySubject`, `activityTags`, and `createdBy` on this
    collection. Author is never a tool parameter, so this command sends the first two.
    """

    def __init__(self, *, client: BackstopClient) -> None:
        self._client: BackstopClient = client

    async def run(self, *, activity: UpdateEmailInput) -> UpdatedActivityResponse:
        path, resource_id, collection = activity_target(
            kind=activity.kind, activity_id=activity.activity_id
        )
        tags = relationship_replace("activity-tags", activity.activity_tag_ids)
        payload = json_api_update(
            resource_type=collection,
            resource_id=resource_id,
            attributes=omit_none_values({"displaySubject": activity.display_subject}),
            relationships={"activityTags": tags} if tags is not None else None,
        )
        document = await self._client.patch(path, schema=_Document, json=payload)
        logger.info("activity_writes.email.updated", extra={"id": document.data.id})
        return UpdatedActivityResponse(id=document.data.id, resource_type="emails")
