"""POST a CRM note against a party via the top-level `/notes` collection.

Top-level rather than nested `POST /{segment}/{id}/notes` because the nested route is not
uniformly writable: `POST /contacts/{id}/notes` answers `403 "contacts/notes is read only."`
The top-level route accepts every `SearchType` parent (verified live for organizations,
people, employees and contacts) and the record still lands in that party's `/activities`
feed, which is what `get_activity_history` reads.
"""

import logging
from datetime import date

from backstop_mcp.backstop_client import BackstopApiSingleResourceDocument, BackstopClient
from backstop_mcp.features.activity_writes.api_responses import NoteAttributes
from backstop_mcp.features.activity_writes.commands._json_api_utils import (
    isoformat,
    json_api_create,
    omit_none_values,
    party_resource_link,
    relationship_data,
    secondary_resource_link,
)
from backstop_mcp.features.activity_writes.internal_dto import AuthorDto
from backstop_mcp.features.activity_writes.log_activity_input import NoteActivityInput
from backstop_mcp.features.activity_writes.responses import LoggedNoteResponse
from backstop_mcp.features.system_users import system_user_relationship

logger = logging.getLogger(__name__)

_NoteDocument = BackstopApiSingleResourceDocument[NoteAttributes]


class LogNoteCommand:
    """Create a note via top-level `POST /notes`."""

    def __init__(self, *, client: BackstopClient) -> None:
        self._client: BackstopClient = client

    async def run(
        self,
        *,
        activity: NoteActivityInput,
        party_id: str,
        author: AuthorDto,
        secondary_party_id: str | None = None,
    ) -> LoggedNoteResponse:
        secondary = secondary_resource_link(
            party_id=party_id,
            secondary_party_id=secondary_party_id,
            secondary_search_type=activity.secondary_search_type,
        )
        tags = relationship_data("activity-tags", activity.activity_tag_ids)
        relationships: dict[str, object] = {"author": system_user_relationship(author.id)}
        if tags is not None:
            relationships["activityTags"] = tags
        payload = json_api_create(
            resource_type="notes",
            attributes=omit_none_values(
                {
                    "title": activity.title,
                    "description": activity.description,
                    # Required by Backstop (`400 "Field effectiveDate is required"`), so an
                    # omitted backdate becomes today rather than a rejected request.
                    "effectiveDate": isoformat(activity.effective_date or date.today()),
                    "attachedTo": party_resource_link(
                        party_id=party_id, search_type=activity.search_type
                    ),
                    "linkedResources": [secondary] if secondary is not None else None,
                }
            ),
            relationships=relationships,
        )
        document = await self._client.post("/notes", schema=_NoteDocument, json=payload)
        logger.info(
            "activity_writes.note.created",
            extra={"id": document.data.id, "party_id": party_id},
        )
        return LoggedNoteResponse(id=document.data.id, title=activity.title)
