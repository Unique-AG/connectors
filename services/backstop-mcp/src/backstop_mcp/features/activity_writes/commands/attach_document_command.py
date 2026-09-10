"""POST a document against the party via top-level `POST /documents`."""

import logging
from datetime import date

from backstop_mcp.backstop_client import BackstopApiSingleResourceDocument, BackstopClient
from backstop_mcp.features.activity_writes.api_responses import DocumentAttributes
from backstop_mcp.features.activity_writes.attach_file_input import DocumentFileInput
from backstop_mcp.features.activity_writes.commands._attachment_utils import encode_file_data
from backstop_mcp.features.activity_writes.commands._utils import (
    compact_attributes,
    isoformat,
    json_api_create,
    party_resource_link,
    relationship_data,
    secondary_resource_link,
    system_user_resource_link,
)
from backstop_mcp.features.activity_writes.internal_dto import AuthorDto
from backstop_mcp.features.activity_writes.responses import AttachedFileResponse

logger = logging.getLogger(__name__)

_PATH = "/documents"
_DocumentDocument = BackstopApiSingleResourceDocument[DocumentAttributes]


class AttachDocumentCommand:
    """Create a document via `POST /documents` with gzip+base64 `data`."""

    def __init__(self, *, client: BackstopClient) -> None:
        self._client: BackstopClient = client

    async def run(
        self,
        *,
        activity: DocumentFileInput,
        party_id: str,
        author: AuthorDto,
        secondary_party_id: str | None = None,
    ) -> AttachedFileResponse:
        secondary = secondary_resource_link(
            party_id=party_id,
            secondary_party_id=secondary_party_id,
            secondary_search_type=activity.secondary_search_type,
        )
        tags = relationship_data("activity-tags", activity.activity_tag_ids)
        title = activity.title or activity.file_name
        payload = json_api_create(
            resource_type="documents",
            attributes=compact_attributes(
                {
                    "title": title,
                    "description": activity.description,
                    "documentName": activity.file_name,
                    "data": encode_file_data(activity.content),
                    "effectiveDate": isoformat(activity.effective_date or date.today()),
                    "attachedTo": party_resource_link(
                        party_id=party_id, search_type=activity.search_type
                    ),
                    "linkedResources": [secondary] if secondary is not None else None,
                    "author": system_user_resource_link(author.id),
                }
            ),
            relationships={"activityTags": tags} if tags is not None else None,
        )
        document = await self._client.post(_PATH, schema=_DocumentDocument, json=payload)
        logger.info(
            "activity_writes.document.created",
            extra={"id": document.data.id, "party_id": party_id},
        )
        return AttachedFileResponse(id=document.data.id, kind="document")
