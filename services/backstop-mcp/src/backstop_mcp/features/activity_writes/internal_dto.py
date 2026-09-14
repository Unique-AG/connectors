from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict

from backstop_mcp.features.system_users import SystemUserDto

__all__ = ["AuthorDto"]


class AuthorDto(BaseModel):
    """The system user who authored an activity, once resolved from `/system-users`."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    user_name: str | None = None
    name: str | None = None

    @classmethod
    def from_system_user(cls, user: SystemUserDto) -> Self:
        return cls(id=user.id, user_name=user.user_name, name=user.name)
