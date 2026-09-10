"""Dispatch a validated `update_activity` input to the command for that `kind`."""

from typing import assert_never

from backstop_mcp.features.activity_writes.commands.update_document_command import (
    UpdateDocumentCommand,
)
from backstop_mcp.features.activity_writes.commands.update_email_command import UpdateEmailCommand
from backstop_mcp.features.activity_writes.commands.update_meeting_or_call_command import (
    UpdateMeetingOrCallCommand,
)
from backstop_mcp.features.activity_writes.commands.update_note_command import UpdateNoteCommand
from backstop_mcp.features.activity_writes.commands.update_task_command import UpdateTaskCommand
from backstop_mcp.features.activity_writes.responses import UpdatedActivityResponse
from backstop_mcp.features.activity_writes.update_activity_input import UpdateActivityInput


class UpdateActivityCommand:
    """One write: switch on `kind` and call the matching command.

    The activity id is already known. This command does not look up a party. Meeting and
    call share one command — they are the same Backstop collection.
    """

    def __init__(
        self,
        *,
        update_note_command: UpdateNoteCommand,
        update_meeting_or_call_command: UpdateMeetingOrCallCommand,
        update_task_command: UpdateTaskCommand,
        update_email_command: UpdateEmailCommand,
        update_document_command: UpdateDocumentCommand,
    ) -> None:
        self._update_note_command: UpdateNoteCommand = update_note_command
        self._update_meeting_or_call_command: UpdateMeetingOrCallCommand = (
            update_meeting_or_call_command
        )
        self._update_task_command: UpdateTaskCommand = update_task_command
        self._update_email_command: UpdateEmailCommand = update_email_command
        self._update_document_command: UpdateDocumentCommand = update_document_command

    async def run(self, *, activity: UpdateActivityInput) -> UpdatedActivityResponse:
        match activity.kind:
            case "note":
                return await self._update_note_command.run(activity=activity)
            case "meeting" | "call":
                return await self._update_meeting_or_call_command.run(activity=activity)
            case "task":
                return await self._update_task_command.run(activity=activity)
            case "email":
                return await self._update_email_command.run(activity=activity)
            case "document":
                return await self._update_document_command.run(activity=activity)
            case _:
                assert_never(activity.kind)
