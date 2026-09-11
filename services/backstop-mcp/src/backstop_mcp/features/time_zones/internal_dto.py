from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict

from backstop_mcp.backstop_client import BackstopApiResource
from backstop_mcp.features.time_zones.api_responses import TimeZoneAttributes

__all__ = ["TimeZoneDto"]


class TimeZoneDto(BaseModel):
    """A Backstop time zone from `GET /time-zones`. Dropped when `id` or `shortName` is missing."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    name: str | None = None
    short_name: str

    @classmethod
    def from_resource(cls, resource: BackstopApiResource[TimeZoneAttributes]) -> Self | None:
        """Map one time-zone resource. Returns None when `id` or `shortName` is missing."""
        short_name = resource.attributes.short_name
        if not resource.id or not short_name:
            return None
        return cls(id=resource.id, name=resource.attributes.name, short_name=short_name)
