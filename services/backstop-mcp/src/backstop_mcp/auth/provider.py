import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import ClassVar, override

from fastmcp.server.auth.auth import AccessToken, OAuthProvider
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

from backstop_mcp.auth.credential_store import find_user_id_by_username, save_credential
from backstop_mcp.auth.crypto import BackstopCredentialSecret
from backstop_mcp.auth.login_form import render_login_form
from backstop_mcp.backstop_client import BackstopUnreachableError, verify_credential
from backstop_mcp.db.engine import get_session
from backstop_mcp.db.models import AuthorizationCode as AuthorizationCodeRow
from backstop_mcp.db.models import OAuthClient as OAuthClientRow
from backstop_mcp.db.models import OAuthToken as OAuthTokenRow
from backstop_mcp.db.models import PendingAuthorization


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


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
    _backstop_base_url: str
    login_path: str

    def __init__(
        self,
        *,
        base_url: str,
        session_factory: async_sessionmaker[AsyncSession],
        encryption_key: bytes,
        backstop_base_url: str,
        login_path: str = "/backstop/login",
    ) -> None:
        super().__init__(
            base_url=base_url,
            client_registration_options=ClientRegistrationOptions(enabled=True),
            revocation_options=RevocationOptions(enabled=True),
        )
        self._session_factory = session_factory
        self._encryption_key = encryption_key
        self._backstop_base_url = backstop_base_url
        self.login_path = login_path

    # -- Dynamic client registration -----------------------------------------------------

    @override
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        async with get_session(self._session_factory) as session:
            row = await session.get(OAuthClientRow, client_id)
        if row is None:
            return None
        return OAuthClientInformationFull.model_validate_json(row.client_metadata_json)

    @override
    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        assert client_info.client_id is not None, "client_id must be assigned before registration"
        async with get_session(self._session_factory) as session:
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

        async with get_session(self._session_factory) as session:
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
        async with get_session(self._session_factory) as session:
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

        try:
            valid = await verify_credential(username, api_token, self._backstop_base_url)
        except BackstopUnreachableError:
            return HTMLResponse(
                render_login_form(
                    request_id,
                    username=username,
                    error="Backstop is unreachable right now — please try again shortly.",
                )
            )

        if not valid:
            return HTMLResponse(
                render_login_form(
                    request_id,
                    username=username,
                    error="Invalid username or API token.",
                )
            )

        code = secrets.token_urlsafe(32)
        code_expires_at = (datetime.now(UTC) + self.AUTHORIZATION_CODE_TTL).timestamp()

        async with get_session(self._session_factory) as session:
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
        async with get_session(self._session_factory) as session:
            pending = await session.get(PendingAuthorization, request_id)
        if pending is None or pending.expires_at < datetime.now(UTC):
            return None
        return pending

    # -- Authorization code exchange ---------------------------------------------------------

    @override
    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        async with get_session(self._session_factory) as session:
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

        async with get_session(self._session_factory) as session:
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
            # Authorization codes are single-use.
            await session.execute(
                delete(AuthorizationCodeRow).where(
                    AuthorizationCodeRow.code == authorization_code.code
                )
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
        async with get_session(self._session_factory) as session:
            result = await session.execute(
                select(OAuthTokenRow).where(OAuthTokenRow.refresh_token_hash == token_hash)
            )
            row = result.scalar_one_or_none()

        if row is None or row.client_id != client.client_id or row.revoked_at is not None:
            return None

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
        token_hash = _hash_token(refresh_token.token)
        now = datetime.now(UTC)

        # `TokenError` is a frozen dataclass exception — raising it while an `async with
        # get_session(...)` block is still open breaks (the context manager's `__aexit__`
        # tries to set `__traceback__` on the exception, which a frozen dataclass rejects).
        # So every branch below only *decides* what to raise/return here, and the actual
        # `raise`/`return` happens after the session block has closed.
        reused = False
        unknown = False
        new_access_token = ""
        new_refresh_token = ""
        effective_scopes: list[str] = []

        async with get_session(self._session_factory) as session:
            result = await session.execute(
                select(OAuthTokenRow).where(OAuthTokenRow.refresh_token_hash == token_hash)
            )
            row = result.scalar_one_or_none()
            if row is None:
                unknown = True
            elif row.revoked_at is not None:
                # This refresh token was already rotated away once — someone is replaying a
                # stolen/leaked token. Revoke every token descending from the same grant.
                reused = True
                await session.execute(
                    update(OAuthTokenRow)
                    .where(
                        OAuthTokenRow.family_id == row.family_id,
                        OAuthTokenRow.revoked_at.is_(None),
                    )
                    .values(revoked_at=now)
                )
            else:
                new_access_token = secrets.token_urlsafe(32)
                new_refresh_token = secrets.token_urlsafe(32)
                effective_scopes = scopes or row.scopes

                row.revoked_at = now
                session.add(
                    OAuthTokenRow(
                        family_id=row.family_id,
                        access_token_hash=_hash_token(new_access_token),
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

        if unknown:
            raise TokenError(error="invalid_grant", error_description="Unknown refresh token")
        if reused:
            raise TokenError(
                error="invalid_grant",
                error_description="Refresh token has already been used",
            )

        return OAuthTokenResponse(
            access_token=new_access_token,
            token_type="Bearer",
            expires_in=int(self.ACCESS_TOKEN_TTL.total_seconds()),
            scope=" ".join(effective_scopes) if effective_scopes else None,
            refresh_token=new_refresh_token,
        )

    # -- Access token verification / revocation ------------------------------------------------

    @override
    async def load_access_token(self, token: str) -> AccessToken | None:
        token_hash = _hash_token(token)
        async with get_session(self._session_factory) as session:
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
        async with get_session(self._session_factory) as session:
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
        async with get_session(self._session_factory) as session:
            await session.execute(
                update(OAuthTokenRow)
                .where(
                    OAuthTokenRow.subject == subject,
                    OAuthTokenRow.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(UTC))
            )
