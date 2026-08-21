from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict

from backstop_mcp.backstop_client import BackstopApiResource
from backstop_mcp.features.activity_tags.api_responses import ActivityTagAttributes

__all__ = ["ActivityTagDto"]


class ActivityTagDto(BaseModel):
    """A CRM activity tag from Backstop `activity-tags` attributes."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    name: str
    quantity_tagged: int | None = None
    viewable: bool | None = None

    @classmethod
    def from_resource(cls, resource: BackstopApiResource[ActivityTagAttributes]) -> Self | None:
        """Map one activity-tag resource. Returns None when `name` is missing."""
        name = resource.attributes.name
        if not name:
            return None
        return cls(
            id=resource.id,
            name=name,
            quantity_tagged=resource.attributes.quantity_tagged,
            viewable=resource.attributes.viewable,
        )
