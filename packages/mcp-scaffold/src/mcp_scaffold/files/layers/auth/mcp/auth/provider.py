from collections.abc import Awaitable
from collections.abc import Callable
import hashlib
import logging
import secrets
import time
from typing import NoReturn, override
import uuid

from fastmcp.server.auth import AccessToken
from fastmcp.server.auth import OAuthProvider
from mcp.server.auth.provider import AuthorizationCode
from mcp.server.auth.provider import AuthorizationParams
from mcp.server.auth.provider import construct_redirect_uri
from mcp.server.auth.provider import RefreshToken
from mcp.server.auth.provider import TokenError
from mcp.server.auth.settings import ClientRegistrationOptions
from mcp.server.auth.settings import RevocationOptions
from mcp.shared.auth import OAuthClientInformationFull
from mcp.shared.auth import OAuthToken
from pydantic import AnyUrl
from pydantic import SecretStr
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.responses import Response
from starlette.routing import Route

from mcp_skeleton.mcp.auth.login_page import csrf_cookie
from mcp_skeleton.mcp.auth.login_page import csrf_token_matches
from mcp_skeleton.mcp.auth.login_page import login_page
from mcp_skeleton.mcp.auth.login_page import message_page
from mcp_skeleton.mcp.auth.login_page import new_csrf_token
from mcp_skeleton.mcp.auth.settings import AuthSettings
from mcp_skeleton.shared import AuthStore
from mcp_skeleton.shared import IssuedToken
from mcp_skeleton.shared import PendingSignIn
from mcp_skeleton.shared import UpstreamCredentials
from mcp_skeleton.upstream import UpstreamError

LOGIN_PATH = "/sign-in"
_TITLE = "MCP Skeleton"
_AUTHORIZATION_CODE_SECONDS = 5 * 60
_PENDING_SIGN_IN_SECONDS = 10 * 60
_MAX_USERNAME_LENGTH = 320
_EXPIRED = "This sign-in link has expired or was already used. Start again from your MCP client."
_LOGGER = logging.getLogger(__name__)

type VerifyCredentials = Callable[[UpstreamCredentials], Awaitable[bool]]


