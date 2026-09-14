"""Create, update, and delete CRM activities (notes, meetings, calls, tasks, emails, documents).

`LogActivityCommand`, `AttachFileCommand`, and `UpdateActivityCommand` switch on `kind`.
Meeting and call share one command (same Backstop collection). `DeleteActivityCommand` is
one path map. Commands are cached; author is a per-request argument to create `run`.

`log_activity` covers note, meeting, call and task. Email creates live only on
`attach_file`: `POST /emails` requires the message blob, so there is no metadata-only
email record to write. `update_activity` and `delete_activity` still cover all six types,
including the emails and documents `attach_file` creates.
"""

from backstop_mcp.features.activity_writes.attach_file_input import (
    ATTACH_FILE_INPUT_DESCRIPTION,
    AttachFileInput,
)
from backstop_mcp.features.activity_writes.attach_file_max_bytes import (
    ATTACH_FILE_MAX_BYTES,
    attach_file_max_bytes_message,
)
from backstop_mcp.features.activity_writes.commands import (
    AttachFileCommand,
    DeleteActivityCommand,
    LogActivityCommand,
    UpdateActivityCommand,
    encode_file_data,
    extract_collection,
)
from backstop_mcp.features.activity_writes.delete_activity_input import (
    DELETE_ACTIVITY_INPUT_DESCRIPTION,
    DeleteActivityInput,
)
from backstop_mcp.features.activity_writes.dependencies import (
    get_attach_document_command_factory,
    get_attach_email_command_factory,
    get_attach_file_command_factory,
    get_delete_activity_command_factory,
    get_log_activity_command_factory,
    get_log_meeting_or_call_command_factory,
    get_log_note_command_factory,
    get_log_task_command_factory,
    get_update_activity_command_factory,
    get_update_document_command_factory,
    get_update_email_command_factory,
    get_update_meeting_or_call_command_factory,
    get_update_note_command_factory,
    get_update_task_command_factory,
)
from backstop_mcp.features.activity_writes.internal_dto import AuthorDto
from backstop_mcp.features.activity_writes.log_activity_input import (
    LOG_ACTIVITY_INPUT_DESCRIPTION,
    LogActivityInput,
)
from backstop_mcp.features.activity_writes.responses import (
    AttachedFileResponse,
    AttachFileResponse,
    DeletedActivityResponse,
    LogActivityResponse,
    LoggedActivityResponse,
    UpdatedActivityResponse,
)
from backstop_mcp.features.activity_writes.update_activity_input import (
    UPDATE_ACTIVITY_INPUT_DESCRIPTION,
    UpdateActivityInput,
)

__all__ = [
    "ATTACH_FILE_INPUT_DESCRIPTION",
    "ATTACH_FILE_MAX_BYTES",
    "DELETE_ACTIVITY_INPUT_DESCRIPTION",
    "LOG_ACTIVITY_INPUT_DESCRIPTION",
    "UPDATE_ACTIVITY_INPUT_DESCRIPTION",
    "AttachFileCommand",
    "AttachFileInput",
    "AttachFileResponse",
    "AttachedFileResponse",
    "AuthorDto",
    "DeleteActivityCommand",
    "DeleteActivityInput",
    "DeletedActivityResponse",
    "LogActivityCommand",
    "LogActivityInput",
    "LogActivityResponse",
    "LoggedActivityResponse",
    "UpdateActivityCommand",
    "UpdateActivityInput",
    "UpdatedActivityResponse",
    "attach_file_max_bytes_message",
    "encode_file_data",
    "extract_collection",
    "get_attach_document_command_factory",
    "get_attach_email_command_factory",
    "get_attach_file_command_factory",
    "get_delete_activity_command_factory",
    "get_log_activity_command_factory",
    "get_log_meeting_or_call_command_factory",
    "get_log_note_command_factory",
    "get_log_task_command_factory",
    "get_update_activity_command_factory",
    "get_update_document_command_factory",
    "get_update_email_command_factory",
    "get_update_meeting_or_call_command_factory",
    "get_update_note_command_factory",
    "get_update_task_command_factory",
]
