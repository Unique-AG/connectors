"""The OAuth flow end to end: authorize, login form, code exchange, refresh, revocation.

With Intelligence sign-in is mocked at the HTTP boundary with respx rather than by patching the
factory, so the login path exercises the real `_auth_call` — including how it reads
`accessToken`/`refreshToken` out of the response.
"""

import asyncio
import uuid
from collections.abc import Callable
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from mcp.server.auth.provider import AuthorizationParams, TokenError
from mcp.shared.auth import OAuthClientInformationFull
from mcp_credential_auth import LoginCsrf
from pydantic import AnyUrl
from sqlalchemy import func, select
from starlette.requests import Request

from tests.conftest import DatabaseFixture
from tests.helpers import BASE_URL, sign_in_ok, wi_factory
from with_intelligence_mcp.db import LoginAttempt, read_session
from with_intelligence_mcp.db import WithIntelligenceSession as SessionRow
from with_intelligence_mcp.features.auth import ThrottleConfig
from with_intelligence_mcp.features.auth.provider import WithIntelligenceOAuthProvider
from with_intelligence_mcp.features.auth.session_store import get_session

_REDIRECT_URI = "https://client.example/callback"
_SIGN_IN = f"{BASE_URL}/v3/auth/sign-in"
_CSRF_TOKEN = "provider-test-csrf-token"
_LOGIN_CSRF = LoginCsrf("wi_login_csrf_")


def _ignore_subject(_subject: str) -> None:
    pass


def _make_provider(
    db: DatabaseFixture,
    *,
    throttle: ThrottleConfig | None = None,
    forget_cached_session: Callable[[str], None] = _ignore_subject,
) -> WithIntelligenceOAuthProvider:
    _, factory = db
    provider = WithIntelligenceOAuthProvider(
        base_url="https://wi-mcp.example",
        secure_cookies=True,
        session_factory=factory,
        encryption_key=Fernet.generate_key(),
        wi_clients=wi_factory(),
        # Effectively off unless a test asks for it, so no test depends on how many failed
        # logins its neighbours happened to make.
        throttle=throttle or ThrottleConfig(max_attempts=1_000_000, window=timedelta(minutes=15)),
    )
    provider.attach_forget_cached_session(forget_cached_session)
    return provider


async def _register_client(
    provider: WithIntelligenceOAuthProvider, client_id: str
) -> OAuthClientInformationFull:
    client_info = OAuthClientInformationFull(
        client_id=client_id,
        redirect_uris=[AnyUrl(_REDIRECT_URI)],
        client_name="Test Client",
    )
    await provider.register_client(client_info)
    return client_info


def _params(*, state: str = "xyz") -> AuthorizationParams:
    return AuthorizationParams(
        state=state,
        scopes=[],
        code_challenge="challenge",
        redirect_uri=AnyUrl(_REDIRECT_URI),
        redirect_uri_provided_explicitly=True,
    )


def _login_post(
    request_id: str,
    username: str,
    password: str,
    *,
    form_csrf_token: str = _CSRF_TOKEN,
    cookie_csrf_token: str | None = _CSRF_TOKEN,
) -> Request:
    """A form POST carrying a matching CSRF cookie/field pair by default.

    Every real submission has both halves — the form is only rendered with the cookie set — so
    the happy path is the default; the overrides exist for the CSRF tests.
    """
    body = (
        f"request_id={request_id}&username={username}"
        f"&password={password}&csrf_token={form_csrf_token}"
    ).encode()
    headers = [(b"content-type", b"application/x-www-form-urlencoded")]
    if cookie_csrf_token is not None:
        headers.append(
            (b"cookie", f"{_LOGIN_CSRF.cookie_name(request_id)}={cookie_csrf_token}".encode())
        )

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({"type": "http", "method": "POST", "headers": headers}, receive)


async def _pending_request_id(provider: WithIntelligenceOAuthProvider, client_id: str) -> str:
    client = await _register_client(provider, client_id)
    url = await provider.authorize(client, _params())
    return parse_qs(urlparse(url).query)["request_id"][0]


