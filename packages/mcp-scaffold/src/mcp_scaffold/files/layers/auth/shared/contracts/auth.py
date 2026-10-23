"""What the sign-in's layers agree on. `persistence` implements `AuthStore`, `upstream` signs its
requests with the `UpstreamCredentials` a `CredentialsProvider` returns, and `mcp/auth` connects
the two without either knowing the other.

Every time is seconds since the epoch, and scopes are one space-separated string, so a store can
keep them in plain columns.
"""

from collections.abc import Awaitable
from collections.abc import Callable
from typing import ClassVar
from typing import Protocol
from typing import runtime_checkable

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import SecretStr


class UpstreamCredentials(BaseModel):
    """What the upstream needs to act as one user. Add what else it needs, such as an account id:
    the store keeps it with the rest, and the upstream signs with it."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    username: str
    password: SecretStr


# Returns the credentials of whoever the current call acts for.
type CredentialsProvider = Callable[[], Awaitable[UpstreamCredentials]]


class RegisteredClient(BaseModel):
    """A client that registered itself, its registration kept as the JSON it sent."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, from_attributes=True)

    client_id: str
    registration: str


class PendingSignIn(BaseModel):
    """An authorization request waiting for its user to sign in on the login page."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, from_attributes=True)

    request_id: str
    client_id: str
    scopes: str
    code_challenge: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    state: str | None
    resource: str | None
    expires_at: float


class IssuedCode(BaseModel):
    """A one-time code the client exchanges for its first tokens, issued to `subject`."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, from_attributes=True)

    code: str
    client_id: str
    scopes: str
    code_challenge: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    resource: str | None
    subject: str
    expires_at: float


class IssuedToken(BaseModel):
    """An access and refresh token pair, kept as hashes. Refreshing revokes the pair and issues
    the next one in the same family, so a reused refresh token can revoke them all."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, from_attributes=True)

    id: str
    family_id: str
    client_id: str
    scopes: str
    resource: str | None
    subject: str
    access_token_expires_at: float
    refresh_token_expires_at: float
    revoked_at: float | None = None


@runtime_checkable
class AuthStore(Protocol):
    """Everything the sign-in keeps. Each method is one transaction."""

    async def save_client(self, *, client_id: str, registration: str, now: float) -> None: ...

    async def get_client(self, client_id: str) -> RegisteredClient | None: ...

    async def save_pending_sign_in(self, pending: PendingSignIn) -> None: ...

    async def get_pending_sign_in(self, request_id: str, *, now: float) -> PendingSignIn | None:
        """None once it expired or a sign-in completed it."""
        ...

    async def complete_sign_in(
        self, request_id: str, *, code: str, subject: str, code_expires_at: float, now: float
    ) -> PendingSignIn | None:
        """Turns the pending sign-in into an authorization code for `subject`. None when it
        expired or another sign-in completed it first."""
        ...

    async def get_authorization_code(
        self, code: str, *, client_id: str, now: float
    ) -> IssuedCode | None: ...

    async def take_authorization_code(self, code: str, *, client_id: str, now: float) -> bool:
        """Deletes the code, so it is exchanged once. False when it is gone or expired."""
        ...

    async def save_tokens(
        self, token: IssuedToken, *, access_hash: str, refresh_hash: str
    ) -> None: ...

    async def get_token_by_access_hash(self, access_hash: str) -> IssuedToken | None: ...

    async def get_token_by_refresh_hash(self, refresh_hash: str) -> IssuedToken | None: ...

    async def revoke_token(self, token_id: str, *, now: float) -> bool:
        """False when it was revoked already, such as by a refresh that won a race."""
        ...

    async def revoke_family(self, family_id: str, *, now: float) -> None: ...

    async def revoke_subject(self, subject: str, *, now: float) -> None: ...

    async def save_credentials(self, credentials: UpstreamCredentials) -> str:
        """Keeps the credentials and returns the user's subject, the same each time the same
        username signs in."""
        ...

    async def get_credentials(self, subject: str) -> UpstreamCredentials | None:
        """None when the user never signed in, or what was kept can no longer be read."""
        ...

    async def count_failed_sign_ins(self, username: str, *, since: float) -> int: ...

    async def record_failed_sign_in(self, username: str, *, now: float) -> None: ...

    async def clear_failed_sign_ins(self, username: str) -> None: ...

    async def purge_expired(self, *, now: float, failed_sign_ins_before: float) -> None:
        """Deletes the pending sign-ins, codes and token families that can no longer be used,
        and the failed sign-ins too old to count."""
        ...
