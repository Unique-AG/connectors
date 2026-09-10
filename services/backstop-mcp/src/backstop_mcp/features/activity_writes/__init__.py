"""Create, update, and delete CRM activities (notes, meetings, calls, tasks, emails, documents).

`LogActivityCommand` and `AttachFileCommand` switch on `kind`. Meeting and call share
`LogMeetingOrCallCommand` (same Backstop collection). Commands are cached; author is a
per-request argument to `run`.
"""

from backstop_mcp.features.activity_writes.api_responses import (
    DocumentAttributes,
    EmailAttributes,
    MeetingOrCallAttributes,
    NoteAttributes,
    ResourceLinkAttributes,
    TaskAttributes,
)
from backstop_mcp.features.activity_writes.attach_file_input import (
    ATTACH_FILE_INPUT_DESCRIPTION,
    AttachFileInput,
    DocumentFileInput,
    EmailFileInput,
)
from backstop_mcp.features.activity_writes.commands import (
    ATTACH_FILE_MAX_BYTES,
    AttachDocumentCommand,
    AttachEmailCommand,
    AttachFileCommand,
    LogActivityCommand,
    LogEmailCommand,
    LogMeetingOrCallCommand,
    LogNoteCommand,
    LogTaskCommand,
    encode_file_data,
)
from backstop_mcp.features.activity_writes.dependencies import (
    get_attach_document_command_factory,
    get_attach_email_command_factory,
    get_attach_file_command_factory,
    get_log_activity_command_factory,
    get_log_email_command_factory,
    get_log_meeting_or_call_command_factory,
    get_log_note_command_factory,
    get_log_task_command_factory,
)
from backstop_mcp.features.activity_writes.internal_dto import (
    AuthorDto,
    ResolvedTargetDto,
    ResolvedTimeZoneDto,
)
from backstop_mcp.features.activity_writes.log_activity_input import (
    LOG_ACTIVITY_INPUT_DESCRIPTION,
    CallActivityInput,
    EmailActivityInput,
    LogActivityInput,
    MeetingActivityInput,
    NoteActivityInput,
    TaskActivityInput,
)
from backstop_mcp.features.activity_writes.responses import (
    AttachedFileResponse,
    AttachFileResponse,
    DeletedActivityResponse,
    LogActivityResponse,
    LoggedActivityResponse,
    LoggedCallResponse,
    LoggedEmailResponse,
    LoggedMeetingResponse,
    LoggedNoteResponse,
    LoggedTaskResponse,
    UpdatedActivityResponse,
)

__all__ = [
    "ATTACH_FILE_INPUT_DESCRIPTION",
    "ATTACH_FILE_MAX_BYTES",
    "AttachDocumentCommand",
    "AttachEmailCommand",
    "AttachFileCommand",
    "AttachFileInput",
    "AttachFileResponse",
    "AttachedFileResponse",
    "AuthorDto",
    "CallActivityInput",
    "DeletedActivityResponse",
    "DocumentAttributes",
    "DocumentFileInput",
    "EmailActivityInput",
    "EmailAttributes",
    "EmailFileInput",
    "LOG_ACTIVITY_INPUT_DESCRIPTION",
    "LogActivityCommand",
    "LogActivityInput",
    "LogActivityResponse",
    "LogEmailCommand",
    "LoggedActivityResponse",
    "LoggedCallResponse",
    "LoggedEmailResponse",
    "LoggedMeetingResponse",
    "LoggedNoteResponse",
    "LoggedTaskResponse",
    "LogMeetingOrCallCommand",
    "LogNoteCommand",
    "LogTaskCommand",
    "MeetingActivityInput",
    "MeetingOrCallAttributes",
    "NoteActivityInput",
    "NoteAttributes",
    "ResolvedTargetDto",
    "ResolvedTimeZoneDto",
    "ResourceLinkAttributes",
    "TaskActivityInput",
    "TaskAttributes",
    "UpdatedActivityResponse",
    "encode_file_data",
    "get_attach_document_command_factory",
    "get_attach_email_command_factory",
    "get_attach_file_command_factory",
    "get_log_activity_command_factory",
    "get_log_email_command_factory",
    "get_log_meeting_or_call_command_factory",
    "get_log_note_command_factory",
    "get_log_task_command_factory",
]
