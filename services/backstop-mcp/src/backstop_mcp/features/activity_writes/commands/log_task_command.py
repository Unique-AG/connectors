"""POST a CRM task. Tasks have no author, activity tags, or effectiveDate."""

import logging

from backstop_mcp.backstop_client import BackstopApiSingleResourceDocument, BackstopClient
from backstop_mcp.features.activity_writes.api_responses import TaskAttributes
from backstop_mcp.features.activity_writes.commands._utils import (
    isoformat,
    json_api_create,
    omit_none_values,
    party_resource_link,
    secondary_resource_link,
)
from backstop_mcp.features.activity_writes.log_activity_input import TaskActivityInput
from backstop_mcp.features.activity_writes.responses import LoggedTaskResponse
from backstop_mcp.features.system_users import SystemUsersService

logger = logging.getLogger(__name__)

_PATH = "/tasks"
_TaskDocument = BackstopApiSingleResourceDocument[TaskAttributes]


class LogTaskCommand:
    """Create a task via `POST /tasks`."""

    def __init__(self, *, client: BackstopClient, system_users_service: SystemUsersService) -> None:
        self._client: BackstopClient = client
        self._system_users_service: SystemUsersService = system_users_service

    async def run(
        self,
        *,
        activity: TaskActivityInput,
        party_id: str,
        secondary_party_id: str | None = None,
    ) -> LoggedTaskResponse:
        secondary = secondary_resource_link(
            party_id=party_id,
            secondary_party_id=secondary_party_id,
            secondary_search_type=activity.secondary_search_type,
        )
        payload = json_api_create(
            resource_type="tasks",
            attributes=omit_none_values(
                {
                    "name": activity.title,
                    "details": activity.description,
                    "dueDate": isoformat(activity.due_date),
                    "sendNotification": activity.send_notification,
                    "attachedTo": party_resource_link(
                        party_id=party_id, search_type=activity.search_type
                    ),
                    "secondaryRegarding": secondary,
                    "assignedUser": await self._system_users_service.resolve_resource_link(
                        activity.assigned_user
                    ),
                }
            ),
        )
        document = await self._client.post(_PATH, schema=_TaskDocument, json=payload)
        logger.info(
            "activity_writes.task.created",
            extra={
                "id": document.data.id,
                "party_id": party_id,
                "send_notification": activity.send_notification,
            },
        )
        return LoggedTaskResponse(
            id=document.data.id,
            title=activity.title,
            send_notification=activity.send_notification,
        )
