import hashlib
import logging
import secrets
import time
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

from backstop_mcp.backstop_client import (
    BackstopClientFactory,
    BackstopCredentialSecret,
    BackstopUnreachableError,
)
from backstop_mcp.db import AuthorizationCode as AuthorizationCodeRow
from backstop_mcp.db import OAuthClient as OAuthClientRow
from backstop_mcp.db import OAuthToken as OAuthTokenRow
from backstop_mcp.db import PendingAuthorization, read_session, transaction
from backstop_mcp.features.auth.credential_store import save_credential
from backstop_mcp.features.auth.login_csrf import (
    clear_csrf_cookie,
    csrf_token_is_valid,
    issue_csrf_token,
    set_csrf_cookie,
)
from backstop_mcp.features.auth.login_form import render_login_form
from backstop_mcp.features.auth.throttle import (
    MAX_USERNAME_LENGTH,
    ThrottleConfig,
    clear_failures,
    is_throttled,
    record_failure,
)

logger = logging.getLogger(__name__)


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

# Applied to every login-endpoint response. `Referrer-Policy` is the load-bearing one: the
# `request_id` travels in the login URL's query string, and without this the browser would
# forward it in the `Referer` of anything the page links to or loads. `no-store` keeps it out of
# shared caches and the back/forward cache for the same reason.
_LOGIN_SECURITY_HEADERS = {
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}

