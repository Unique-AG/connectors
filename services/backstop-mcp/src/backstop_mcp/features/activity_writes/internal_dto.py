from typing import ClassVar

from pydantic import BaseModel, ConfigDict

__all__ = ["AuthorDto"]


class AuthorDto(BaseModel):
    """The system user who authored an activity, once resolved from `/system-users`."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str
    user_name: str | None = None
    name: str | None = None
