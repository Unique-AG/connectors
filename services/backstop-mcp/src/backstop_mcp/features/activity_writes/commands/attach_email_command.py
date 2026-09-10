"""POST a real `.msg`/`.eml` import via `POST /emails` with gzip+base64 `data`."""

import logging

from backstop_mcp.backstop_client import BackstopApiSingleResourceDocument, BackstopClient
from backstop_mcp.features.activity_writes.api_responses import EmailAttributes
from backstop_mcp.features.activity_writes.attach_file_input import EmailFileInput
from backstop_mcp.features.activity_writes.commands._attachment_utils import encode_file_data
from backstop_mcp.features.activity_writes.commands._utils import (
    json_api_create,
    omit_none_values,
    party_resource_link,
    relationship_data,
)
from backstop_mcp.features.activity_writes.internal_dto import AuthorDto
from backstop_mcp.features.activity_writes.responses import AttachedFileResponse
from backstop_mcp.features.system_users import system_user_resource_link

logger = logging.getLogger(__name__)

_PATH = "/emails"
_EmailDocument = BackstopApiSingleResourceDocument[EmailAttributes]


class AttachEmailCommand:
    """Import an email file via `POST /emails`."""

    def __init__(self, *, client: BackstopClient) -> None:
        self._client: BackstopClient = client

    async def run(
        self,
        *,
        activity: EmailFileInput,
        party_id: str,
        author: AuthorDto,
    ) -> AttachedFileResponse:
        tags = relationship_data("activity-tags", activity.activity_tag_ids)
        payload = json_api_create(
            resource_type="emails",
            attributes=omit_none_values(
                {
                    "displaySubject": activity.display_subject,
                    "emailFormat": activity.email_format,
                    "data": encode_file_data(activity.content),
                    "resources": [
                        party_resource_link(party_id=party_id, search_type=activity.search_type)
                    ],
                    "createdBy": system_user_resource_link(author.id),
                }
            ),
            relationships={"activityTags": tags} if tags is not None else None,
        )
        document = await self._client.post(_PATH, schema=_EmailDocument, json=payload)
        logger.info(
            "activity_writes.email.imported", extra={"id": document.data.id, "party_id": party_id}
        )
        return AttachedFileResponse(id=document.data.id, kind="email")
