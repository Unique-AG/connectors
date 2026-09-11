"""DELETE a CRM activity. Backstop hard-deletes; there is no recycle bin."""

import logging

from backstop_mcp.backstop_client import (
    BackstopApiError,
    BackstopApiSingleResourceDocument,
    BackstopClient,
)
from backstop_mcp.features.activity_writes.api_responses import DeletedResourceAttributes
from backstop_mcp.features.activity_writes.commands._activity_resource_location import (
    ActivityResourceLocation,
)
from backstop_mcp.features.activity_writes.commands._write_error_utils import (
    reraise_activity_write_error,
)
from backstop_mcp.features.activity_writes.delete_activity_input import DeleteActivityInput
from backstop_mcp.features.activity_writes.responses import DeletedActivityResponse

logger = logging.getLogger(__name__)

# All six collections answer `204` with an empty body, so `client.delete` returns before
# deserializing and this schema is never used. It still has to be a real attributes model,
# and a collection-specific one here would read as if delete were note-shaped.
_Document = BackstopApiSingleResourceDocument[DeletedResourceAttributes]


class DeleteActivityCommand:
    """Hard-delete via `DELETE /{collection}/{id}`. One command: the body is empty."""

    def __init__(self, *, client: BackstopClient) -> None:
        self._client: BackstopClient = client

    async def run(self, *, activity: DeleteActivityInput) -> DeletedActivityResponse:
        location = ActivityResourceLocation.from_activity_id(
            kind=activity.kind, activity_id=activity.activity_id
        )
        try:
            await self._client.delete(location.path, schema=_Document)
        except BackstopApiError as exc:
            reraise_activity_write_error(exc)
        logger.warning(
            "activity_writes.activity.deleted",
            extra={
                "id": location.resource_id,
                "kind": activity.kind,
                "collection": location.collection,
            },
        )
        return DeletedActivityResponse(id=location.resource_id, resource_type=location.collection)
