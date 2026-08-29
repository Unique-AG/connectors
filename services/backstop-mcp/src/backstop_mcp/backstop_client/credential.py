"""What a request needs to authenticate as one Backstop user, and who can supply it.

Both live here rather than in `features/auth` because they are transport concerns:
`BackstopClient` sends the credential on every request, and `BackstopClientFactory` asks the
context whose credential to send. `features/auth` owns the *other* half — encrypting the
credential at rest, and resolving "which MCP subject is this" — and depends on these types, not
the reverse. Keeping the direction one-way is what `tests/test_layering.py` asserts.
"""

from collections.abc import Awaitable, Callable
from typing import ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, SecretStr


class BackstopCredentialSecret(BaseModel):
    """A user's Backstop username + personal API token, decrypted and held in memory only.

    `api_token` is a `SecretStr` so an accidental `logger.info(credential)` (or any repr/str
    conversion) prints `**********` instead of the token — call `.get_secret_value()` to use it.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    username: str
    api_token: SecretStr


type AuthFailureHook = Callable[[], Awaitable[None]]


class CallerSession(BaseModel):
    """Who one Backstop request authenticates as — resolved per call, not held by the client.

    `BackstopClient` keeps a `CallerSessionProvider` rather than a credential, which is what
    lets one process-wide client serve every caller: it asks for this triple at the start of
    each public call and threads it through. `subject` and `on_auth_failure` travel with the
    credential because they are just as per-caller — the subject labels the logs, and the hook
    revokes *that* caller's MCP tokens once Backstop confirms their credential is dead.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    credential: BackstopCredentialSecret
    subject: str | None = None
    # None only for login (`verify_credential`): that call *is* the credential check, so a 401
    # must fail fast instead of re-probing `/system-info`. Mid-session sessions always carry one.
    on_auth_failure: AuthFailureHook | None = None


type CallerSessionProvider = Callable[[], Awaitable[CallerSession]]


class CallerAuthContext(Protocol):
    """Resolves "whose Backstop credential" for the in-flight MCP request.

    A Protocol, not the concrete class: the implementation
    (`features.auth.context.BackstopAuthContext`) needs the database, the encryption key and the
    OAuth provider's revocation hook, none of which the transport layer should know about.
    """

    async def current_credential(self) -> BackstopCredentialSecret:
        """The calling MCP user's stored credential.

        Raises if the caller hasn't completed the login flow — see
        `features.auth.context.NotConnectedError`.
        """
        ...

    def current_subject(self) -> str | None:
        """MCP access-token subject for the in-flight request, if any."""
        ...

    async def revoke_current_subject_tokens(self) -> None:
        """Revoke the active subject's MCP tokens after a mid-session Backstop 401."""
        ...
