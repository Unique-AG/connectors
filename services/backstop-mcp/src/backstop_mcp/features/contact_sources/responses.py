"""Published contact-source catalog response models."""

from typing import ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.features.contact_sources.internal_dto import ContactSourceDto

__all__ = ["ContactSourceResponse", "ListContactSourcesResponse"]


class ContactSourceResponse(BaseModel):
    """One contact source in the standard Backstop vocabulary returned to MCP callers."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str = Field(
        description=(
            "Backstop id of this contact source. Echo it as `contact_source_id` on "
            "`create_person`, `update_person`, `create_organization`, or "
            "`update_organization`. Never invent one."
        )
    )
    name: str = Field(description="Source name as this instance publishes it.")
    description: str | None = Field(
        default=None,
        description=(
            "Source description as Backstop publishes it. Often the same as `name`. "
            "Omitted when Backstop does not publish one."
        ),
    )

    @classmethod
    def from_source(cls, source: ContactSourceDto) -> Self:
        """Project an internal catalog source onto the published response shape."""
        return cls(id=source.id, name=source.name, description=source.description)


class ListContactSourcesResponse(BaseModel):
    """Contact sources from the standard Backstop contact-source vocabulary."""

    status: Literal["ok"] = Field(default="ok", description="Always 'ok'.")
    cache: Literal["ok", "stale"] = Field(
        description=(
            "'ok' when the catalog was fetched this call or is still fresh; 'stale' when a "
            "previous catalog is served because refresh failed."
        )
    )
    sources: list[ContactSourceResponse] = Field(
        description=(
            "Contact sources in catalog order. Each source's id is the stable identifier "
            "for `contact_source_id` on a person or organization write. This is a standard "
            "vocabulary, not a custom field."
        )
    )
