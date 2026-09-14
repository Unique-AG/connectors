import logging
import uuid
from collections.abc import Awaitable, Callable

from mcp_credential_auth import (
    MAX_USERNAME_LENGTH,
    CredentialOAuthProvider,
    ThrottleConfig,
    clear_failures,
    is_throttled,
    record_failure,
)
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response

from backstop_mcp.backstop_client import (
    BackstopClientFactory,
    BackstopCredentialSecret,
    BackstopUnreachableError,
)
from backstop_mcp.db import read_session
from backstop_mcp.features.auth.credential_store import (
    find_user_id_by_username,
    get_credential,
    save_credential,
)
from backstop_mcp.features.auth.crypto import InvalidCredentialEnvelopeError
from backstop_mcp.features.auth.login_csrf import (
    clear_csrf_cookie,
    csrf_token_is_valid,
    issue_csrf_token,
    set_csrf_cookie,
)
from backstop_mcp.features.auth.login_form import render_login_form

logger = logging.getLogger(__name__)

type ResolveSystemUser = Callable[[str, str], Awaitable[tuple[str, dict[str, object]] | None]]


def _source_ip(request: Request) -> str | None:
    """The peer address, recorded on a failed attempt for diagnosis only.

    Behind an ingress this is the ingress's address, which is exactly why the shared throttle
    does not rate-limit on it. `X-Forwarded-For` is deliberately ignored: it's client-supplied,
    so treating it as an identity would record whatever an attacker chose to send.
    """
    return request.client.host if request.client is not None else None


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


class BackstopOAuthProvider(CredentialOAuthProvider):
    """FastMCP OAuth 2.1 authorization server whose "login" step is a Backstop credential form.

    Backstop itself has no OAuth — so instead of redirecting to a third-party identity
    provider, `authorize()` redirects the browser to our own hosted login page
    (`handle_login_get`/`handle_login_post`), which collects a Backstop username + personal
    API token, verifies it against Backstop, and only then mints an authorization code.
    """

    _encryption_key: bytes
    _backstop_clients: BackstopClientFactory
    _resolve_system_user: ResolveSystemUser | None
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
        resolve_system_user: ResolveSystemUser | None = None,
        login_path: str = "/backstop/login",
    ) -> None:
        super().__init__(
            base_url=base_url,
            session_factory=session_factory,
            login_path=login_path,
        )
        self._encryption_key = encryption_key
        # Credential verification goes through the shared factory so the login form reuses the
        # same connection pool, base URL and timeout profile as every tool call.
        self._backstop_clients = backstop_clients
        self._resolve_system_user = resolve_system_user
        self._throttle = throttle
        # Drives the CSRF cookie's `Secure` flag. Passed in rather than re-parsed here so the
        # public URL is parsed exactly once, in `AppConfig`. A local http:// development deploy
        # still gets a working form; every real deploy (https, enforced for production by
        # `AppConfig`) gets the flag.
        self._secure_cookies: bool = secure_cookies

    def attach_resolve_system_user(self, resolve: ResolveSystemUser) -> None:
        if self._resolve_system_user is not None:
            return
        self._resolve_system_user = resolve

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
        api_token = str(form.get("api_token", ""))
        csrf_token = str(form.get("csrf_token", ""))

        pending = await self.load_pending_authorization(request_id)
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

        assert self._resolve_system_user is not None, (
            "resolve_system_user must be provided or attached before login"
        )
        try:
            system_user = await self._resolve_system_user(username, api_token)
        except BackstopUnreachableError as exc:
            logger.warning("auth.login.backstop_unreachable", extra={"error": str(exc)})
            return self._form_response(
                request_id,
                username=username,
                error="Backstop is unreachable right now — please try again shortly.",
            )

        if system_user is None:
            return self._form_response(
                request_id,
                username=username,
                error=(
                    "This Backstop login has no matching system user, so it cannot be "
                    + "used to author activities."
                ),
            )
        external_user_id, system_user_raw = system_user

        # Authenticated, so the guessing budget is irrelevant for this username.
        await clear_failures(self._session_factory, username)

        existing_id: str | None
        previous: BackstopCredentialSecret | None = None
        async with read_session(self._session_factory) as session:
            existing_id = await find_user_id_by_username(session, username)
            if existing_id is not None:
                try:
                    previous = await get_credential(session, existing_id, self._encryption_key)
                except InvalidCredentialEnvelopeError:
                    previous = None
        had_previous_credential = existing_id is not None
        credential_changed = (
            had_previous_credential
            if previous is None
            else previous.api_token.get_secret_value() != api_token
        )
        logger.info(
            "auth.login.succeeded",
            extra={
                "had_previous_credential": had_previous_credential,
                "credential_changed": credential_changed,
            },
        )

        async def save_subject(session: AsyncSession) -> str:
            return await save_credential(
                session,
                str(uuid.uuid4()),
                BackstopCredentialSecret(username=username, api_token=SecretStr(api_token)),
                self._encryption_key,
                external_user_id=external_user_id,
                raw=system_user_raw,
            )

        redirect_url = await self.complete_authorization(pending, save_subject)
        if redirect_url is None:
            return self._expired_link_response()

        response = RedirectResponse(redirect_url, status_code=302, headers=_LOGIN_SECURITY_HEADERS)
        # The pending authorization is gone, so its CSRF cookie has nothing left to protect.
        clear_csrf_cookie(response, request_id, path=self.login_path, secure=self._secure_cookies)
        return response
