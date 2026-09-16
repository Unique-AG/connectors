from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict

from backstop_mcp.backstop_client import BackstopApiResource
from backstop_mcp.features.contact_sources.api_responses import ContactSourceAttributes

__all__ = ["ContactSourceDto"]


class ContactSourceDto(BaseModel):
    """A CRM contact source from Backstop `contact-sources` attributes."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    name: str
    description: str | None = None

    @classmethod
    def from_resource(cls, resource: BackstopApiResource[ContactSourceAttributes]) -> Self | None:
        """Map one contact-source resource. Returns None when `name` is missing."""
        name = resource.attributes.name
        if not name:
            return None
        return cls(
            id=resource.id,
            name=name,
            description=resource.attributes.description,
        )
