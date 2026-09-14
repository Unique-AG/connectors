"""POST a document against the party via top-level `POST /documents`."""

import logging

from backstop_mcp.backstop_client import (
    BackstopApiSingleResourceDocument,
    BackstopClient,
    json_api_create,
    omit_none_values,
)
from backstop_mcp.features.activity_writes.api_responses import DocumentAttributes
from backstop_mcp.features.activity_writes.attach_file_input import DocumentFileInput
from backstop_mcp.features.activity_writes.commands._file_data_utils import encode_file_data
from backstop_mcp.features.activity_writes.commands._json_api_utils import (
    activity_base_attributes,
    activity_tag_relationship,
    party_resource_link,
    secondary_resource_link,
)
from backstop_mcp.features.activity_writes.internal_dto import AuthorDto
from backstop_mcp.features.activity_writes.responses import AttachedFileResponse
from backstop_mcp.features.system_users import system_user_relationship

logger = logging.getLogger(__name__)

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
        payload = json_api_create(
            resource_type="documents",
            attributes=omit_none_values(
                {
                    **activity_base_attributes(activity, default_effective_today=True),
                    "title": activity.title or activity.file_name,
                    "documentName": activity.file_name,
                    "data": encode_file_data(activity.content),
                    "attachedTo": party_resource_link(
                        party_id=party_id, search_type=activity.search_type
                    ),
                    "linkedResources": [secondary] if secondary is not None else None,
                }
            ),
            relationships=omit_none_values(
                {
                    "author": system_user_relationship(author.id),
                    "activityTags": activity_tag_relationship(activity, omit_empty=True),
                }
            ),
        )
        document = await self._client.post("/documents", schema=_DocumentDocument, json=payload)
        logger.info(
            "activity_writes.document.created",
            extra={"id": document.data.id, "party_id": party_id},
        )
        return AttachedFileResponse(id=document.data.id, kind="document")
