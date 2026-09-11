"""PATCH a CRM task via `/tasks/{id}`. `assignedUser` is a relationship, not an attribute."""

import logging

from backstop_mcp.backstop_client import BackstopApiSingleResourceDocument, BackstopClient
from backstop_mcp.features.activity_writes.api_responses import TaskAttributes
from backstop_mcp.features.activity_writes.commands._activity_resource_location import (
    ActivityResourceLocation,
)
from backstop_mcp.features.activity_writes.commands._json_api_utils import (
    isoformat,
    json_api_update,
    omit_none_values,
)
from backstop_mcp.features.activity_writes.responses import UpdatedActivityResponse
from backstop_mcp.features.activity_writes.update_activity_input import UpdateTaskInput
from backstop_mcp.features.system_users import SystemUsersService

logger = logging.getLogger(__name__)

_Document = BackstopApiSingleResourceDocument[TaskAttributes]


class UpdateTaskCommand:
    """Update a task via `PATCH /tasks/{id}`."""

    def __init__(self, *, client: BackstopClient, system_users_service: SystemUsersService) -> None:
        self._client: BackstopClient = client
        self._system_users_service: SystemUsersService = system_users_service

    async def run(self, *, activity: UpdateTaskInput) -> UpdatedActivityResponse:
        location = ActivityResourceLocation.from_activity_id(
            kind=activity.kind, activity_id=activity.activity_id
        )
        payload = json_api_update(
            resource_type=location.collection,
            resource_id=location.resource_id,
            attributes=omit_none_values(
                {
                    "name": activity.title,
                    "details": activity.description,
                    "dueDate": isoformat(activity.due_date),
                    "sendNotification": activity.send_notification,
                }
            ),
            relationships=omit_none_values(
                {
                    "assignedUser": await self._system_users_service.resolve_relationship(
                        activity.assigned_user
                    )
                }
            )
            or None,
        )
        document = await self._client.patch(location.path, schema=_Document, json=payload)
        logger.info("activity_writes.task.updated", extra={"id": document.data.id})
        return UpdatedActivityResponse(id=document.data.id, resource_type="tasks")
