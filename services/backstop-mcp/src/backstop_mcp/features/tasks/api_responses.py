from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.dates import LenientDate
from backstop_mcp.lenient import LenientBool

__all__ = ["TaskAttributes"]


class TaskAttributes(BaseModel):
    """Wire shape for `tasks` attributes (subset we publish)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    title: str | None = None
    status: str | None = None
    description: str | None = None
    due_date: LenientDate = Field(default=None, alias="dueDate")
    completed_date: LenientDate = Field(default=None, alias="completedDate")
    completed: LenientBool = None
