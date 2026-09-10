"""Dispatch a validated `log_activity` input to the command for that `kind`."""

from typing import assert_never

from backstop_mcp.features.activity_writes.commands.log_email_command import LogEmailCommand
from backstop_mcp.features.activity_writes.commands.log_meeting_or_call_command import (
    LogMeetingOrCallCommand,
)
from backstop_mcp.features.activity_writes.commands.log_note_command import LogNoteCommand
from backstop_mcp.features.activity_writes.commands.log_task_command import LogTaskCommand
from backstop_mcp.features.activity_writes.internal_dto import AuthorDto
from backstop_mcp.features.activity_writes.log_activity_input import LogActivityInput
from backstop_mcp.features.activity_writes.responses import LoggedActivityResponse


class LogActivityCommand:
    """One write: switch on `kind` and call the matching command.

    `party_id` and `secondary_party_id` are already resolved. This command does not look up
    a party. Meeting and call share one command — they are the same Backstop collection.
    """

    def __init__(
        self,
        *,
        log_note_command: LogNoteCommand,
        log_meeting_or_call_command: LogMeetingOrCallCommand,
        log_task_command: LogTaskCommand,
        log_email_command: LogEmailCommand,
    ) -> None:
        self._log_note_command: LogNoteCommand = log_note_command
        self._log_meeting_or_call_command: LogMeetingOrCallCommand = log_meeting_or_call_command
        self._log_task_command: LogTaskCommand = log_task_command
        self._log_email_command: LogEmailCommand = log_email_command

    async def run(
        self,
        *,
        activity: LogActivityInput,
        party_id: str,
        author: AuthorDto,
        secondary_party_id: str | None = None,
    ) -> LoggedActivityResponse:
        match activity.kind:
            case "note":
                return await self._log_note_command.run(
                    activity=activity,
                    party_id=party_id,
                    author=author,
                    secondary_party_id=secondary_party_id,
                )
            case "meeting" | "call":
                return await self._log_meeting_or_call_command.run(
                    activity=activity,
                    party_id=party_id,
                    author=author,
                    secondary_party_id=secondary_party_id,
                )
            case "task":
                return await self._log_task_command.run(
                    activity=activity,
                    party_id=party_id,
                    secondary_party_id=secondary_party_id,
                )
            case "email":
                return await self._log_email_command.run(
                    activity=activity,
                    party_id=party_id,
                    author=author,
                    secondary_party_id=secondary_party_id,
                )
            case _:
                assert_never(activity.kind)
