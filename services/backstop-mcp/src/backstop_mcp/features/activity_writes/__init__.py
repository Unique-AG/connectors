"""Create, update, and delete CRM activities (notes, meetings, calls, tasks, emails).

`LogActivityCommand` switches on `kind`. Meeting and call share `LogMeetingOrCallCommand`
(same Backstop collection). Tools and `dependencies.py` come later — no cached factory yet.
"""

from backstop_mcp.features.activity_writes.api_responses import (
    DocumentAttributes,
    EmailAttributes,
    MeetingOrCallAttributes,
    NoteAttributes,
    ResourceLinkAttributes,
    TaskAttributes,
)
from backstop_mcp.features.activity_writes.commands import (
    LogActivityCommand,
    LogEmailCommand,
    LogMeetingOrCallCommand,
    LogNoteCommand,
    LogTaskCommand,
)
from backstop_mcp.features.activity_writes.internal_dto import (
    AuthorDto,
    ResolvedTargetDto,
    ResolvedTimeZoneDto,
)
from backstop_mcp.features.activity_writes.log_activity_input import (
    CallActivityInput,
    EmailActivityInput,
    LogActivityInput,
    MeetingActivityInput,
    NoteActivityInput,
    TaskActivityInput,
)
from backstop_mcp.features.activity_writes.responses import (
    AttachedFileResponse,
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
    "AttachedFileResponse",
    "AuthorDto",
    "CallActivityInput",
    "DeletedActivityResponse",
    "DocumentAttributes",
    "EmailActivityInput",
    "EmailAttributes",
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
]
