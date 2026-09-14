"""Parse an `activity_id` that `get_activity_detail` can fetch.

History email composites (`email_*` / `emails_*`) are `/emails` ids, not
`/entity-activity-details`, so they are rejected here. Writes that know `kind=email`
use `extract_collection` instead.
"""

import logging

from fastmcp.exceptions import ToolError

from backstop_mcp.utils import ParsedActivityHandle, parse_activity_handle

logger = logging.getLogger(__name__)

_EMAIL_RESOURCE_TYPES = frozenset({"email", "emails"})


def parse_activity_detail_handle(activity_id: str) -> ParsedActivityHandle:
    """A history composite or a search-row / create-echo bare id.

    Rejects a history email handle. A blank value is rejected by `parse_activity_handle`.
    """
    parsed = parse_activity_handle(activity_id)
    if parsed.resource_type in _EMAIL_RESOURCE_TYPES:
        logger.info("activity_history.handle.email_id", extra={"activity_id": parsed.handle})
        raise ToolError(
            f"{activity_id!r} is a get_activity_history email handle, not an "
            + "activity_id `get_activity_detail` can fetch. History emails come from "
            + "`/emails` (body via contentUrl), not `/entity-activity-details`. Use "
            + "`search_activities` for the body and attachment list."
        )
    if parsed.resource_type is None:
        logger.info("activity_history.handle.bare_id", extra={"activity_id": parsed.handle})
    return parsed
