"""Dispatch a validated `log_activity` input to the command for that `kind`."""

from typing import Self, assert_never

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.activity_writes.commands.log_email_command import LogEmailCommand
from backstop_mcp.features.activity_writes.commands.log_meeting_or_call_command import (
    LogMeetingOrCallCommand,
)
from backstop_mcp.features.activity_writes.commands.log_note_command import LogNoteCommand
from backstop_mcp.features.activity_writes.commands.log_task_command import LogTaskCommand
from backstop_mcp.features.activity_writes.internal_dto import AuthorDto
from backstop_mcp.features.activity_writes.log_activity_input import LogActivityInput
from backstop_mcp.features.activity_writes.responses import LoggedActivityResponse
from backstop_mcp.features.system_users import SystemUsersService
from backstop_mcp.features.time_zones import TimeZonesService


class LogActivityCommand:
    """One write: switch on `kind` and call the matching command.

    `party_id` and `secondary_party_id` are already resolved. This command does not look up
    a party. Meeting and call share one command — they are the same Backstop collection.
    """

    def __init__(
        self,
        *,
        log_note: LogNoteCommand,
        log_meeting_or_call: LogMeetingOrCallCommand,
        log_task: LogTaskCommand,
        log_email: LogEmailCommand,
    ) -> None:
        self._log_note: LogNoteCommand = log_note
        self._log_meeting_or_call: LogMeetingOrCallCommand = log_meeting_or_call
        self._log_task: LogTaskCommand = log_task
        self._log_email: LogEmailCommand = log_email

    @classmethod
    def from_collaborators(
        cls,
        *,
        client: BackstopClient,
        author: AuthorDto,
        time_zones: TimeZonesService,
        system_users: SystemUsersService,
    ) -> Self:
        return cls(
            log_note=LogNoteCommand(client=client, author=author),
            log_meeting_or_call=LogMeetingOrCallCommand(
                client=client, author=author, time_zones=time_zones
            ),
            log_task=LogTaskCommand(client=client, system_users=system_users),
            log_email=LogEmailCommand(client=client, author=author),
        )

    async def run(
        self,
        *,
        activity: LogActivityInput,
        party_id: str,
        secondary_party_id: str | None = None,
    ) -> LoggedActivityResponse:
        match activity.kind:
            case "note":
                return await self._log_note.run(
                    activity=activity,
                    party_id=party_id,
                    secondary_party_id=secondary_party_id,
                )
            case "meeting" | "call":
                return await self._log_meeting_or_call.run(
                    activity=activity,
                    party_id=party_id,
                    secondary_party_id=secondary_party_id,
                )
            case "task":
                return await self._log_task.run(
                    activity=activity,
                    party_id=party_id,
                    secondary_party_id=secondary_party_id,
                )
            case "email":
                return await self._log_email.run(
                    activity=activity,
                    party_id=party_id,
                    secondary_party_id=secondary_party_id,
                )
            case _:
                assert_never(activity.kind)
