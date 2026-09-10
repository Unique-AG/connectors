"""POST a CRM note against the parent party's nested `/notes` collection."""

import logging
from urllib.parse import quote

from backstop_mcp.backstop_client import BackstopApiSingleResourceDocument, BackstopClient
from backstop_mcp.features.activity_writes.api_responses import NoteAttributes
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
from backstop_mcp.features.activity_writes.log_activity_input import NoteActivityInput
from backstop_mcp.features.activity_writes.responses import LoggedNoteResponse

logger = logging.getLogger(__name__)

_NoteDocument = BackstopApiSingleResourceDocument[NoteAttributes]


class LogNoteCommand:
    """Create a note via nested `POST /{segment}/{id}/notes`."""

    def __init__(self, *, client: BackstopClient, author: AuthorDto) -> None:
        self._client: BackstopClient = client
        self._author: AuthorDto = author

    async def run(
        self,
        *,
        activity: NoteActivityInput,
        party_id: str,
        secondary_party_id: str | None = None,
    ) -> LoggedNoteResponse:
        path = f"/{activity.search_type}/{quote(party_id, safe='')}/notes"
        secondary = secondary_resource_link(
            party_id=party_id,
            secondary_party_id=secondary_party_id,
            secondary_search_type=activity.secondary_search_type,
        )
        tags = relationship_data("activity-tags", activity.activity_tag_ids)
        payload = json_api_create(
            resource_type="notes",
            attributes=compact_attributes(
                {
                    "title": activity.title,
                    "description": activity.description,
                    "effectiveDate": isoformat(activity.effective_date),
                    "attachedTo": party_resource_link(
                        party_id=party_id, search_type=activity.search_type
                    ),
                    "linkedResources": [secondary] if secondary is not None else None,
                    "author": system_user_resource_link(self._author.id),
                }
            ),
            relationships={"activityTags": tags} if tags is not None else None,
        )
        document = await self._client.post(path, schema=_NoteDocument, json=payload)
        logger.info(
            "activity_writes.note.created",
            extra={"id": document.data.id, "party_id": party_id},
        )
        return LoggedNoteResponse(id=document.data.id, title=activity.title)
