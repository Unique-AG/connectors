"""Published contact-category catalog response models."""

from typing import ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.features.contact_categories.internal_dto import ContactCategoryDto

__all__ = ["ContactCategoryResponse", "ListContactCategoriesResponse"]


class ContactCategoryResponse(BaseModel):
    """One contact category in the standard Backstop vocabulary returned to MCP callers."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str = Field(
        description=(
            "Backstop id of this contact category. Echo it as `category_ids`, "
            "`add_category_ids`, or `replace_category_ids` on `create_person`, "
            "`update_person`, `create_organization`, or `update_organization`. "
            "Never invent one."
        )
    )
    name: str = Field(description="Category name as this instance publishes it.")

    @classmethod
    def from_category(cls, category: ContactCategoryDto) -> Self:
        """Project an internal catalog category onto the published response shape."""
        return cls(id=category.id, name=category.name)


class ListContactCategoriesResponse(BaseModel):
    """Contact categories from the standard Backstop contact-category vocabulary."""

    status: Literal["ok"] = Field(default="ok", description="Always 'ok'.")
    cache: Literal["ok", "stale"] = Field(
        description=(
            "'ok' when the catalog was fetched this call or is still fresh; 'stale' when a "
            "previous catalog is served because refresh failed."
        )
    )
    categories: list[ContactCategoryResponse] = Field(
        description=(
            "Contact categories in catalog order. Each category's id is the stable "
            "identifier for `category_ids` / `add_category_ids` / `replace_category_ids` "
            "on a person or organization write. This is a standard vocabulary, not a "
            "custom field."
        )
    )
