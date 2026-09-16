"""WI authentication interfaces."""

from typing import ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, SecretStr


class WiCredential(BaseModel):
    """WI username and password."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    username: str
    password: SecretStr


class CallerSessionProvider(Protocol):
    """Provides authentication for one caller."""

    async def get_access_token(self) -> str: ...

    async def refresh_access_token(self) -> str:
        """A fresh token after a 401. Refreshes, or signs in again if the refresh is spent."""
        ...

    def subject(self) -> str:
        """Who the token belongs to. Keys the per-caller concurrency gate."""
        ...
