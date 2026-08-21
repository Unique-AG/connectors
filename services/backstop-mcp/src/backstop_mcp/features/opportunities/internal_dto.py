from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict

from backstop_mcp.backstop_client import BackstopApiResource
from backstop_mcp.features.opportunities.api_responses import OpportunityStageAttributes

__all__ = ["OpportunityStageDto"]


class OpportunityStageDto(BaseModel):
    """One row of the instance's opportunity-stage vocabulary."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    name: str
    closed: bool = False
    sort_order: int | None = None

    @classmethod
    def from_resource(
        cls, resource: BackstopApiResource[OpportunityStageAttributes]
    ) -> Self | None:
        """Map one `opportunity-stages` resource onto the vocabulary shape.

        Returns None when `name` is missing — naming a stage is the whole point of this
        vocabulary, so an unnamed row would only masquerade as a resolution.
        """
        name = resource.attributes.name
        if not name:
            return None
        return cls(
            id=resource.id,
            name=name,
            closed=bool(resource.attributes.closed),
            sort_order=resource.attributes.sort_order,
        )
