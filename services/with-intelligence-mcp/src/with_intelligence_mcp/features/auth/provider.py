import logging
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import ClassVar

from mcp_credential_auth import (
    MAX_USERNAME_LENGTH,
    CredentialOAuthProvider,
    LoginCsrf,
    ThrottleConfig,
    clear_failures,
    is_throttled,
    record_failure,
)
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response

from with_intelligence_mcp.db import read_session
from with_intelligence_mcp.features.auth.login_form import render_login_form
from with_intelligence_mcp.features.auth.session_store import (
    find_user_id_by_username,
    save_session,
)
from with_intelligence_mcp.with_intelligence_client import (
    RateLimited,
    SignInFailed,
    Unreachable,
    WiCredential,
    WithIntelligenceClientFactory,
)

logger = logging.getLogger(__name__)


def _source_ip(request: Request) -> str | None:
    """Return the direct peer address."""
    return request.client.host if request.client is not None else None


_LOGIN_SECURITY_HEADERS = {
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}

_EXPIRED_LINK_MESSAGE = (
    "This login link is invalid or has expired. Please reconnect from your MCP client."
)

_LOGIN_CSRF = LoginCsrf("wi_login_csrf_")


class WithIntelligenceOAuthProvider(CredentialOAuthProvider):
    """OAuth provider backed by WI authentication."""

    REFRESH_TOKEN_REUSE_GRACE: ClassVar[timedelta] = timedelta(seconds=10)
    REVOKE_FAMILY_ON_CONCURRENT_REFRESH: ClassVar[bool] = False

    _session_factory: async_sessionmaker[AsyncSession]
    _encryption_key: bytes
    _wi_clients: WithIntelligenceClientFactory
    _throttle: ThrottleConfig
    _forget_cached_session: Callable[[str], None] | None
    login_path: str

    def __init__(
        self,
        *,
        base_url: str,
        secure_cookies: bool,
        session_factory: async_sessionmaker[AsyncSession],
        encryption_key: bytes,
        wi_clients: WithIntelligenceClientFactory,
        throttle: ThrottleConfig,
        login_path: str = "/login",
    ) -> None:
        super().__init__(
            base_url=base_url,
            session_factory=session_factory,
            login_path=login_path,
        )
        self._encryption_key = encryption_key
        self._wi_clients = wi_clients
        self._throttle = throttle
        self._forget_cached_session = None
        self._secure_cookies: bool = secure_cookies

    def attach_forget_cached_session(self, forget_cached_session: Callable[[str], None]) -> None:
        self._forget_cached_session = forget_cached_session

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
        """Render the login form with fresh CSRF credentials."""
        csrf_token = _LOGIN_CSRF.issue_token()
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
        _LOGIN_CSRF.set_cookie(
            response,
            request_id,
            csrf_token,
            path=self.login_path,
            max_age_seconds=int(self.pending_authorization_ttl.total_seconds()),
            secure=self._secure_cookies,
        )
        return response

    async def handle_login_get(self, request: Request) -> Response:
        request_id = request.query_params.get("request_id", "")
        pending = await self.load_pending_authorization(request_id)
        if pending is None:
            return self._expired_link_response()

        client = await self.get_client(pending.client_id)
        client_name = client.client_name if client is not None else None

        return self._form_response(request_id, client_name=client_name)

    async def handle_login_post(self, request: Request) -> Response:
        form = await request.form()
        request_id = str(form.get("request_id", ""))
        username = str(form.get("username", "")).strip()
        password = str(form.get("password", ""))
        csrf_token = str(form.get("csrf_token", ""))

        pending = await self.load_pending_authorization(request_id)
        if pending is None:
            return self._expired_link_response()

        if not _LOGIN_CSRF.token_is_valid(request, request_id, csrf_token):
            logger.warning("auth.login.csrf_mismatch")
            return self._form_response(
                request_id,
                status_code=400,
                username=username,
                error="This form expired before it was submitted. Please try again.",
            )

        if not username or not password:
            return self._form_response(
                request_id,
                username=username,
                error="Username and password are both required.",
            )

        if len(username) > MAX_USERNAME_LENGTH:
            return self._form_response(request_id, error="Invalid username or password.")

        # Checked before contacting With Intelligence — the point of the limit is to stop this
        # endpoint being used to test credentials against them at all.
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

        credential = WiCredential(username=username, password=SecretStr(password))
        try:
            wi_session = await self._wi_clients.sign_in(credential)
        except SignInFailed:
            await record_failure(self._session_factory, username, source_ip=_source_ip(request))
            return self._form_response(
                request_id,
                username=username,
                error="Invalid username or password.",
            )
        except RateLimited as exc:
            logger.warning("auth.login.wi_rate_limited", exc_info=exc)
            return self._form_response(
                request_id,
                status_code=429,
                username=username,
                error=(
                    "With Intelligence is rate-limiting sign-in requests — "
                    + "please try again shortly."
                ),
            )
        except Unreachable as exc:
            # Not recorded as a failed attempt: nothing was learned about the credential, so
            # counting it would let a With Intelligence outage lock users out.
            logger.warning("auth.login.wi_unreachable", exc_info=exc)
            return self._form_response(
                request_id,
                username=username,
                error="With Intelligence is unreachable right now — please try again shortly.",
            )

        # Authenticated, so the guessing budget is irrelevant for this username.
        await clear_failures(self._session_factory, username)

        async with read_session(self._session_factory) as session:
            existing_id = await find_user_id_by_username(session, username)
        logger.info("auth.login.succeeded", extra={"reconnected": existing_id is not None})

        async def save_subject(session: AsyncSession) -> str:
            return await save_session(
                session,
                str(uuid.uuid4()),
                username,
                wi_session,
                self._encryption_key,
            )

        redirect_url = await self.complete_authorization(pending, save_subject)
        if redirect_url is None:
            return self._expired_link_response()

        if existing_id is not None:
            assert self._forget_cached_session is not None
            self._forget_cached_session(existing_id)
        response = RedirectResponse(redirect_url, status_code=302, headers=_LOGIN_SECURITY_HEADERS)
        _LOGIN_CSRF.clear_cookie(
            response, request_id, path=self.login_path, secure=self._secure_cookies
        )
        return response