_EXPIRED_LINK_MESSAGE = (
    "This login link is invalid or has expired. Please reconnect from your MCP client."
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
        secure_cookies: bool,
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
        # `base_url` arrives already validated and trailing-slash-free (`AppConfig.issuer`), so
        # it is kept verbatim rather than read back off `self.base_url` — the SDK re-parses it
        # into an `AnyHttpUrl`, which renders the slash straight back on.
        self._issuer: str = base_url
        # Drives the CSRF cookie's `Secure` flag. Passed in rather than re-parsed here so the
        # public URL is parsed exactly once, in `AppConfig`. A local http:// development deploy
        # still gets a working form; every real deploy (https, enforced for production by
        # `AppConfig`) gets the flag.
        self._secure_cookies: bool = secure_cookies

    # -- Dynamic client registration -----------------------------------------------------

    @override
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        async with read_session(self._session_factory) as session:
            row = await session.get(OAuthClientRow, client_id)
        if row is None:
            return None
        return OAuthClientInformationFull.model_validate(row.client_metadata)

    @override
    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        assert client_info.client_id is not None, "client_id must be assigned before registration"
        async with transaction(self._session_factory) as session:
            session.add(
                OAuthClientRow(
                    client_id=client_info.client_id,
                    client_metadata=client_info.model_dump(mode="json"),
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

        return f"{self._issuer}{self.login_path}?request_id={request_id}"

    # -- Login form: our replacement for the third-party OAuth redirect ---------------------

    def _expired_link_response(self) -> Response:
        return PlainTextResponse(
            _EXPIRED_LINK_MESSAGE, status_code=400, headers=_LOGIN_SECURITY_HEADERS
        )

    def _form_response(
        self,
        request_id: str,
        *,
        status_code: int = 200,
        client_name: str | None = None,
        username: str = "",
        error: str | None = None,
    ) -> Response:
        """Render the login form with a freshly-issued CSRF token and matching cookie.

        Every render goes through here, including the re-renders after a failed submission, so
        the cookie and the hidden field can't drift apart. A fresh token per render (rather than
        echoing the one just submitted) means an error page never reflects an attacker-supplied
        value back into the form.
        """
        csrf_token = issue_csrf_token()
        response = HTMLResponse(
            render_login_form(
                request_id,
                csrf_token,
                client_name=client_name,
                username=username,
                error=error,
            ),
            status_code=status_code,
            headers=_LOGIN_SECURITY_HEADERS,
        )
        set_csrf_cookie(
            response,
            request_id,
            csrf_token,
            path=self.login_path,
            max_age_seconds=int(self.PENDING_AUTHORIZATION_TTL.total_seconds()),
            secure=self._secure_cookies,
        )
        return response

    async def handle_login_get(self, request: Request) -> Response:
        request_id = request.query_params.get("request_id", "")
        pending = await self._load_pending(request_id)
        if pending is None:
            return self._expired_link_response()

        client_name = None
        async with read_session(self._session_factory) as session:
            client_row = await session.get(OAuthClientRow, pending.client_id)
        if client_row is not None:
            client_info = OAuthClientInformationFull.model_validate(client_row.client_metadata)
            client_name = client_info.client_name

        return self._form_response(request_id, client_name=client_name)

    async def handle_login_post(self, request: Request) -> Response:
        form = await request.form()
        request_id = str(form.get("request_id", ""))
        username = str(form.get("username", "")).strip()
        api_token = str(form.get("api_token", ""))
        csrf_token = str(form.get("csrf_token", ""))

        pending = await self._load_pending(request_id)
        if pending is None:
            return self._expired_link_response()

        # Before anything else, and in particular before the credential reaches Backstop: a
        # submission that can't prove it came from the browser this form was served to is not a
        # login attempt worth forwarding. Re-rendering (rather than a bare 400) issues a fresh
        # token, so the legitimate case — a user whose cookie expired while the form sat open —
        # recovers by simply submitting again.
        if not csrf_token_is_valid(request, request_id, csrf_token):
            logger.warning("auth.login.csrf_mismatch")
            return self._form_response(
                request_id,
                status_code=400,
                username=username,
                error="This form expired before it was submitted. Please try again.",
            )

        if not username or not api_token:
            return self._form_response(
                request_id,
                username=username,
                error="Username and API token are both required.",
            )

        # Rejected before any storage or upstream call: the submitted username is
        # attacker-controlled and would otherwise reach a `text` column in `login_attempts`.
        # Treated as an ordinary invalid credential — no Backstop username is this long — so the
        # response is indistinguishable from any other bad submission.
        if len(username) > MAX_USERNAME_LENGTH:
            return self._form_response(request_id, error="Invalid username or API token.")

        # Checked before contacting Backstop — the point of the limit is to stop this endpoint
        # being used to test credentials against Backstop at all.
        if await is_throttled(self._session_factory, username, config=self._throttle):
            return self._form_response(
                request_id,
                status_code=429,
                username=username,
                error=(
                    "Too many failed attempts for this username. "
                    + "Please wait a few minutes and try again."
                ),
            )

        try:
            valid = await self._backstop_clients.verify_credential(username, api_token)
        except BackstopUnreachableError as exc:
            # Not recorded as a failed attempt: nothing was learned about the credential, so
            # counting it would let a Backstop outage lock users out.
            logger.warning("auth.login.backstop_unreachable", extra={"error": str(exc)})
            return self._form_response(
                request_id,
                username=username,
                error="Backstop is unreachable right now — please try again shortly.",
            )

        if not valid:
            await record_failure(self._session_factory, username, source_ip=_source_ip(request))
            return self._form_response(
                request_id,
                username=username,
                error="Invalid username or API token.",
            )

        # Authenticated, so the guessing budget is irrelevant for this username.
        await clear_failures(self._session_factory, username)

        code = secrets.token_urlsafe(32)
        code_expires_at = (datetime.now(UTC) + self.AUTHORIZATION_CODE_TTL).timestamp()

        # Same frozen-decision pattern as `exchange_authorization_code`: decide inside the
        # transaction, return only after it closes.
        already_claimed = False

        async with transaction(self._session_factory) as session:
            # Pending authorizations are single-use. `DELETE ... WHERE request_id = ...`
            # claims the row atomically — under concurrent submits for the same request,
            # only one transaction's delete affects a row; the other must not mint a code.
            claim = await session.execute(
                delete(PendingAuthorization).where(PendingAuthorization.request_id == request_id)
            )
            if claim.rowcount == 0:  # pyright: ignore[reportUnknownMemberType, reportAttributeAccessIssue]
                already_claimed = True
            else:
                # Propose a fresh id; `save_credential` upserts on `backstop_username` and
                # returns the durable id (existing row wins under concurrent first logins).
                user_id = await save_credential(
                    session,
                    str(uuid.uuid4()),
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

        if already_claimed:
            return self._expired_link_response()

        redirect_url = construct_redirect_uri(pending.redirect_uri, code=code, state=pending.state)
        response = RedirectResponse(redirect_url, status_code=302, headers=_LOGIN_SECURITY_HEADERS)
        # The pending authorization is gone, so its CSRF cookie has nothing left to protect.
        clear_csrf_cookie(response, request_id, path=self.login_path, secure=self._secure_cookies)
        return response

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
        # `expires_at` is a POSIX timestamp (same shape as the MCP SDK's AuthorizationCode).
        if row.expires_at < time.time():
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

    async def revoke_all_tokens_for_subject(self, subject: str) -> None:
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