class CredentialsAuthProvider(OAuthProvider):
    """An OAuth server for the MCP's clients, where each user signs in on `LOGIN_PATH` with their
    own credentials for the upstream. The upstream checks them, and the store keeps them for the
    calls made for that user. Each access token names the user as its subject, which FastMCP
    keeps for the request: `get_access_token().subject`.
    """

    def __init__(
        self,
        *,
        base_url: str,
        settings: AuthSettings,
        store: Callable[[], AuthStore],
        verify: VerifyCredentials,
    ) -> None:
        super().__init__(
            base_url=base_url,
            client_registration_options=ClientRegistrationOptions(enabled=True),
            revocation_options=RevocationOptions(enabled=True),
        )
        self._settings: AuthSettings = settings
        self._store: Callable[[], AuthStore] = store
        self._verify: VerifyCredentials = verify
        self._login_url: str = f"{base_url.rstrip('/')}{LOGIN_PATH}"
        self._secure_cookies: bool = base_url.startswith("https://")

    @override
    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        return [
            *super().get_routes(mcp_path),
            Route(LOGIN_PATH, self._show_sign_in, methods=["GET"]),
            Route(LOGIN_PATH, self._sign_in, methods=["POST"]),
        ]

    @override
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        client = await self._store().get_client(client_id)
        if client is None:
            return None
        return OAuthClientInformationFull.model_validate_json(client.registration)

    @override
    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        assert client_info.client_id is not None, "the SDK assigns the id before registering"
        await self._store().save_client(
            client_id=client_info.client_id,
            registration=client_info.model_dump_json(),
            now=time.time(),
        )

    @override
    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        assert client.client_id is not None, "a registered client has an id"
        now = time.time()
        store = self._store()
        await store.purge_expired(
            now=now, failed_sign_ins_before=now - self._failed_sign_in_window_seconds
        )
        request_id = secrets.token_urlsafe(32)
        await store.save_pending_sign_in(
            PendingSignIn(
                request_id=request_id,
                client_id=client.client_id,
                scopes=" ".join(params.scopes or []),
                code_challenge=params.code_challenge,
                redirect_uri=str(params.redirect_uri),
                redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                state=params.state,
                resource=params.resource,
                expires_at=now + _PENDING_SIGN_IN_SECONDS,
            )
        )
        return f"{self._login_url}?request_id={request_id}"

    @override
    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        assert client.client_id is not None, "a registered client has an id"
        code = await self._store().get_authorization_code(
            authorization_code, client_id=client.client_id, now=time.time()
        )
        if code is None:
            return None
        return AuthorizationCode(
            code=code.code,
            scopes=code.scopes.split(),
            expires_at=code.expires_at,
            client_id=code.client_id,
            code_challenge=code.code_challenge,
            redirect_uri=AnyUrl(code.redirect_uri),
            redirect_uri_provided_explicitly=code.redirect_uri_provided_explicitly,
            resource=code.resource,
            subject=code.subject,
        )

    @override
    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        assert client.client_id is not None, "a registered client has an id"
        assert authorization_code.subject is not None, "every code this provider issues has one"
        store = self._store()
        if not await store.take_authorization_code(
            authorization_code.code, client_id=client.client_id, now=time.time()
        ):
            raise TokenError(
                error="invalid_grant", error_description="Authorization code was already used"
            )
        return await self._issue_tokens(
            store,
            family_id=str(uuid.uuid4()),
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            resource=authorization_code.resource,
            subject=authorization_code.subject,
        )

    @override
    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        token = await self._store().get_token_by_refresh_hash(_hash(refresh_token))
        if token is None or token.client_id != client.client_id:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=token.client_id,
            scopes=token.scopes.split(),
            expires_at=int(token.refresh_token_expires_at),
            subject=token.subject,
        )

    @override
    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        """Revokes the pair and issues the next one. A refresh token used twice was stolen or
        replayed, so its whole family is revoked and the user signs in again."""
        store = self._store()
        now = time.time()
        token = await store.get_token_by_refresh_hash(_hash(refresh_token.token))
        if token is None or token.refresh_token_expires_at < now:
            raise TokenError(error="invalid_grant", error_description="Refresh token has expired")
        if token.revoked_at is not None:
            await self._revoke_reused(store, token.family_id, now=now)
        granted = token.scopes.split()
        if not set(scopes) <= set(granted):
            raise TokenError(
                error="invalid_scope",
                error_description="The requested scopes exceed those granted",
            )
        if not await store.revoke_token(token.id, now=now):
            await self._revoke_reused(store, token.family_id, now=now)
        return await self._issue_tokens(
            store,
            family_id=token.family_id,
            client_id=token.client_id,
            scopes=scopes or granted,
            resource=token.resource,
            subject=token.subject,
        )

    @override
    async def load_access_token(self, token: str) -> AccessToken | None:
        record = await self._store().get_token_by_access_hash(_hash(token))
        if (
            record is None
            or record.revoked_at is not None
            or record.access_token_expires_at < time.time()
        ):
            return None
        return AccessToken(
            token=token,
            client_id=record.client_id,
            scopes=record.scopes.split(),
            expires_at=int(record.access_token_expires_at),
            resource=record.resource,
            subject=record.subject,
            claims={"sub": record.subject},
        )

    @override
    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        store = self._store()
        record = await store.get_token_by_access_hash(
            _hash(token.token)
        ) or await store.get_token_by_refresh_hash(_hash(token.token))
        if record is not None:
            await store.revoke_family(record.family_id, now=time.time())

    async def revoke_subject(self, subject: str) -> None:
        """Signs the user out of every client, such as once the upstream stops accepting their
        credentials."""
        await self._store().revoke_subject(subject, now=time.time())

    async def _show_sign_in(self, request: Request) -> Response:
        request_id = request.query_params.get("request_id", "")
        if await self._store().get_pending_sign_in(request_id, now=time.time()) is None:
            return message_page(title=_TITLE, message=_EXPIRED, status_code=400)
        return self._form(request_id)

    async def _sign_in(self, request: Request) -> Response:
        form = await request.form(max_files=0, max_fields=4)
        request_id = _field(form.get("request_id"))
        username = _field(form.get("username")).strip()
        password = _field(form.get("password"))
        store = self._store()
        now = time.time()
        if await store.get_pending_sign_in(request_id, now=now) is None:
            return message_page(title=_TITLE, message=_EXPIRED, status_code=400)
        if not csrf_token_matches(request, request_id, _field(form.get("csrf_token"))):
            return self._form(
                request_id,
                username=username,
                error="Your session expired. Sign in again.",
                status=400,
            )
        if not username or not password or len(username) > _MAX_USERNAME_LENGTH:
            return self._form(
                request_id, username=username, error="Enter your username and password.", status=400
            )
        since = now - self._failed_sign_in_window_seconds
        if await store.count_failed_sign_ins(username, since=since) >= (
            self._settings.max_failed_sign_ins
        ):
            return self._form(
                request_id,
                username=username,
                error="Too many failed sign-ins. Try again later.",
                status=429,
            )
        credentials = UpstreamCredentials(username=username, password=SecretStr(password))
        try:
            accepted = await self._verify(credentials)
        except UpstreamError:
            _LOGGER.warning("The upstream could not check a sign-in", exc_info=True)
            return self._form(
                request_id,
                username=username,
                error="The sign-in could not be checked. Try again.",
                status=503,
            )
        if not accepted:
            await store.record_failed_sign_in(username, now=now)
            return self._form(
                request_id, username=username, error="Wrong username or password.", status=401
            )
        await store.clear_failed_sign_ins(username)
        subject = await store.save_credentials(credentials)
        code = secrets.token_urlsafe(32)
        pending = await store.complete_sign_in(
            request_id,
            code=code,
            subject=subject,
            code_expires_at=now + _AUTHORIZATION_CODE_SECONDS,
            now=now,
        )
        if pending is None:
            return message_page(title=_TITLE, message=_EXPIRED, status_code=400)
        response = RedirectResponse(
            construct_redirect_uri(pending.redirect_uri, code=code, state=pending.state),
            status_code=302,
        )
        response.delete_cookie(csrf_cookie(request_id), path=LOGIN_PATH)
        return response

    def _form(
        self, request_id: str, *, username: str = "", error: str | None = None, status: int = 200
    ) -> Response:
        """A new CSRF token with every form, set in the cookie the submission is checked with."""
        token = new_csrf_token()
        response = login_page(
            title=_TITLE,
            request_id=request_id,
            csrf_token=token,
            username=username,
            error=error,
            status_code=status,
        )
        response.set_cookie(
            csrf_cookie(request_id),
            token,
            max_age=_PENDING_SIGN_IN_SECONDS,
            path=LOGIN_PATH,
            secure=self._secure_cookies,
            httponly=True,
            samesite="lax",
        )
        return response

    async def _issue_tokens(
        self,
        store: AuthStore,
        *,
        family_id: str,
        client_id: str,
        scopes: list[str],
        resource: str | None,
        subject: str,
    ) -> OAuthToken:
        access_token = secrets.token_urlsafe(32)
        refresh_token = secrets.token_urlsafe(32)
        now = time.time()
        access_seconds = self._settings.access_token_minutes * 60
        await store.save_tokens(
            IssuedToken(
                id=str(uuid.uuid4()),
                family_id=family_id,
                client_id=client_id,
                scopes=" ".join(scopes),
                resource=resource,
                subject=subject,
                access_token_expires_at=now + access_seconds,
                refresh_token_expires_at=now + self._settings.refresh_token_days * 86400,
            ),
            access_hash=_hash(access_token),
            refresh_hash=_hash(refresh_token),
        )
        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=access_seconds,
            scope=" ".join(scopes) or None,
            refresh_token=refresh_token,
        )

    @staticmethod
    async def _revoke_reused(store: AuthStore, family_id: str, *, now: float) -> NoReturn:
        await store.revoke_family(family_id, now=now)
        raise TokenError(error="invalid_grant", error_description="Refresh token was already used")

    @property
    def _failed_sign_in_window_seconds(self) -> float:
        return self._settings.failed_sign_in_window_minutes * 60


def _hash(token: str) -> str:
    """Tokens are kept as hashes, so a copy of the database signs nobody in."""
    return hashlib.sha256(token.encode()).hexdigest()


def _field(value: object) -> str:
    """A form value, or empty for a missing field or a file."""
    return value if isinstance(value, str) else ""
