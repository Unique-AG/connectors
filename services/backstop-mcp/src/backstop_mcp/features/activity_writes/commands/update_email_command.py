"""PATCH email metadata via `/emails/{id}`. Parsed subject/from/to are not writable."""

import logging
from urllib.parse import quote

from backstop_mcp.backstop_client import (
    BackstopApiSingleResourceDocument,
    BackstopClient,
    json_api_update,
    omit_none_values,
)
from backstop_mcp.features.activity_writes.api_responses import EmailAttributes
from backstop_mcp.features.activity_writes.commands._json_api_utils import (
    activity_tag_relationship,
)
from backstop_mcp.features.activity_writes.commands.extract_collection import extract_collection
from backstop_mcp.features.activity_writes.responses import UpdatedActivityResponse
from backstop_mcp.features.activity_writes.update_activity_input import UpdateEmailInput
from backstop_mcp.utils import parse_activity_handle

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
        handle = parse_activity_handle(activity.activity_id)
        collection, resource_id = extract_collection(handle, kind=activity.kind)
        path = f"/{collection}/{quote(resource_id, safe='')}"
        payload = json_api_update(
            resource_type=collection,
            resource_id=resource_id,
            attributes=omit_none_values({"displaySubject": activity.display_subject}),
            relationships=omit_none_values({"activityTags": activity_tag_relationship(activity)})
            or None,
        )
        document = await self._client.patch(path, schema=_Document, json=payload)
        logger.info("activity_writes.email.updated", extra={"id": document.data.id})
        return UpdatedActivityResponse(id=document.data.id, resource_type="emails")
