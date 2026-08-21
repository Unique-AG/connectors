from datetime import date
from typing import ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict

from backstop_mcp.backstop_client import BackstopApiResource
from backstop_mcp.features.tasks.api_responses import TaskAttributes

__all__ = ["TaskDto", "TasksListingDto"]

type TaskStatus = Literal["open", "completed"]


class TaskDto(BaseModel):
    """One CRM task after the paired entity filter."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    title: str | None = None
    status: str | None = None
    description: str | None = None
    due_date: date | None = None
    completed_date: date | None = None
    is_open: bool

    @classmethod
    def from_resource(cls, resource: BackstopApiResource[TaskAttributes]) -> Self:
        attributes = resource.attributes
        completed = _is_completed(attributes)
        return cls(
            id=resource.id,
            title=attributes.title,
            status=attributes.status,
            description=attributes.description,
            due_date=attributes.due_date,
            completed_date=attributes.completed_date,
            is_open=not completed,
        )


def _is_completed(attributes: TaskAttributes) -> bool:
    if attributes.completed is True:
        return True
    if attributes.completed_date is not None:
        return True
    status = (attributes.status or "").strip().casefold()
    return status in {"completed", "complete", "done", "closed"}


class TasksListingDto(BaseModel):
    """One party's tasks, and whether the walk read all of them.

    `/tasks` takes no status filter, so the whole sub-collection is read and split here.
    `scan_truncated` is the walk's scan ceiling firing, which makes `rows` a prefix.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    rows: tuple[TaskDto, ...]
    scan_truncated: bool = False
