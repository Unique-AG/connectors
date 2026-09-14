"""POST a CRM note against a party via the top-level `/notes` collection.

Top-level rather than nested `POST /{segment}/{id}/notes` because the nested route is not
uniformly writable: `POST /contacts/{id}/notes` answers `403 "contacts/notes is read only."`
The top-level route accepts every `SearchType` parent (verified live for organizations,
people, employees and contacts) and the record still lands in that party's `/activities`
feed, which is what `get_activity_history` reads.
"""

import logging

from backstop_mcp.backstop_client import (
    BackstopApiSingleResourceDocument,
    BackstopClient,
    json_api_create,
    omit_none_values,
)
from backstop_mcp.features.activity_writes.api_responses import NoteAttributes
from backstop_mcp.features.activity_writes.commands._json_api_utils import (
    activity_base_attributes,
    activity_tag_relationship,
    party_resource_link,
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
        payload = json_api_create(
            resource_type="notes",
            attributes=omit_none_values(
                {
                    **activity_base_attributes(activity, default_effective_today=True),
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
        document = await self._client.post("/notes", schema=_NoteDocument, json=payload)
        logger.info(
            "activity_writes.note.created",
            extra={"id": document.data.id, "party_id": party_id},
        )
        return LoggedNoteResponse(id=document.data.id, title=activity.title)
