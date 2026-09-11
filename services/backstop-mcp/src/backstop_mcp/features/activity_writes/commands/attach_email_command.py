"""POST a real `.msg`/`.eml` import via `POST /emails` with gzip+base64 `data`.

`data` and `emailFormat` are both mandatory on this collection — Backstop answers
`400 "Field data is required in POST request."` without a blob, which is why there is no
metadata-only email create. Plain base64 is rejected with
`400 "You should Zip and encode dto data with Base64 schema"`.
"""

import logging

from backstop_mcp.backstop_client import BackstopApiSingleResourceDocument, BackstopClient
from backstop_mcp.features.activity_writes.api_responses import EmailAttributes
from backstop_mcp.features.activity_writes.attach_file_input import EmailFileInput
from backstop_mcp.features.activity_writes.commands._file_data_utils import encode_file_data
from backstop_mcp.features.activity_writes.commands._json_api_utils import (
    json_api_create,
    omit_none_values,
    party_resource_link,
    relationship_data,
)
from backstop_mcp.features.activity_writes.internal_dto import AuthorDto
from backstop_mcp.features.activity_writes.responses import AttachedFileResponse
from backstop_mcp.features.system_users import system_user_relationship

logger = logging.getLogger(__name__)

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
        relationships: dict[str, object] = {"createdBy": system_user_relationship(author.id)}
        if tags is not None:
            relationships["activityTags"] = tags
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
                }
            ),
            relationships=relationships,
        )
        document = await self._client.post("/emails", schema=_EmailDocument, json=payload)
        logger.info(
            "activity_writes.email.imported", extra={"id": document.data.id, "party_id": party_id}
        )
        return AttachedFileResponse(id=document.data.id, kind="email")
