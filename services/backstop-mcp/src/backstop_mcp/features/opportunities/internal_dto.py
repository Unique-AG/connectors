from typing import ClassVar

from pydantic import BaseModel, ConfigDict

__all__ = ["OpportunityStageDto"]


class OpportunityStageDto(BaseModel):
    """One row of the instance's opportunity-stage vocabulary."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    name: str
    closed: bool = False
    sort_order: int | None = None