def _unique(tag: str) -> str:
    return f"{tag}-{uuid.uuid4().hex[:8]}"


class TestAuthorize:
    async def test_redirects_to_our_own_login_form(self, db: DatabaseFixture) -> None:
        """No third-party identity provider exists to redirect to."""
        provider = _make_provider(db)
        client = await _register_client(provider, _unique("client"))
        url = await provider.authorize(client, _params())
        assert url.startswith("https://wi-mcp.example/login?request_id=")

    async def test_the_form_renders_for_a_pending_request(self, db: DatabaseFixture) -> None:
        provider = _make_provider(db)
        request_id = await _pending_request_id(provider, _unique("client"))
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "query_string": f"request_id={request_id}".encode(),
                "headers": [],
            }
        )
        response = await provider.handle_login_get(request)
        assert response.status_code == 200
        assert b'name="password"' in response.body
        assert b'name="request_id"' in response.body

    async def test_the_form_refuses_an_unknown_request_id(self, db: DatabaseFixture) -> None:
        provider = _make_provider(db)
        request = Request(
            {"type": "http", "method": "GET", "query_string": b"request_id=nope", "headers": []}
        )
        response = await provider.handle_login_get(request)
        assert response.status_code == 400

    async def test_the_form_does_not_leak_the_request_id_via_referrer(
        self, db: DatabaseFixture
    ) -> None:
        provider = _make_provider(db)
        request_id = await _pending_request_id(provider, _unique("client"))
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "query_string": f"request_id={request_id}".encode(),
                "headers": [],
            }
        )
        response = await provider.handle_login_get(request)
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["cache-control"] == "no-store"


