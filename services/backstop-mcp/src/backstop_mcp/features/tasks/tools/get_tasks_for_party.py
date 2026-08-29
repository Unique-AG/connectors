"""`get_tasks_for_party`: open and completed follow-ups on one party."""

from datetime import date
from typing import Annotated, Literal, Self

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client_for_current_caller
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.party_resolver import (
    PartyAmbiguousResponse,
    ResolvedPartyResponse,
    resolve_party,
    unresolved_party_response,
)
from backstop_mcp.features.resolution import NotFoundResponse, Resolved
from backstop_mcp.features.tasks import MAX_TASK_SCAN_RECORDS, TaskDto, fetch_tasks_for_party
from backstop_mcp.models import OmitNoneModel, published_output_schema

type TaskFilter = Literal["open", "completed", "all"]


class TaskRowResponse(OmitNoneModel):
    """One CRM task on the resolved party."""

    id: str = Field(description="Backstop id of this task. Echo it; never invent one.")
    title: str | None = Field(default=None, description="Task title as Backstop publishes it.")
    status: str | None = Field(default=None, description="Backstop's status string, when present.")
    description: str | None = Field(default=None, description="Task body, when Backstop sends one.")
    due_date: date | None = Field(default=None, description="Due day, when set.")
    completed_date: date | None = Field(
        default=None, description="Day the task was completed, if any."
    )
    is_open: bool = Field(description="False when completed, complete, done, closed, or dated so.")

    @classmethod
    def from_dto(cls, row: TaskDto) -> Self:
        return cls.model_validate(row.model_dump())


class TasksResolvedResponse(OmitNoneModel):
    """A party's tasks after the paired entity filter and the client-side status split."""

    status: Literal["resolved"] = Field(
        default="resolved",
        description="Always 'resolved': the party was found and its tasks fetched.",
    )
    resolved: ResolvedPartyResponse = Field(
        description=(
            "The identity this call settled on. Echo `id` / `search_type` / `name` as "
            "`party_id` later — never invent them."
        )
    )
    tasks: tuple[TaskRowResponse, ...] = Field(
        description="Tasks matching `status`, after the client-side open/completed split."
    )
    total: int = Field(description="Every task fetched for this party, before the status filter.")
    open_count: int = Field(description="How many of those are open.")
    completed_count: int = Field(description="How many of those are completed.")
    scan_truncated: bool = Field(
        description=(
            f"True when the walk stopped at the {MAX_TASK_SCAN_RECORDS}-task scan ceiling, so "
            "these counts are floors rather than totals."
        )
    )


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
                "Which Backstop collection to resolve the party against. Organizations use "
                "OrganizationBean on the tasks filter; people use PersonBean. Echo a prior "
                "resolve's search_type — a contact id is not a people id."
            )
        ),
    ],
    party_id: Annotated[
        str | None,
        Field(
            description=(
                "Trusted Backstop Party ID from a prior resolve echo. Never invent or guess. "
                "Exactly one of `party_id` or `search` must be provided."
            )
        ),
    ] = None,
    search: Annotated[
        str | None,
        Field(
            description=(
                "Name or email to resolve when no trusted `party_id` is available. Exactly "
                "one of `party_id` or `search` must be provided."
            )
        ),
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
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
) -> GetTasksForPartyResponse:
    """List a party's CRM tasks.

    Both `filter[entityType]` and `filter[entityId]` are always sent. Either alone is
    silently ignored and returns every task in the instance. Organizations use
    `OrganizationBean` casing — `organizations` or `ORGANIZATION` fail closed. Status is
    not filterable on the wire; open vs completed is split here.
    """
    result = await resolve_party(
        ctx, client, search_type=search_type, party_id=party_id, search=search
    )
    if not isinstance(result, Resolved):
        return unresolved_party_response(result)
    party = result.value
    listing = await fetch_tasks_for_party(client, search_type=party.search_type, entity_id=party.id)
    selected = tuple(
        row for row in listing.rows if status == "all" or (row.is_open is (status == "open"))
    )
    return TasksResolvedResponse(
        resolved=ResolvedPartyResponse.from_party(party),
        tasks=tuple(TaskRowResponse.from_dto(row) for row in selected),
        total=len(listing.rows),
        open_count=sum(1 for row in listing.rows if row.is_open),
        completed_count=sum(1 for row in listing.rows if not row.is_open),
        scan_truncated=listing.scan_truncated,
    )
