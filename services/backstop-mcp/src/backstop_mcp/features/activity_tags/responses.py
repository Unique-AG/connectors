"""Published activity-tag catalog response models."""

from typing import ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.features.activity_tags.internal_dto import ActivityTagDto

__all__ = ["ActivityTagResponse", "ListActivityTagsResponse"]


class ActivityTagResponse(BaseModel):
    """One activity tag in the standard Backstop catalog returned to MCP callers."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str = Field(
        description=(
            "Backstop id of this activity tag. Use it as the stable identifier when filtering "
            "activities by tag; echo it, never invent one."
        )
    )
    name: str = Field(description="Tag name as Backstop publishes it.")
    quantity_tagged: int | None = Field(
        default=None,
        description=(
            "Number of activities currently carrying this tag. Use it to tell a live tag from "
            "an unused one. Null when Backstop does not publish a count."
        ),
    )
    viewable: bool | None = Field(
        default=None,
        description=(
            "Whether this tag is shown in the Backstop UI. Some tags are hidden. Null when "
            "Backstop does not publish the flag."
        ),
    )

    @classmethod
    def from_tag(cls, tag: ActivityTagDto) -> Self:
        """Project an internal catalog tag onto the published response shape."""
        return cls(
            id=tag.id,
            name=tag.name,
            quantity_tagged=tag.quantity_tagged,
            viewable=tag.viewable,
        )


class ListActivityTagsResponse(BaseModel):
    """Activity tags from the standard Backstop activity-tag catalog."""

    status: Literal["ok"] = Field(default="ok", description="Always 'ok'.")
    cache: Literal["ok", "stale"] = Field(
        description=(
            "'ok' when the catalog was fetched this call or is still fresh; 'stale' when a "
            "previous catalog is served because refresh failed."
        )
    )
    tags: list[ActivityTagResponse] = Field(
        description=(
            "Activity tags in catalog order. Each tag's id is the stable identifier for "
            "filtering activities by tag. quantity_tagged is how many activities currently "
            "carry the tag; viewable is whether the tag is shown in the Backstop UI."
        )
    )