class TestLoginSubmission:
    @respx.mock
    async def test_valid_credentials_redirect_with_a_code(self, db: DatabaseFixture) -> None:
        respx.post(_SIGN_IN).mock(return_value=sign_in_ok())
        provider = _make_provider(db)
        request_id = await _pending_request_id(provider, _unique("client"))
        response = await provider.handle_login_post(_login_post(request_id, _unique("user"), "pw"))
        assert response.status_code == 302
        location = response.headers["location"]
        assert "code=" in location
        assert "state=xyz" in location

    @respx.mock
    async def test_reconnect_forgets_the_existing_subject(self, db: DatabaseFixture) -> None:
        respx.post(_SIGN_IN).mock(return_value=sign_in_ok())
        _, factory = db
        forgotten: list[str] = []
        provider = _make_provider(db, forget_cached_session=forgotten.append)
        username = _unique("reconnect")

        first_request = await _pending_request_id(provider, _unique("client"))
        first = await provider.handle_login_post(_login_post(first_request, username, "pw"))
        assert first.status_code == 302
        assert forgotten == []
        async with read_session(factory) as session:
            result = await session.execute(
                select(SessionRow.user_id).where(SessionRow.wi_username == username)
            )
            existing_subject = result.scalar_one()

        second_request = await _pending_request_id(provider, _unique("client"))
        second = await provider.handle_login_post(_login_post(second_request, username, "pw"))
        assert second.status_code == 302
        assert forgotten == [existing_subject]

    @respx.mock
    async def test_the_wi_session_is_stored_and_the_password_is_not(
        self, db: DatabaseFixture
    ) -> None:
        """The password buys a session and is then discarded — only the session is at rest."""
        respx.post(_SIGN_IN).mock(return_value=sign_in_ok())
        provider = _make_provider(db)
        _, factory = db
        username = _unique("stored")
        request_id = await _pending_request_id(provider, _unique("client"))
        _ = await provider.handle_login_post(_login_post(request_id, username, "the-password"))

        async with read_session(factory) as session:
            result = await session.execute(
                select(SessionRow).where(SessionRow.wi_username == username)
            )
            row = result.scalar_one()
            assert b"the-password" not in row.encrypted_blob
            restored = await get_session(session, row.user_id, provider._encryption_key)  # pyright: ignore[reportPrivateUsage]
        assert restored is not None
        assert restored.access_token.get_secret_value() == "access-1"
        assert restored.refresh_token.get_secret_value() == "refresh-1"

    @respx.mock
    async def test_a_refused_sign_in_mints_no_code(self, db: DatabaseFixture) -> None:
        respx.post(_SIGN_IN).mock(return_value=httpx.Response(401))
        provider = _make_provider(db)
        request_id = await _pending_request_id(provider, _unique("client"))
        response = await provider.handle_login_post(_login_post(request_id, _unique("bad"), "pw"))
        assert response.status_code == 200
        assert b"Invalid username or password" in response.body

    @respx.mock
    async def test_a_refused_sign_in_records_a_failed_attempt(self, db: DatabaseFixture) -> None:
        respx.post(_SIGN_IN).mock(return_value=httpx.Response(401))
        provider = _make_provider(db)
        _, factory = db
        username = _unique("recorded")
        request_id = await _pending_request_id(provider, _unique("client"))
        _ = await provider.handle_login_post(_login_post(request_id, username, "pw"))
        async with read_session(factory) as session:
            result = await session.execute(
                select(func.count())
                .select_from(LoginAttempt)
                .where(LoginAttempt.username == username)
            )
            assert result.scalar_one() == 1

    @respx.mock
    async def test_a_wi_outage_does_not_burn_the_budget(
        self, db: DatabaseFixture, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Nothing was learned about the credential, so counting it would lock users out."""
        respx.post(_SIGN_IN).mock(side_effect=httpx.ConnectError("down"))
        provider = _make_provider(db)
        _, factory = db
        username = _unique("outage")
        request_id = await _pending_request_id(provider, _unique("client"))
        response = await provider.handle_login_post(_login_post(request_id, username, "pw"))
        assert b"unreachable" in response.body
        async with read_session(factory) as session:
            result = await session.execute(
                select(func.count())
                .select_from(LoginAttempt)
                .where(LoginAttempt.username == username)
            )
            assert result.scalar_one() == 0
        records = [
            record for record in caplog.records if record.message == "auth.login.wi_unreachable"
        ]
        assert len(records) == 1
        assert records[0].exc_info is not None

    @respx.mock
    async def test_wi_rate_limit_returns_a_controlled_response(
        self, db: DatabaseFixture, caplog: pytest.LogCaptureFixture
    ) -> None:
        respx.post(_SIGN_IN).mock(return_value=httpx.Response(429))
        provider = _make_provider(db)
        _, factory = db
        username = _unique("rate-limited")
        request_id = await _pending_request_id(provider, _unique("client"))
        response = await provider.handle_login_post(_login_post(request_id, username, "pw"))
        assert response.status_code == 429
        assert b"rate-limiting sign-in requests" in response.body
        async with read_session(factory) as session:
            result = await session.execute(
                select(func.count())
                .select_from(LoginAttempt)
                .where(LoginAttempt.username == username)
            )
            assert result.scalar_one() == 0
        records = [
            record for record in caplog.records if record.message == "auth.login.wi_rate_limited"
        ]
        assert len(records) == 1
        assert records[0].exc_info is not None

    @respx.mock
    async def test_missing_fields_are_reported_without_calling_wi(
        self, db: DatabaseFixture
    ) -> None:
        route = respx.post(_SIGN_IN).mock(return_value=sign_in_ok())
        provider = _make_provider(db)
        request_id = await _pending_request_id(provider, _unique("client"))
        response = await provider.handle_login_post(_login_post(request_id, "", ""))
        assert b"required" in response.body
        assert route.call_count == 0


class TestLoginCsrf:
    @respx.mock
    async def test_a_submission_without_the_cookie_never_reaches_wi(
        self, db: DatabaseFixture
    ) -> None:
        route = respx.post(_SIGN_IN).mock(return_value=sign_in_ok())
        provider = _make_provider(db)
        request_id = await _pending_request_id(provider, _unique("client"))
        response = await provider.handle_login_post(
            _login_post(request_id, _unique("nocookie"), "pw", cookie_csrf_token=None)
        )
        assert response.status_code == 400
        assert route.call_count == 0

    @respx.mock
    async def test_a_mismatched_token_is_refused(self, db: DatabaseFixture) -> None:
        route = respx.post(_SIGN_IN).mock(return_value=sign_in_ok())
        provider = _make_provider(db)
        request_id = await _pending_request_id(provider, _unique("client"))
        response = await provider.handle_login_post(
            _login_post(request_id, _unique("mismatch"), "pw", cookie_csrf_token="other")
        )
        assert response.status_code == 400
        assert route.call_count == 0

    async def test_the_rendered_form_sets_the_cookie_it_will_be_checked_against(
        self, db: DatabaseFixture
    ) -> None:
        provider = _make_provider(db)
        request_id = await _pending_request_id(provider, _unique("client"))
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "query_string": f"request_id={request_id}".encode(),
                "headers": [],
            }
        )
        response = await provider.handle_login_get(request)
        cookie = response.headers["set-cookie"]
        assert _LOGIN_CSRF.cookie_name(request_id) in cookie
        assert "HttpOnly" in cookie
        assert "Secure" in cookie
        assert "SameSite=lax" in cookie

    @respx.mock
    async def test_a_refused_submission_re_renders_a_usable_form(self, db: DatabaseFixture) -> None:
        """A user whose cookie expired while the form sat open recovers by submitting again."""
        provider = _make_provider(db)
        request_id = await _pending_request_id(provider, _unique("client"))
        response = await provider.handle_login_post(
            _login_post(request_id, _unique("retry"), "pw", cookie_csrf_token=None)
        )
        assert b'name="csrf_token"' in response.body
        assert _LOGIN_CSRF.cookie_name(request_id) in response.headers["set-cookie"]


class TestLoginThrottling:
    @respx.mock
    async def test_stops_calling_wi_once_the_budget_is_spent(self, db: DatabaseFixture) -> None:
        route = respx.post(_SIGN_IN).mock(return_value=httpx.Response(401))
        provider = _make_provider(
            db, throttle=ThrottleConfig(max_attempts=2, window=timedelta(minutes=15))
        )
        username = _unique("spent")
        for _ in range(2):
            request_id = await _pending_request_id(provider, _unique("client"))
            _ = await provider.handle_login_post(_login_post(request_id, username, "pw"))
        assert route.call_count == 2

        request_id = await _pending_request_id(provider, _unique("client"))
        response = await provider.handle_login_post(_login_post(request_id, username, "pw"))
        assert response.status_code == 429
        assert route.call_count == 2

    @respx.mock
    async def test_a_success_resets_the_budget(self, db: DatabaseFixture) -> None:
        provider = _make_provider(
            db, throttle=ThrottleConfig(max_attempts=2, window=timedelta(minutes=15))
        )
        username = _unique("reset")
        respx.post(_SIGN_IN).mock(return_value=httpx.Response(401))
        request_id = await _pending_request_id(provider, _unique("client"))
        _ = await provider.handle_login_post(_login_post(request_id, username, "pw"))

        respx.post(_SIGN_IN).mock(return_value=sign_in_ok())
        request_id = await _pending_request_id(provider, _unique("client"))
        ok = await provider.handle_login_post(_login_post(request_id, username, "pw"))
        assert ok.status_code == 302

        respx.post(_SIGN_IN).mock(return_value=httpx.Response(401))
        request_id = await _pending_request_id(provider, _unique("client"))
        after = await provider.handle_login_post(_login_post(request_id, username, "pw"))
        assert after.status_code == 200

    @respx.mock
    async def test_an_overlong_username_is_rejected_without_being_stored(
        self, db: DatabaseFixture
    ) -> None:
        """The submitted username reaches a text column, so its length is bounded first."""
        route = respx.post(_SIGN_IN).mock(return_value=sign_in_ok())
        provider = _make_provider(db)
        _, factory = db
        username = "a" * 400
        request_id = await _pending_request_id(provider, _unique("client"))
        response = await provider.handle_login_post(_login_post(request_id, username, "pw"))
        assert response.status_code == 200
        assert route.call_count == 0
        async with read_session(factory) as session:
            result = await session.execute(
                select(func.count())
                .select_from(LoginAttempt)
                .where(LoginAttempt.username == username)
            )
            assert result.scalar_one() == 0


class TestTokenLifecycle:
    async def _login(
        self, provider: WithIntelligenceOAuthProvider, username: str
    ) -> tuple[OAuthClientInformationFull, str]:
        client = await _register_client(provider, _unique("client"))
        url = await provider.authorize(client, _params())
        request_id = parse_qs(urlparse(url).query)["request_id"][0]
        response = await provider.handle_login_post(_login_post(request_id, username, "pw"))
        code = parse_qs(urlparse(response.headers["location"]).query)["code"][0]
        return client, code

    @respx.mock
    async def test_the_subject_is_the_stored_users_id(self, db: DatabaseFixture) -> None:
        """This is what lets a tool call resolve whose WI session to use."""
        respx.post(_SIGN_IN).mock(return_value=sign_in_ok())
        provider = _make_provider(db)
        _, factory = db
        username = _unique("subject")
        client, code = await self._login(provider, username)
        authorization_code = await provider.load_authorization_code(client, code)
        assert authorization_code is not None
        tokens = await provider.exchange_authorization_code(client, authorization_code)
        access = await provider.load_access_token(tokens.access_token)
        assert access is not None
        async with read_session(factory) as session:
            result = await session.execute(
                select(SessionRow.user_id).where(SessionRow.wi_username == username)
            )
            assert access.subject == result.scalar_one()

    @respx.mock
    async def test_a_refresh_rotates_and_detects_reuse(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Replaying a rotated-away refresh token revokes the whole family."""
        respx.post(_SIGN_IN).mock(return_value=sign_in_ok())
        provider = _make_provider(db)
        client, code = await self._login(provider, _unique("rotate"))
        authorization_code = await provider.load_authorization_code(client, code)
        assert authorization_code is not None
        first = await provider.exchange_authorization_code(client, authorization_code)
        assert first.refresh_token is not None

        stale = await provider.load_refresh_token(client, first.refresh_token)
        assert stale is not None
        second = await provider.exchange_refresh_token(client, stale, [])
        assert second.access_token != first.access_token

        monkeypatch.setattr(type(provider), "REFRESH_TOKEN_REUSE_GRACE", timedelta(0))
        replayed = await provider.load_refresh_token(client, first.refresh_token)
        assert replayed is not None
        with pytest.raises(TokenError):
            _ = await provider.exchange_refresh_token(client, replayed, [])
        assert await provider.load_access_token(second.access_token) is None

    @respx.mock
    async def test_concurrent_refresh_never_leaves_two_valid_descendants(
        self, db: DatabaseFixture
    ) -> None:
        respx.post(_SIGN_IN).mock(return_value=sign_in_ok())
        provider = _make_provider(db)
        client, code = await self._login(provider, _unique("concurrent"))
        authorization_code = await provider.load_authorization_code(client, code)
        assert authorization_code is not None
        issued = await provider.exchange_authorization_code(client, authorization_code)
        assert issued.refresh_token is not None

        loaded = await provider.load_refresh_token(client, issued.refresh_token)
        assert loaded is not None
        results = await asyncio.gather(
            provider.exchange_refresh_token(client, loaded, []),
            provider.exchange_refresh_token(client, loaded, []),
            return_exceptions=True,
        )
        succeeded = [r for r in results if not isinstance(r, BaseException)]
        assert len(succeeded) == 1
        assert await provider.load_access_token(succeeded[0].access_token) is not None
