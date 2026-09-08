"""`get_tasks_for_party`: open and completed follow-ups on one party."""

import logging
from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.party_resolver import (
    PARTY_ID_REQUIRES_SEARCH_TYPE_DESCRIPTION,
    REQUIRED_SEARCH_TYPE_DESCRIPTION,
    SEARCH_REQUIRES_SEARCH_TYPE_DESCRIPTION,
    PartyAmbiguousResponse,
    ResolvedPartyResponse,
    ResolvePartyQuery,
    get_resolve_party_query_factory,
    unresolved_party_response,
)
from backstop_mcp.features.resolution import NotFoundResponse, Resolved, elicit_if_ambiguous
from backstop_mcp.features.tasks import GetTasksForPartyQuery, TaskFilter, TasksResolvedResponse
from backstop_mcp.features.tasks.dependencies import get_tasks_for_party_query_factory
from backstop_mcp.models import published_output_schema

logger = logging.getLogger(__name__)

type GetTasksForPartyResponse = PartyAmbiguousResponse | NotFoundResponse | TasksResolvedResponse


@tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    output_schema=published_output_schema(GetTasksForPartyResponse),
)
async def get_tasks_for_party(
    ctx: Context,
    search_type: Annotated[
        SearchType,
        Field(
            description=(
                REQUIRED_SEARCH_TYPE_DESCRIPTION
                + " Organizations use OrganizationBean on the tasks filter; people use PersonBean."
            )
        ),
    ],
    party_id: Annotated[
        str | None,
        Field(description=PARTY_ID_REQUIRES_SEARCH_TYPE_DESCRIPTION),
    ] = None,
    search: Annotated[
        str | None,
        Field(description=SEARCH_REQUIRES_SEARCH_TYPE_DESCRIPTION),
    ] = None,
    status: Annotated[
        TaskFilter,
        Field(
            description=(
                "Client-side split: open, completed, or all. filter[status] is not accepted "
                "on /tasks."
            )
        ),
    ] = "all",
    resolve_party_query: ResolvePartyQuery = Depends(get_resolve_party_query_factory),
    get_tasks_for_party_query: GetTasksForPartyQuery = Depends(get_tasks_for_party_query_factory),
) -> GetTasksForPartyResponse:
    """List a party's CRM tasks.

    Required: `search_type` plus exactly one of `party_id` or `search`. A `party_id` without
    `search_type` is rejected.

    Call like: {"search_type": "organizations",
    "party_id": "<id from prior resolve echo>", "status": "open"}

    Both `filter[entityType]` and `filter[entityId]` are always sent. Either alone is
    silently ignored and returns every task in the instance. Organizations use
    `OrganizationBean` casing — `organizations` or `ORGANIZATION` fail closed. Status is
    not filterable on the wire; open vs completed is split here.
    """
    result = await resolve_party_query.run(
        search_type=search_type, party_id=party_id, search=search
    )
    result = await elicit_if_ambiguous(ctx, result)
    if not isinstance(result, Resolved):
        return unresolved_party_response(result)
    party = result.value
    logger.info(
        "tasks.get.start",
        extra={"segment": party.search_type, "entity_id": party.id, "status": status},
    )
    fetched = await get_tasks_for_party_query.run(
        search_type=party.search_type,
        entity_id=party.id,
        status=status,
    )
    return TasksResolvedResponse(
        resolved=ResolvedPartyResponse.from_party(party),
        tasks=fetched.tasks,
        total=fetched.total,
        open_count=fetched.open_count,
        completed_count=fetched.completed_count,
        scan_truncated=fetched.scan_truncated,
    )
