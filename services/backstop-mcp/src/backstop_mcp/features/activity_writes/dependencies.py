from functools import lru_cache

from fastmcp.dependencies import Depends

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client_for_current_caller
from backstop_mcp.features.activity_writes.commands import (
    LogActivityCommand,
    LogEmailCommand,
    LogMeetingOrCallCommand,
    LogNoteCommand,
    LogTaskCommand,
)
from backstop_mcp.features.system_users import SystemUsersService, get_system_users_service
from backstop_mcp.features.time_zones import TimeZonesService, get_time_zones_service


@lru_cache(maxsize=1)
def get_log_note_command_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
) -> LogNoteCommand:
    return LogNoteCommand(client=client)


@lru_cache(maxsize=1)
def get_log_meeting_or_call_command_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    time_zones_service: TimeZonesService = Depends(get_time_zones_service),
) -> LogMeetingOrCallCommand:
    return LogMeetingOrCallCommand(client=client, time_zones_service=time_zones_service)


@lru_cache(maxsize=1)
def get_log_task_command_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    system_users_service: SystemUsersService = Depends(get_system_users_service),
) -> LogTaskCommand:
    return LogTaskCommand(client=client, system_users_service=system_users_service)


@lru_cache(maxsize=1)
def get_log_email_command_factory(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
) -> LogEmailCommand:
    return LogEmailCommand(client=client)


@lru_cache(maxsize=1)
def get_log_activity_command_factory(
    log_note_command: LogNoteCommand = Depends(get_log_note_command_factory),
    log_meeting_or_call_command: LogMeetingOrCallCommand = Depends(
        get_log_meeting_or_call_command_factory
    ),
    log_task_command: LogTaskCommand = Depends(get_log_task_command_factory),
    log_email_command: LogEmailCommand = Depends(get_log_email_command_factory),
) -> LogActivityCommand:
    return LogActivityCommand(
        log_note_command=log_note_command,
        log_meeting_or_call_command=log_meeting_or_call_command,
        log_task_command=log_task_command,
        log_email_command=log_email_command,
    )
