"""Create, update, and delete CRM activities (notes, meetings, calls, tasks, emails).

This package currently publishes the write-side models only — wire attributes, internal
DTOs, tool responses, and the discriminated `log_activity` input. HTTP, payloads, queries, and
tools come later. `dependencies.py` is deferred until a query factory exists.
"""

from backstop_mcp.features.activity_writes.api_responses import (
    DocumentAttributes,
    EmailAttributes,
    MeetingOrCallAttributes,
    NoteAttributes,
    ResourceLinkAttributes,
    TaskAttributes,
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
    "LogActivityInput",
    "LogActivityResponse",
    "LoggedActivityResponse",
    "LoggedCallResponse",
    "LoggedEmailResponse",
    "LoggedMeetingResponse",
    "LoggedNoteResponse",
    "LoggedTaskResponse",
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
