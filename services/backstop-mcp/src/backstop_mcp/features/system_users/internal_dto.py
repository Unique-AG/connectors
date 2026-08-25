from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict

from backstop_mcp.backstop_client import BackstopApiResource
from backstop_mcp.features.system_users.api_responses import SystemUserAttributes

__all__ = ["SystemUserDto"]


class SystemUserDto(BaseModel):
    """One colleague from `GET /system-users`. Dropped when the resource has no id."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    name: str | None = None
    user_name: str | None = None
    email: str | None = None
    phone: str | None = None
    disabled: bool | None = None

    @classmethod
    def from_resource(cls, resource: BackstopApiResource[SystemUserAttributes]) -> Self | None:
        if not resource.id:
            return None
        attributes = resource.attributes
        return cls(
            id=resource.id,
            name=attributes.name,
            user_name=attributes.user_name,
            email=attributes.email,
            phone=attributes.phone,
            disabled=attributes.disabled,
        )
