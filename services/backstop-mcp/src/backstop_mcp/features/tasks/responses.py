"""Published task response models."""

from datetime import date
from typing import ClassVar, Literal, Self

from pydantic import ConfigDict, Field

from backstop_mcp.backstop_client import BackstopApiResource
from backstop_mcp.features.party_resolver import ResolvedPartyResponse
from backstop_mcp.features.tasks.api_responses import TaskAttributes
from backstop_mcp.models import OmitNoneModel

__all__ = ["PartyTasksResponse", "TaskRowResponse", "TasksResolvedResponse"]


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
    def from_resource(cls, resource: BackstopApiResource[TaskAttributes]) -> Self:
        attributes = resource.attributes
        return cls(
            id=resource.id,
            title=attributes.title,
            status=attributes.status,
            description=attributes.description,
            due_date=attributes.due_date,
            completed_date=attributes.completed_date,
            is_open=not _is_completed(attributes),
        )


def _is_completed(attributes: TaskAttributes) -> bool:
    if attributes.completed is True:
        return True
    if attributes.completed_date is not None:
        return True
    status = (attributes.status or "").strip().casefold()
    return status in {"completed", "complete", "done", "closed"}


class PartyTasksResponse(OmitNoneModel):
    """One party's tasks after the client-side status split, without a resolve wrap."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    tasks: tuple[TaskRowResponse, ...] = Field(
        description="Tasks matching `status`, after the client-side open/completed split."
    )
    total: int = Field(description="Every task fetched for this party, before the status filter.")
    open_count: int = Field(description="How many of those are open.")
    completed_count: int = Field(description="How many of those are completed.")
    scan_truncated: bool = Field(
        description=(
            "True when the walk stopped at the 5000-task scan ceiling, so these counts are "
            "floors rather than totals."
        )
    )


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
            "True when the walk stopped at the 5000-task scan ceiling, so these counts are "
            "floors rather than totals."
        )
    )
