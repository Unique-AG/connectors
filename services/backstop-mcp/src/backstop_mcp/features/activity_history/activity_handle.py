"""The `{resourceType}_{resourceId}` handle a timeline record carries as its `activity_id`.

Confirmed live across all four activity streams: every record `/{segment}/{id}/activities`
returns has an id of exactly `f"{specificResource.resourceType}_{specificResource.resourceId}"` —
`meeting-or-calls_76537547` (both meetings and calls), `notes_26018215`,
`documents_127746731`. That composite is the only id `get_activity_history` hands out, so the
model always holds a resource type alongside a resource id and never has to guess which
collection an id belongs to.

The detail endpoints go the other way: `/entity-activity-details/{id}`,
`/meeting-or-calls/{id}` and `/meeting-or-calls/{id}/attendees` all take the **bare**
`resource_id`. Passing the composite to `/entity-activity-details` does not 404 — it answers
`200 {"data": null}`, so the mistake surfaces as a schema error rather than a not-found (see
`BackstopApiResourceDocument.require_data`). This module is where the two forms meet, so that
translation happens once instead of at each call site.
"""

import logging

from fastmcp.exceptions import ToolError

from backstop_mcp.features.activity_history.internal_dto import ActivityHandleDto

logger = logging.getLogger(__name__)

__all__ = ["MEETING_OR_CALL_RESOURCE_TYPE", "ActivityHandleDto", "parse_activity_handle"]

MEETING_OR_CALL_RESOURCE_TYPE = "meeting-or-calls"


def parse_activity_handle(activity_id: str) -> ActivityHandleDto:
    """Split a timeline `activity_id` into its resource type and bare resource id.

    Splits on the LAST underscore: resource ids are numeric, while a resource type can carry
    hyphens (`meeting-or-calls`), so the final separator is the unambiguous one.
    """
    resource_type, separator, resource_id = activity_id.rpartition("_")
    if not separator or not resource_type or not resource_id:
        logger.info("activity_history.handle.malformed", extra={"activity_id": activity_id})
        raise ToolError(
            f"{activity_id!r} is not a valid activity_id. Expected "
            + "'{resource_type}_{resource_id}' (e.g. 'meeting-or-calls_76537547', "
            + "'notes_26018215'), exactly as a get_activity_history record reports it."
        )
    return ActivityHandleDto(resource_type=resource_type, resource_id=resource_id)
