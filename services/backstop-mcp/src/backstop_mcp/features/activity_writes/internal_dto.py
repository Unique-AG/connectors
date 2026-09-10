from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from backstop_mcp.features.entity_types import SearchType

__all__ = ["AuthorDto", "ResolvedTargetDto", "ResolvedTimeZoneDto"]


class AuthorDto(BaseModel):
    """The system user who authored an activity, once resolved from `/system-users`."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    user_name: str | None = None
    name: str | None = None


class ResolvedTargetDto(BaseModel):
    """A party the activity attaches to, after resolve, with Backstop's Bean casing."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    search_type: SearchType
    resource_type_bean: str
    name: str | None = None


class ResolvedTimeZoneDto(BaseModel):
    """A `/time-zones` row after matching `shortName` (or id, or a unique display name)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    short_name: str
    name: str | None = None
