import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import ClassVar, Literal, override

from fastmcp.server.auth import AccessToken, OAuthProvider
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import OAuthClientInformationFull
from mcp.shared.auth import OAuthToken as OAuthTokenResponse
from pydantic import AnyUrl, SecretStr
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response

from backstop_mcp.backstop_client import BackstopClientFactory, BackstopUnreachableError
from backstop_mcp.db.engine import read_session, transaction
from backstop_mcp.db.models import AuthorizationCode as AuthorizationCodeRow
from backstop_mcp.db.models import OAuthClient as OAuthClientRow
from backstop_mcp.db.models import OAuthToken as OAuthTokenRow
from backstop_mcp.db.models import PendingAuthorization
from backstop_mcp.features.auth.credential_store import find_user_id_by_username, save_credential
from backstop_mcp.features.auth.crypto import BackstopCredentialSecret
from backstop_mcp.features.auth.login_form import render_login_form
from backstop_mcp.features.auth.throttle import (
    MAX_USERNAME_LENGTH,
    ThrottleConfig,
    clear_failures,
    is_throttled,
    record_failure,
)
from backstop_mcp.logging import get_logger

logger = get_logger(__name__)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _source_ip(request: Request) -> str | None:
    """The peer address, recorded on a failed attempt for diagnosis only.

    Behind an ingress this is the ingress's address, which is exactly why `auth/throttle.py`
    does not rate-limit on it. `X-Forwarded-For` is deliberately ignored: it's client-supplied,
    so treating it as an identity would record whatever an attacker chose to send.
    """
    return request.client.host if request.client is not None else None


# --- Refresh rotation outcomes ---------------------------------------------------------------
#
# `_rotate_refresh_token` returns one of these instead of raising, because `TokenError` cannot be
# raised while the transaction is still open (see `exchange_refresh_token`). Modelling the two
# results as types rather than a set of booleans keeps every database branch a single `return`.


@dataclass(frozen=True)
class _RefreshRotated:
    """The token rotated successfully. `scopes` are the ones actually granted."""

    access_token: str
    refresh_token: str
    scopes: list[str]


@dataclass(frozen=True)
class _RefreshRejected:
    """The rotation was refused, carrying the OAuth error the caller should raise."""

    error: Literal["invalid_grant", "invalid_scope"]
    description: str


type _RefreshOutcome = _RefreshRotated | _RefreshRejected

_UNKNOWN_TOKEN = _RefreshRejected("invalid_grant", "Unknown refresh token")
_REUSED_TOKEN = _RefreshRejected("invalid_grant", "Refresh token has already been used")
_EXPIRED_TOKEN = _RefreshRejected("invalid_grant", "Refresh token has expired")
_INVALID_SCOPE = _RefreshRejected(
    "invalid_scope", "Requested scope exceeds originally granted scopes"
)


