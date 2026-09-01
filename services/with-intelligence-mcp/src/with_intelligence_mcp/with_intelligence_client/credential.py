"""What a request needs to authenticate, and who supplies it.

Both live in the transport because that is what sends them. `features/vendor_session` owns the
other half — obtaining and refreshing a session — and depends on these types, not the reverse.
"""

from typing import ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, SecretStr


class VendorCredential(BaseModel):
    """A username and password `POST /v3/auth/sign-in` accepts.

    `password` is a `SecretStr` so an accidental log line prints `**********`.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    username: str
    password: SecretStr


class CallerSession(Protocol):
    """Resolves "whose access token" for the in-flight request.

    A Protocol, not the concrete class: the implementation needs configuration, and later the
    database and the calling MCP subject, none of which the transport should know about. It is
    also what makes the dev-only single-account implementation and the per-user one
    interchangeable.
    """

    async def access_token(self) -> str: ...

    async def renewed_access_token(self) -> str:
        """A fresh token after a 401. Refreshes, or signs in again if the refresh is spent."""
        ...

    def subject(self) -> str:
        """Who the token belongs to. Keys the per-caller concurrency gate."""
        ...
