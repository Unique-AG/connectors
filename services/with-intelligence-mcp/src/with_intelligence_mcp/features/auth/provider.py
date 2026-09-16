import logging
import uuid
from datetime import timedelta
from typing import ClassVar, cast

from mcp_credential_auth import (
    MAX_USERNAME_LENGTH,
    CredentialOAuthProvider,
    LoginCsrf,
    LoginThrottleConfig,
    discard_login_attempt,
    finalize_login_failure,
    record_login_success,
    reserve_login_attempt,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StrictStr,
    ValidationError,
    field_validator,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.datastructures import FormData
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from starlette.types import Message

from with_intelligence_mcp.db import read_session
from with_intelligence_mcp.features.auth.login_form import render_login_form
from with_intelligence_mcp.features.auth.session_store import (
    find_subject_by_username,
    upsert_stored_wi_session,
)
from with_intelligence_mcp.with_intelligence_client import (
    AuthenticationRejected,
    RateLimited,
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
_MAX_LOGIN_BODY_BYTES = 16 * 1024
_MAX_LOGIN_FIELD_LENGTH = 1024


class _LoginBodyTooLargeError(ValueError):
    pass


async def _read_login_form(request: Request) -> FormData:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            parsed_content_length = int(content_length)
        except ValueError as exc:
            raise _LoginBodyTooLargeError from exc
        if parsed_content_length > _MAX_LOGIN_BODY_BYTES:
            raise _LoginBodyTooLargeError

    received = 0
    receive = request.receive

    async def limited_receive() -> Message:
        nonlocal received
        message = await receive()
        if message["type"] == "http.request":
            body = cast("object", message.get("body", b""))
            if not isinstance(body, bytes):
                raise _LoginBodyTooLargeError
            received += len(body)
            if received > _MAX_LOGIN_BODY_BYTES:
                raise _LoginBodyTooLargeError
        return message

    limited_request = Request(request.scope, limited_receive)
    return await limited_request.form(
        max_files=0,
        max_fields=8,
        max_part_size=_MAX_LOGIN_BODY_BYTES,
    )


class _LoginSubmission(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    request_id: StrictStr = Field(default="", max_length=128)
    username: StrictStr = Field(default="", max_length=MAX_USERNAME_LENGTH)
    password: StrictStr = Field(default="", max_length=_MAX_LOGIN_FIELD_LENGTH)
    csrf_token: StrictStr = Field(default="", max_length=128)

    @field_validator("username", mode="before")
    @classmethod
    def strip_username(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class WithIntelligenceOAuthProvider(CredentialOAuthProvider):
    """OAuth provider backed by WI authentication."""

    REFRESH_TOKEN_REUSE_GRACE: ClassVar[timedelta] = timedelta(seconds=10)

    _session_factory: async_sessionmaker[AsyncSession]
    _encryption_key: bytes
    _wi_clients: WithIntelligenceClientFactory
    _throttle: LoginThrottleConfig
    login_path: str

    def __init__(
        self,
        *,
        base_url: str,
        secure_cookies: bool,
        session_factory: async_sessionmaker[AsyncSession],
        encryption_key: bytes,
        wi_clients: WithIntelligenceClientFactory,
        throttle: LoginThrottleConfig,
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
        self._secure_cookies: bool = secure_cookies

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
        try:
            form = await _read_login_form(request)
        except _LoginBodyTooLargeError:
            return PlainTextResponse(
                "Login form is too large.", status_code=413, headers=_LOGIN_SECURITY_HEADERS
            )
        try:
            submission = _LoginSubmission.model_validate(form)
        except ValidationError:
            request_id_value = form.get("request_id", "")
            if not isinstance(request_id_value, str):
                return self._expired_link_response()
            pending = await self.load_pending_authorization(request_id_value)
            if pending is None:
                return self._expired_link_response()
            return self._form_response(
                request_id_value,
                status_code=400,
                error="The login form contains invalid values. Please try again.",
            )
        request_id = submission.request_id
        username = submission.username
        password = submission.password
        csrf_token = submission.csrf_token

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

        attempt_id = await reserve_login_attempt(
            self._session_factory,
            username,
            source_ip=_source_ip(request),
            config=self._throttle,
        )
        if attempt_id is None:
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
        except AuthenticationRejected:
            await finalize_login_failure(self._session_factory, attempt_id)
            return self._form_response(
                request_id,
                username=username,
                error="Invalid username or password.",
            )
        except RateLimited as exc:
            await discard_login_attempt(self._session_factory, attempt_id)
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
            await discard_login_attempt(self._session_factory, attempt_id)
            logger.warning("auth.login.wi_unreachable", exc_info=exc)
            return self._form_response(
                request_id,
                username=username,
                error="With Intelligence is unreachable right now — please try again shortly.",
            )

        await record_login_success(self._session_factory, username, attempt_id=attempt_id)

        async with read_session(self._session_factory) as session:
            existing_id = await find_subject_by_username(session, username)
        logger.info("auth.login.succeeded", extra={"reconnected": existing_id is not None})

        async def save_subject(session: AsyncSession) -> str:
            return await upsert_stored_wi_session(
                session,
                str(uuid.uuid4()),
                username,
                wi_session,
                self._encryption_key,
            )

        redirect_url = await self.complete_authorization(pending, save_subject)
        if redirect_url is None:
            return self._expired_link_response()

        response = RedirectResponse(redirect_url, status_code=302, headers=_LOGIN_SECURITY_HEADERS)
        _LOGIN_CSRF.clear_cookie(
            response, request_id, path=self.login_path, secure=self._secure_cookies
        )
        return response
