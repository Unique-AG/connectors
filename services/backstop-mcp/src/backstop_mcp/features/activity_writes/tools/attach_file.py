"""`attach_file`: resolve the party, then upload a document or import an email file."""

import logging
from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.features.activity_writes import (
    ATTACH_FILE_INPUT_DESCRIPTION,
    AttachFileCommand,
    AttachFileInput,
    AttachFileResponse,
    AuthorDto,
    DocumentFileInput,
    get_attach_file_command_factory,
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
    output_schema=published_output_schema(AttachFileResponse),
)
async def attach_file(
    ctx: Context,
    activity: Annotated[AttachFileInput, Field(description=ATTACH_FILE_INPUT_DESCRIPTION)],
    resolve_party_query: ResolvePartyQuery = Depends(get_resolve_party_query_factory),
    attach_file_command: AttachFileCommand = Depends(get_attach_file_command_factory),
    caller: SystemUserDto = Depends(get_current_caller_system_user),
) -> AttachFileResponse:
    """Attach a document or import a real `.msg`/`.eml` email against a party.

    Required on `activity`: `kind`, `search_type`, `file_name`, `content` (standard base64
    of the raw file), and exactly one of `party_id` or `search`. A `party_id` without
    `search_type` is rejected. Do not generate `content` yourself — always use a
    file-encoding tool for the base64 when one is available.
    Author is the authenticated caller, not a parameter.

    Use `log_activity` for a note, meeting, call or task — anything with no file. Use this
    tool for every file, and for every email: Backstop will not create an email record
    without the message blob, so `log_activity` has no email kind.

    Files are rejected before any Backstop request once they exceed the cap published in
    the `content` description. The practical ceiling for a call an LLM composes is far
    smaller, because the base64 has to pass through the model's context first.

    Call like: {"activity": {"kind": "document", "search_type": "organizations",
    "party_id": "<id from prior resolve echo>", "file_name": "memo.pdf",
    "content": "<standard base64 from a file-encoding tool>"}}
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
    secondary_party_id = (
        activity.secondary_party_id if isinstance(activity, DocumentFileInput) else None
    )
    logger.info(
        "activity_writes.attach.start",
        extra={
            "kind": activity.kind,
            "search_type": party.search_type,
            "party_id": party.id,
        },
    )
    return await attach_file_command.run(
        activity=activity,
        party_id=party.id,
        author=AuthorDto(id=caller.id, user_name=caller.user_name, name=caller.name),
        secondary_party_id=secondary_party_id,
    )
