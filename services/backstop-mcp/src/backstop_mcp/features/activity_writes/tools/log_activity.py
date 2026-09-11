"""`log_activity`: resolve the party, then create a note, meeting, call, or task."""

import logging
from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.features.activity_writes import (
    LOG_ACTIVITY_INPUT_DESCRIPTION,
    AuthorDto,
    LogActivityCommand,
    LogActivityInput,
    LogActivityResponse,
    get_log_activity_command_factory,
)
from backstop_mcp.features.party_resolver import (
    ResolvePartyQuery,
    get_resolve_party_query_factory,
    unresolved_party_response,
)
from backstop_mcp.features.resolution import Resolved, elicit_if_ambiguous
from backstop_mcp.features.system_users import SystemUserDto, get_current_caller_system_user
from backstop_mcp.models import published_output_schema

logger = logging.getLogger(__name__)


@tool(
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(LogActivityResponse),
)
async def log_activity(
    ctx: Context,
    activity: Annotated[LogActivityInput, Field(description=LOG_ACTIVITY_INPUT_DESCRIPTION)],
    resolve_party_query: ResolvePartyQuery = Depends(get_resolve_party_query_factory),
    log_activity_command: LogActivityCommand = Depends(get_log_activity_command_factory),
    caller: SystemUserDto = Depends(get_current_caller_system_user),
) -> LogActivityResponse:
    """Log a CRM note, meeting, call, or task.

    Required on `activity`: `kind`, `search_type`, and exactly one of `party_id` or `search`.
    A `party_id` without `search_type` is rejected. A meeting or call also needs
    `time_zone`, `start` and `stop`; a task needs `assigned_user` and `due_date`. Author is
    the authenticated caller, not a parameter. Activity-tag ids must come from
    `list_activity_tags`; tags are never created automatically.

    There is no email kind here. Backstop will not create an email record without the
    message file, so use `attach_file(kind="email")` with the `.msg`/`.eml` blob. Any other
    file is `attach_file(kind="document")`.

    Call like: {"activity": {"kind": "note", "search_type": "organizations",
    "party_id": "<id from prior resolve echo>", "title": "Follow up"}}
    """
    result = await resolve_party_query.run(
        search_type=activity.search_type,
        party_id=activity.party_id,
        search=activity.search,
    )
    result = await elicit_if_ambiguous(ctx, result)
    if not isinstance(result, Resolved):
        return unresolved_party_response(result)
    party = result.value
    # Every `log_activity` variant carries the secondary-party pair, so this reads straight
    # off the union rather than through a `getattr` the type checker cannot see.
    secondary_party_id = activity.secondary_party_id
    logger.info(
        "activity_writes.log.start",
        extra={
            "kind": activity.kind,
            "search_type": party.search_type,
            "party_id": party.id,
        },
    )
    return await log_activity_command.run(
        activity=activity,
        party_id=party.id,
        author=AuthorDto(id=caller.id, user_name=caller.user_name, name=caller.name),
        secondary_party_id=secondary_party_id,
    )
