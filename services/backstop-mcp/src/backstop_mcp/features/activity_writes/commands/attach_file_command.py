"""Dispatch a validated `attach_file` input to the command for that `kind`."""

from typing import assert_never

from fastmcp.exceptions import ToolError

from backstop_mcp.backstop_client import BackstopApiError
from backstop_mcp.features.activity_writes.attach_file_input import AttachFileInput
from backstop_mcp.features.activity_writes.commands._attachment_utils import (
    backstop_payload_too_large_message,
)
from backstop_mcp.features.activity_writes.commands._write_errors import (
    reraise_activity_write_error,
)
from backstop_mcp.features.activity_writes.commands.attach_document_command import (
    AttachDocumentCommand,
)
from backstop_mcp.features.activity_writes.commands.attach_email_command import AttachEmailCommand
from backstop_mcp.features.activity_writes.internal_dto import AuthorDto
from backstop_mcp.features.activity_writes.responses import AttachedFileResponse


class AttachFileCommand:
    """One write: switch on `kind` and call the matching command.

    `party_id` is already resolved. Size-cap rejection happens in the child before POST;
    a Backstop `413` is remapped so it is not the same message as our local cap.
    """

    def __init__(
        self,
        *,
        attach_document_command: AttachDocumentCommand,
        attach_email_command: AttachEmailCommand,
    ) -> None:
        self._attach_document_command: AttachDocumentCommand = attach_document_command
        self._attach_email_command: AttachEmailCommand = attach_email_command

    async def run(
        self,
        *,
        activity: AttachFileInput,
        party_id: str,
        author: AuthorDto,
        secondary_party_id: str | None = None,
    ) -> AttachedFileResponse:
        try:
            match activity.kind:
                case "document":
                    return await self._attach_document_command.run(
                        activity=activity,
                        party_id=party_id,
                        author=author,
                        secondary_party_id=secondary_party_id,
                    )
                case "email":
                    return await self._attach_email_command.run(
                        activity=activity,
                        party_id=party_id,
                        author=author,
                    )
                case _:
                    assert_never(activity.kind)
        except BackstopApiError as exc:
            if exc.status_code == 413:
                raise ToolError(backstop_payload_too_large_message()) from exc
            reraise_activity_write_error(exc)
