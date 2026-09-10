"""`log_activity`: resolve the party, then create a note, meeting, call, task, or email stub."""

import logging

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations

from backstop_mcp.features.activity_writes import (
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
    activity: LogActivityInput,
    resolve_party_query: ResolvePartyQuery = Depends(get_resolve_party_query_factory),
    log_activity_command: LogActivityCommand = Depends(get_log_activity_command_factory),
    caller: SystemUserDto = Depends(get_current_caller_system_user),
) -> LogActivityResponse:
    """Log a CRM note, meeting, call, task, or email metadata stub.

    Required on `activity`: `kind`, `search_type`, and exactly one of `party_id` or `search`.
    A `party_id` without `search_type` is rejected. Author is the authenticated caller, not
    a parameter. For the message body of an email or a file on a note, use `attach_file`
    after this create — `kind=email` writes metadata only.

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
    secondary_party_id = getattr(activity, "secondary_party_id", None)
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
