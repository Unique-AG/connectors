"""PATCH a CRM note via `/notes/{id}`."""

import logging
from urllib.parse import quote

from backstop_mcp.backstop_client import BackstopApiSingleResourceDocument, BackstopClient
from backstop_mcp.features.activity_writes.api_responses import NoteAttributes
from backstop_mcp.features.activity_writes.commands._json_api_utils import (
    isoformat,
    json_api_update,
    omit_none_values,
    relationship_data,
)
from backstop_mcp.features.activity_writes.commands.extract_collection import extract_collection
from backstop_mcp.features.activity_writes.responses import UpdatedActivityResponse
from backstop_mcp.features.activity_writes.update_activity_input import UpdateNoteInput
from backstop_mcp.utils import parse_activity_handle

logger = logging.getLogger(__name__)

_Document = BackstopApiSingleResourceDocument[NoteAttributes]


class UpdateNoteCommand:
    """Update a note via `PATCH /notes/{id}`."""

    def __init__(self, *, client: BackstopClient) -> None:
        self._client: BackstopClient = client

    async def run(self, *, activity: UpdateNoteInput) -> UpdatedActivityResponse:
        handle = parse_activity_handle(activity.activity_id)
        collection, resource_id = extract_collection(handle, kind=activity.kind)
        path = f"/{collection}/{quote(resource_id, safe='')}"
        tags = relationship_data("activity-tags", activity.activity_tag_ids)
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
        logger.info("activity_writes.note.updated", extra={"id": document.data.id})
        return UpdatedActivityResponse(id=document.data.id, resource_type="notes")