class BackstopOAuthProvider(OAuthProvider):
    """FastMCP OAuth 2.1 authorization server whose "login" step is a Backstop credential form.

    Backstop itself has no OAuth — so instead of redirecting to a third-party identity
    provider, `authorize()` redirects the browser to our own hosted login page
    (`handle_login_get`/`handle_login_post`), which collects a Backstop username + personal
    API token, verifies it against Backstop, and only then mints an authorization code.
    """

    ACCESS_TOKEN_TTL: ClassVar[timedelta] = timedelta(minutes=15)
    REFRESH_TOKEN_TTL: ClassVar[timedelta] = timedelta(days=30)
    AUTHORIZATION_CODE_TTL: ClassVar[timedelta] = timedelta(minutes=5)
    PENDING_AUTHORIZATION_TTL: ClassVar[timedelta] = timedelta(minutes=10)

    _session_factory: async_sessionmaker[AsyncSession]
    _encryption_key: bytes
    _backstop_clients: BackstopClientFactory
    _throttle: ThrottleConfig
    login_path: str

    def __init__(
        self,
        *,
        base_url: str,
        session_factory: async_sessionmaker[AsyncSession],
        encryption_key: bytes,
        backstop_clients: BackstopClientFactory,
        throttle: ThrottleConfig,
        login_path: str = "/backstop/login",
    ) -> None:
        super().__init__(
            base_url=base_url,
            client_registration_options=ClientRegistrationOptions(enabled=True),
            revocation_options=RevocationOptions(enabled=True),
        )
        self._session_factory = session_factory
        self._encryption_key = encryption_key
        # Credential verification goes through the shared factory so the login form reuses the
        # same connection pool, base URL and timeout profile as every tool call.
        self._backstop_clients = backstop_clients
        self._throttle = throttle
        self.login_path = login_path

    # -- Dynamic client registration -----------------------------------------------------

    @override
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        async with read_session(self._session_factory) as session:
            row = await session.get(OAuthClientRow, client_id)
        if row is None:
            return None
        return OAuthClientInformationFull.model_validate_json(row.client_metadata_json)

    @override
    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        assert client_info.client_id is not None, "client_id must be assigned before registration"
        async with transaction(self._session_factory) as session:
            session.add(
                OAuthClientRow(
                    client_id=client_info.client_id,
                    client_metadata_json=client_info.model_dump_json(),
                )
            )

    # -- Authorization: redirect to our own login form, not a third party -------------------

    @override
    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        assert client.client_id is not None
        request_id = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + self.PENDING_AUTHORIZATION_TTL

        async with transaction(self._session_factory) as session:
            session.add(
                PendingAuthorization(
                    request_id=request_id,
                    client_id=client.client_id,
                    scopes=params.scopes or [],
                    code_challenge=params.code_challenge,
                    redirect_uri=str(params.redirect_uri),
                    redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                    state=params.state,
                    resource=params.resource,
                    expires_at=expires_at,
                )
            )

        base = str(self.base_url).rstrip("/")
        return f"{base}{self.login_path}?request_id={request_id}"

    # -- Login form: our replacement for the third-party OAuth redirect ---------------------

    async def handle_login_get(self, request: Request) -> Response:
        request_id = request.query_params.get("request_id", "")
        pending = await self._load_pending(request_id)
        if pending is None:
            return PlainTextResponse(
                "This login link is invalid or has expired. Please reconnect from your MCP client.",
                status_code=400,
            )

        client_name = None
        async with read_session(self._session_factory) as session:
            client_row = await session.get(OAuthClientRow, pending.client_id)
        if client_row is not None:
            client_info = OAuthClientInformationFull.model_validate_json(
                client_row.client_metadata_json
            )
            client_name = client_info.client_name

        return HTMLResponse(render_login_form(request_id, client_name=client_name))

    async def handle_login_post(self, request: Request) -> Response:
        form = await request.form()
        request_id = str(form.get("request_id", ""))
        username = str(form.get("username", "")).strip()
        api_token = str(form.get("api_token", ""))

        pending = await self._load_pending(request_id)
        if pending is None:
            return PlainTextResponse(
                "This login link is invalid or has expired. Please reconnect from your MCP client.",
                status_code=400,
            )

        if not username or not api_token:
            return HTMLResponse(
                render_login_form(
                    request_id,
                    username=username,
                    error="Username and API token are both required.",
                )
            )

        # Rejected before any storage or upstream call: the submitted username is
        # attacker-controlled and would otherwise reach a `text` column in `login_attempts`.
        # Treated as an ordinary invalid credential — no Backstop username is this long — so the
        # response is indistinguishable from any other bad submission.
        if len(username) > MAX_USERNAME_LENGTH:
            return HTMLResponse(
                render_login_form(request_id, error="Invalid username or API token.")
            )

        # Checked before contacting Backstop — the point of the limit is to stop this endpoint
        # being used to test credentials against Backstop at all.
        if await is_throttled(self._session_factory, username, config=self._throttle):
            return HTMLResponse(
                render_login_form(
                    request_id,
                    username=username,
                    error=(
                        "Too many failed attempts for this username. "
                        + "Please wait a few minutes and try again."
                    ),
                ),
                status_code=429,
            )

        try:
            valid = await self._backstop_clients.verify_credential(username, api_token)
        except BackstopUnreachableError as exc:
            # Not recorded as a failed attempt: nothing was learned about the credential, so
            # counting it would let a Backstop outage lock users out.
            logger.warning("auth.login.backstop_unreachable", error=str(exc))
            return HTMLResponse(
                render_login_form(
                    request_id,
                    username=username,
                    error="Backstop is unreachable right now — please try again shortly.",
                )
            )

        if not valid:
            await record_failure(self._session_factory, username, source_ip=_source_ip(request))
            return HTMLResponse(
                render_login_form(
                    request_id,
                    username=username,
                    error="Invalid username or API token.",
                )
            )

        # Authenticated, so the guessing budget is irrelevant for this username.
        await clear_failures(self._session_factory, username)

        code = secrets.token_urlsafe(32)
        code_expires_at = (datetime.now(UTC) + self.AUTHORIZATION_CODE_TTL).timestamp()

        async with transaction(self._session_factory) as session:
            user_id = await find_user_id_by_username(session, username) or str(uuid.uuid4())
            await save_credential(
                session,
                user_id,
                BackstopCredentialSecret(username=username, api_token=SecretStr(api_token)),
                self._encryption_key,
            )
            session.add(
                AuthorizationCodeRow(
                    code=code,
                    client_id=pending.client_id,
                    scopes=pending.scopes,
                    code_challenge=pending.code_challenge,
                    redirect_uri=pending.redirect_uri,
                    redirect_uri_provided_explicitly=pending.redirect_uri_provided_explicitly,
                    resource=pending.resource,
                    subject=user_id,
                    expires_at=code_expires_at,
                )
            )
            await session.execute(
                delete(PendingAuthorization).where(PendingAuthorization.request_id == request_id)
            )

        redirect_url = construct_redirect_uri(pending.redirect_uri, code=code, state=pending.state)
        return RedirectResponse(redirect_url, status_code=302)

    async def _load_pending(self, request_id: str) -> PendingAuthorization | None:
        if not request_id:
            return None
        async with read_session(self._session_factory) as session:
            pending = await session.get(PendingAuthorization, request_id)
        if pending is None or pending.expires_at < datetime.now(UTC):
            return None
        return pending

    # -- Authorization code exchange ---------------------------------------------------------

    @override
    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        async with read_session(self._session_factory) as session:
            row = await session.get(AuthorizationCodeRow, authorization_code)
        if row is None or row.client_id != client.client_id:
            return None
        return AuthorizationCode(
            code=row.code,
            scopes=row.scopes,
            expires_at=row.expires_at,
            client_id=row.client_id,
            code_challenge=row.code_challenge,
            redirect_uri=AnyUrl(row.redirect_uri),
            redirect_uri_provided_explicitly=row.redirect_uri_provided_explicitly,
            resource=row.resource,
            subject=row.subject,
        )

    @override
    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthTokenResponse:
        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)

        # Same frozen-dataclass-exception caveat as `exchange_refresh_token` below: decide,
        # then raise/return only after the session block has closed.
        already_consumed = False

        async with transaction(self._session_factory) as session:
            # Authorization codes are single-use. `DELETE ... WHERE code = ...` claims the
            # row atomically — under concurrent exchanges of the same code, only one
            # transaction's delete affects a row; the other sees `rowcount == 0` and must
            # not mint a token pair.
            result = await session.execute(
                delete(AuthorizationCodeRow).where(
                    AuthorizationCodeRow.code == authorization_code.code
                )
            )
            if result.rowcount == 0:  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]
                already_consumed = True
            else:
                session.add(
                    OAuthTokenRow(
                        family_id=uuid.uuid4(),
                        access_token_hash=_hash_token(access_token),
                        refresh_token_hash=_hash_token(refresh_token),
                        client_id=client.client_id,
                        scopes=authorization_code.scopes,
                        resource=authorization_code.resource,
                        subject=authorization_code.subject,
                        access_token_expires_at=now + self.ACCESS_TOKEN_TTL,
                        refresh_token_expires_at=now + self.REFRESH_TOKEN_TTL,
                    )
                )

        if already_consumed:
            raise TokenError(
                error="invalid_grant",
                error_description="Authorization code has already been used",
            )

        return OAuthTokenResponse(
            access_token=access_token,
            token_type="Bearer",
            expires_in=int(self.ACCESS_TOKEN_TTL.total_seconds()),
            scope=" ".join(authorization_code.scopes) if authorization_code.scopes else None,
            refresh_token=refresh_token,
        )

    # -- Refresh token exchange ---------------------------------------------------------------

    @override
    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        token_hash = _hash_token(refresh_token)
        async with read_session(self._session_factory) as session:
            result = await session.execute(
                select(OAuthTokenRow).where(OAuthTokenRow.refresh_token_hash == token_hash)
            )
            row = result.scalar_one_or_none()

        if row is None or row.client_id != client.client_id:
            return None

        # Deliberately NOT gating on `row.revoked_at` here: an already-rotated-away row is
        # exactly the "someone is replaying a stolen refresh token" case, and
        # `exchange_refresh_token` below is what detects that and revokes the token family.
        # Returning `None` for revoked rows would make the real token-exchange handler reject
        # the request as "unknown" before `exchange_refresh_token` ever runs, leaving reuse
        # detection dead code.
        return RefreshToken(
            token=refresh_token,
            client_id=row.client_id,
            scopes=row.scopes,
            expires_at=(
                int(row.refresh_token_expires_at.timestamp())
                if row.refresh_token_expires_at
                else None
            ),
            subject=row.subject,
        )

    @override
    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthTokenResponse:
        """Rotate a refresh token, detecting reuse.

        Split in two because `TokenError` is a frozen dataclass exception, and raising one while
        an `async with transaction(...)` block is open fails: the context manager's `__aexit__`
        sets `__traceback__` on the exception, which a frozen dataclass rejects. So
        `_rotate_refresh_token` does all the database work and *returns* an outcome, and this
        method turns that outcome into a response or a raise once the session has closed.
        """
        outcome = await self._rotate_refresh_token(refresh_token, scopes)

        if isinstance(outcome, _RefreshRejected):
            raise TokenError(error=outcome.error, error_description=outcome.description)

        return OAuthTokenResponse(
            access_token=outcome.access_token,
            token_type="Bearer",
            expires_in=int(self.ACCESS_TOKEN_TTL.total_seconds()),
            scope=" ".join(outcome.scopes) if outcome.scopes else None,
            refresh_token=outcome.refresh_token,
        )

    async def _rotate_refresh_token(
        self, refresh_token: RefreshToken, scopes: list[str]
    ) -> "_RefreshOutcome":
        """Do the rotation and report what happened. Raises nothing the caller must translate."""
        token_hash = _hash_token(refresh_token.token)
        now = datetime.now(UTC)

        async with transaction(self._session_factory) as session:
            result = await session.execute(
                select(OAuthTokenRow).where(OAuthTokenRow.refresh_token_hash == token_hash)
            )
            row = result.scalar_one_or_none()

            if row is None:
                return _UNKNOWN_TOKEN

            if row.revoked_at is not None:
                # This refresh token was already rotated away once — someone is replaying a
                # stolen/leaked token. Revoke every token descending from the same grant.
                await self._revoke_family(session, family_id=row.family_id, now=now)
                return _REUSED_TOKEN

            if row.refresh_token_expires_at is not None and row.refresh_token_expires_at < now:
                # Enforced here too (not just by the caller) so this holds regardless of
                # which entry point reaches `exchange_refresh_token`.
                return _EXPIRED_TOKEN

            # Refresh may only keep or narrow the originally granted scopes — never widen.
            if scopes and not set(scopes).issubset(row.scopes):
                return _INVALID_SCOPE

            # Claim the row atomically before minting replacement tokens: an
            # `UPDATE ... WHERE revoked_at IS NULL` only ever succeeds for one of two
            # concurrent refreshes of the same token. Mutating `row.revoked_at` via the
            # ORM instead (load-then-write) would let both concurrent requests believe
            # they won, minting two valid descendants from one token.
            claim = await session.execute(
                update(OAuthTokenRow)
                .where(
                    OAuthTokenRow.id == row.id,
                    OAuthTokenRow.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            if claim.rowcount == 0:  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]
                # Lost the race to another concurrent refresh of the same token — treat exactly
                # like replaying an already-rotated token.
                await self._revoke_family(session, family_id=row.family_id, now=now)
                return _REUSED_TOKEN

            access_token = secrets.token_urlsafe(32)
            new_refresh_token = secrets.token_urlsafe(32)
            effective_scopes = scopes or row.scopes

            session.add(
                OAuthTokenRow(
                    family_id=row.family_id,
                    access_token_hash=_hash_token(access_token),
                    refresh_token_hash=_hash_token(new_refresh_token),
                    client_id=row.client_id,
                    scopes=effective_scopes,
                    resource=row.resource,
                    subject=row.subject,
                    access_token_expires_at=now + self.ACCESS_TOKEN_TTL,
                    refresh_token_expires_at=now + self.REFRESH_TOKEN_TTL,
                    rotated_from=row.id,
                )
            )
            return _RefreshRotated(
                access_token=access_token,
                refresh_token=new_refresh_token,
                scopes=effective_scopes,
            )

    @staticmethod
    async def _revoke_family(session: AsyncSession, *, family_id: uuid.UUID, now: datetime) -> None:
        """Revoke every still-live token descending from one grant."""
        await session.execute(
            update(OAuthTokenRow)
            .where(
                OAuthTokenRow.family_id == family_id,
                OAuthTokenRow.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )

    # -- Access token verification / revocation ------------------------------------------------

    @override
    async def load_access_token(self, token: str) -> AccessToken | None:
        token_hash = _hash_token(token)
        async with read_session(self._session_factory) as session:
            result = await session.execute(
                select(OAuthTokenRow).where(OAuthTokenRow.access_token_hash == token_hash)
            )
            row = result.scalar_one_or_none()

        if row is None or row.revoked_at is not None:
            return None
        if row.access_token_expires_at < datetime.now(UTC):
            return None

        return AccessToken(
            token=token,
            client_id=row.client_id,
            scopes=row.scopes,
            expires_at=int(row.access_token_expires_at.timestamp()),
            resource=row.resource,
            subject=row.subject,
        )

    @override
    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        token_hash = _hash_token(token.token)
        async with transaction(self._session_factory) as session:
            result = await session.execute(
                select(OAuthTokenRow).where(
                    (OAuthTokenRow.access_token_hash == token_hash)
                    | (OAuthTokenRow.refresh_token_hash == token_hash)
                )
            )
            row = result.scalar_one_or_none()
            if row is not None:
                row.revoked_at = datetime.now(UTC)

    async def revoke_token_family_for_subject(self, subject: str) -> None:
        """Revoke every non-revoked token belonging to `subject`.

        Called when a Backstop call comes back 401 mid-session (see `auth/context.py`) — the
        stored Backstop credential is no longer valid, so the MCP-facing tokens tied to it are
        forced to fail too, pushing the client back through the login form on its next call.
        """
        async with transaction(self._session_factory) as session:
            await session.execute(
                update(OAuthTokenRow)
                .where(
                    OAuthTokenRow.subject == subject,
                    OAuthTokenRow.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(UTC))
            )
