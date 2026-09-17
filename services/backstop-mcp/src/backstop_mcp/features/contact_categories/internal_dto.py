from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict

from backstop_mcp.backstop_client import BackstopApiResource
from backstop_mcp.features.contact_categories.api_responses import ContactCategoryAttributes

__all__ = ["ContactCategoryDto"]


class ContactCategoryDto(BaseModel):
    """A CRM contact category from Backstop `contact-categories` attributes."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    name: str

    @classmethod
    def from_resource(cls, resource: BackstopApiResource[ContactCategoryAttributes]) -> Self | None:
        """Map one contact-category resource. Returns None when `name` is missing."""
        name = resource.attributes.name
        if not name:
            return None
        return cls(id=resource.id, name=name)
