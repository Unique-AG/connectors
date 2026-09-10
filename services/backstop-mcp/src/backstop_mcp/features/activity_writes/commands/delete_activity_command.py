"""DELETE a CRM activity. Backstop hard-deletes; there is no recycle bin."""

import logging

from backstop_mcp.backstop_client import (
    BackstopApiError,
    BackstopApiSingleResourceDocument,
    BackstopClient,
)
from backstop_mcp.features.activity_writes.api_responses import NoteAttributes
from backstop_mcp.features.activity_writes.commands._utils import activity_target
from backstop_mcp.features.activity_writes.commands._write_errors import (
    reraise_activity_write_error,
)
from backstop_mcp.features.activity_writes.delete_activity_input import DeleteActivityInput
from backstop_mcp.features.activity_writes.responses import DeletedActivityResponse

logger = logging.getLogger(__name__)

_Document = BackstopApiSingleResourceDocument[NoteAttributes]


class DeleteActivityCommand:
    """Hard-delete via `DELETE /{collection}/{id}`. One command: the body is empty."""

    def __init__(self, *, client: BackstopClient) -> None:
        self._client: BackstopClient = client

    async def run(self, *, activity: DeleteActivityInput) -> DeletedActivityResponse:
        path, resource_id, collection = activity_target(
            kind=activity.kind, activity_id=activity.activity_id
        )
        try:
            await self._client.delete(path, schema=_Document)
        except BackstopApiError as exc:
            reraise_activity_write_error(exc)
        logger.info(
            "activity_writes.activity.deleted",
            extra={"id": resource_id, "kind": activity.kind, "collection": collection},
        )
        return DeletedActivityResponse(id=resource_id, resource_type=collection)
