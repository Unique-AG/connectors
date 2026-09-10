"""POST a CRM task. Tasks have no author, activity tags, or effectiveDate."""

import logging

from backstop_mcp.backstop_client import BackstopApiSingleResourceDocument, BackstopClient
from backstop_mcp.features.activity_writes.api_responses import TaskAttributes
from backstop_mcp.features.activity_writes.commands._utils import (
    compact_attributes,
    isoformat,
    json_api_create,
    party_resource_link,
    secondary_resource_link,
    system_user_resource_link,
)
from backstop_mcp.features.activity_writes.log_activity_input import TaskActivityInput
from backstop_mcp.features.activity_writes.responses import LoggedTaskResponse
from backstop_mcp.features.system_users import SystemUsersService

logger = logging.getLogger(__name__)

_PATH = "/tasks"
_TaskDocument = BackstopApiSingleResourceDocument[TaskAttributes]


class LogTaskCommand:
    """Create a task via `POST /tasks`."""

    def __init__(self, *, client: BackstopClient, system_users: SystemUsersService) -> None:
        self._client: BackstopClient = client
        self._system_users: SystemUsersService = system_users

    async def run(
        self,
        *,
        activity: TaskActivityInput,
        party_id: str,
        secondary_party_id: str | None = None,
    ) -> LoggedTaskResponse:
        assignee = await self._system_users.resolve_by_user_name(activity.assigned_user)
        secondary = secondary_resource_link(
            party_id=party_id,
            secondary_party_id=secondary_party_id,
            secondary_search_type=activity.secondary_search_type,
        )
        payload = json_api_create(
            resource_type="tasks",
            attributes=compact_attributes(
                {
                    "name": activity.title,
                    "details": activity.description,
                    "dueDate": isoformat(activity.due_date),
                    "sendNotification": activity.send_notification,
                    "attachedTo": party_resource_link(
                        party_id=party_id, search_type=activity.search_type
                    ),
                    "secondaryRegarding": secondary,
                    "assignedUser": system_user_resource_link(assignee.id),
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
