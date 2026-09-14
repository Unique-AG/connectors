"""DELETE a CRM activity. Backstop hard-deletes; there is no recycle bin."""

import logging
from urllib.parse import quote

from backstop_mcp.backstop_client import BackstopApiError, BackstopClient
from backstop_mcp.features.activity_writes.commands._write_error_utils import (
    reraise_activity_write_error,
)
from backstop_mcp.features.activity_writes.commands.extract_collection import extract_collection
from backstop_mcp.features.activity_writes.delete_activity_input import DeleteActivityInput
from backstop_mcp.features.activity_writes.responses import DeletedActivityResponse
from backstop_mcp.utils import parse_activity_handle

logger = logging.getLogger(__name__)


class DeleteActivityCommand:
    """Hard-delete via `DELETE /{collection}/{id}`. One command: the body is empty."""

    def __init__(self, *, client: BackstopClient) -> None:
        self._client: BackstopClient = client

    async def run(self, *, activity: DeleteActivityInput) -> DeletedActivityResponse:
        handle = parse_activity_handle(activity.activity_id)
        collection, resource_id = extract_collection(handle, kind=activity.kind)
        path = f"/{collection}/{quote(resource_id, safe='')}"
        try:
            await self._client.delete(path)
        except BackstopApiError as exc:
            reraise_activity_write_error(exc)
        logger.warning(
            "activity_writes.activity.deleted",
            extra={
                "id": resource_id,
                "kind": activity.kind,
                "collection": collection,
            },
        )
        return DeletedActivityResponse(id=resource_id, resource_type=collection)
