"""The OAuth flow end to end: authorize, login form, code exchange, refresh, revocation.

The vendor sign-in is mocked at the HTTP boundary with respx rather than by patching the
factory, so the login path exercises the real `_auth_call` — including how it reads
`accessToken`/`refreshToken` out of the response.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from mcp.server.auth.provider import AuthorizationParams, TokenError
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl
from sqlalchemy import func, select
from starlette.requests import Request

from tests.conftest import DatabaseFixture
from tests.helpers import BASE_URL, sign_in_ok, vendor_factory
from with_intelligence_mcp.db import LoginAttempt, PendingAuthorization, read_session
from with_intelligence_mcp.db import WithIntelligenceCredential as CredentialRow
from with_intelligence_mcp.features.auth import ThrottleConfig
from with_intelligence_mcp.features.auth.credential_store import get_credential
from with_intelligence_mcp.features.auth.login_csrf import csrf_cookie_name
from with_intelligence_mcp.features.auth.provider import WithIntelligenceOAuthProvider

_REDIRECT_URI = "https://client.example/callback"
_SIGN_IN = f"{BASE_URL}/v3/auth/sign-in"
_CSRF_TOKEN = "provider-test-csrf-token"


def _make_provider(
    db: DatabaseFixture, *, throttle: ThrottleConfig | None = None
) -> WithIntelligenceOAuthProvider:
    _, factory = db
    return WithIntelligenceOAuthProvider(
        base_url="https://wi-mcp.example",
        secure_cookies=True,
        session_factory=factory,
        encryption_key=Fernet.generate_key(),
        vendor_clients=vendor_factory(),
        # Effectively off unless a test asks for it, so no test depends on how many failed
        # logins its neighbours happened to make.
        throttle=throttle or ThrottleConfig(max_attempts=1_000_000, window=timedelta(minutes=15)),
    )


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
        headers.append((b"cookie", f"{csrf_cookie_name(request_id)}={cookie_csrf_token}".encode()))

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({"type": "http", "method": "POST", "headers": headers}, receive)


async def _pending_request_id(provider: WithIntelligenceOAuthProvider, client_id: str) -> str:
    client = await _register_client(provider, client_id)
    url = await provider.authorize(client, _params())
    return parse_qs(urlparse(url).query)["request_id"][0]


def _unique(tag: str) -> str:
    return f"{tag}-{uuid.uuid4().hex[:8]}"


class TestClientRegistration:
    async def test_a_registered_client_reads_back(self, db: DatabaseFixture) -> None:
        provider = _make_provider(db)
        client_id = _unique("client")
        registered = await _register_client(provider, client_id)
        loaded = await provider.get_client(client_id)
        assert loaded is not None
        assert loaded.client_id == registered.client_id

    async def test_an_unknown_client_is_none(self, db: DatabaseFixture) -> None:
        provider = _make_provider(db)
        assert await provider.get_client(_unique("missing")) is None


class TestAuthorize:
    async def test_redirects_to_our_own_login_form(self, db: DatabaseFixture) -> None:
        """No third-party identity provider exists to redirect to."""
        provider = _make_provider(db)
        client = await _register_client(provider, _unique("client"))
        url = await provider.authorize(client, _params())
        assert url.startswith("https://wi-mcp.example/login?request_id=")

    async def test_persists_the_pending_authorization(self, db: DatabaseFixture) -> None:
        provider = _make_provider(db)
        _, factory = db
        request_id = await _pending_request_id(provider, _unique("client"))
        async with read_session(factory) as session:
            pending = await session.get(PendingAuthorization, request_id)
        assert pending is not None
        assert pending.redirect_uri == _REDIRECT_URI

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
    async def test_the_credential_is_stored_encrypted(self, db: DatabaseFixture) -> None:
        respx.post(_SIGN_IN).mock(return_value=sign_in_ok())
        provider = _make_provider(db)
        _, factory = db
        username = _unique("stored")
        request_id = await _pending_request_id(provider, _unique("client"))
        _ = await provider.handle_login_post(_login_post(request_id, username, "the-password"))

        async with read_session(factory) as session:
            result = await session.execute(
                select(CredentialRow).where(CredentialRow.wi_username == username)
            )
            row = result.scalar_one()
            assert b"the-password" not in row.encrypted_blob
            restored = await get_credential(session, row.user_id, provider._encryption_key)  # pyright: ignore[reportPrivateUsage]
        assert restored is not None
        assert restored.password.get_secret_value() == "the-password"

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
    async def test_a_vendor_outage_does_not_burn_the_budget(self, db: DatabaseFixture) -> None:
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

    @respx.mock
    async def test_a_pending_authorization_is_single_use(self, db: DatabaseFixture) -> None:
        respx.post(_SIGN_IN).mock(return_value=sign_in_ok())
        provider = _make_provider(db)
        request_id = await _pending_request_id(provider, _unique("client"))
        username = _unique("once")
        first = await provider.handle_login_post(_login_post(request_id, username, "pw"))
        second = await provider.handle_login_post(_login_post(request_id, username, "pw"))
        assert first.status_code == 302
        assert second.status_code == 400

    @respx.mock
    async def test_concurrent_submissions_mint_one_code(self, db: DatabaseFixture) -> None:
        respx.post(_SIGN_IN).mock(return_value=sign_in_ok())
        provider = _make_provider(db)
        request_id = await _pending_request_id(provider, _unique("client"))
        username = _unique("race")
        responses = await asyncio.gather(
            provider.handle_login_post(_login_post(request_id, username, "pw")),
            provider.handle_login_post(_login_post(request_id, username, "pw")),
        )
        assert sorted(r.status_code for r in responses) == [302, 400]

    @respx.mock
    async def test_missing_fields_are_reported_without_calling_the_vendor(
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
    async def test_a_submission_without_the_cookie_never_reaches_the_vendor(
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
        assert csrf_cookie_name(request_id) in cookie
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
        assert csrf_cookie_name(request_id) in response.headers["set-cookie"]


class TestLoginThrottling:
    @respx.mock
    async def test_stops_calling_the_vendor_once_the_budget_is_spent(
        self, db: DatabaseFixture
    ) -> None:
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
    async def test_a_code_exchanges_for_a_working_token_pair(self, db: DatabaseFixture) -> None:
        respx.post(_SIGN_IN).mock(return_value=sign_in_ok())
        provider = _make_provider(db)
        client, code = await self._login(provider, _unique("exchange"))
        authorization_code = await provider.load_authorization_code(client, code)
        assert authorization_code is not None
        tokens = await provider.exchange_authorization_code(client, authorization_code)
        access = await provider.load_access_token(tokens.access_token)
        assert access is not None
        assert access.subject is not None

    @respx.mock
    async def test_the_subject_is_the_stored_users_id(self, db: DatabaseFixture) -> None:
        """This is what lets a tool call resolve whose credential to use."""
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
                select(CredentialRow.user_id).where(CredentialRow.wi_username == username)
            )
            assert access.subject == result.scalar_one()

    @respx.mock
    async def test_a_code_cannot_be_exchanged_twice(self, db: DatabaseFixture) -> None:
        respx.post(_SIGN_IN).mock(return_value=sign_in_ok())
        provider = _make_provider(db)
        client, code = await self._login(provider, _unique("replay"))
        authorization_code = await provider.load_authorization_code(client, code)
        assert authorization_code is not None
        _ = await provider.exchange_authorization_code(client, authorization_code)
        with pytest.raises(TokenError):
            _ = await provider.exchange_authorization_code(client, authorization_code)

    @respx.mock
    async def test_a_refresh_rotates_and_detects_reuse(self, db: DatabaseFixture) -> None:
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

    @respx.mock
    async def test_revoking_an_access_token_invalidates_it(self, db: DatabaseFixture) -> None:
        respx.post(_SIGN_IN).mock(return_value=sign_in_ok())
        provider = _make_provider(db)
        client, code = await self._login(provider, _unique("revoke"))
        authorization_code = await provider.load_authorization_code(client, code)
        assert authorization_code is not None
        tokens = await provider.exchange_authorization_code(client, authorization_code)
        access = await provider.load_access_token(tokens.access_token)
        assert access is not None
        await provider.revoke_token(access)
        assert await provider.load_access_token(tokens.access_token) is None

    @respx.mock
    async def test_revoking_a_subject_invalidates_every_token(self, db: DatabaseFixture) -> None:
        """What a stored password that stopped working triggers, pushing the user to re-login."""
        respx.post(_SIGN_IN).mock(return_value=sign_in_ok())
        provider = _make_provider(db)
        client, code = await self._login(provider, _unique("subject-revoke"))
        authorization_code = await provider.load_authorization_code(client, code)
        assert authorization_code is not None
        tokens = await provider.exchange_authorization_code(client, authorization_code)
        access = await provider.load_access_token(tokens.access_token)
        assert access is not None and access.subject is not None
        await provider.revoke_all_tokens_for_subject(access.subject)
        assert await provider.load_access_token(tokens.access_token) is None

    @respx.mock
    async def test_an_expired_code_cannot_be_loaded(self, db: DatabaseFixture) -> None:
        respx.post(_SIGN_IN).mock(return_value=sign_in_ok())
        provider = _make_provider(db)
        _, factory = db
        client, code = await self._login(provider, _unique("expired"))
        from with_intelligence_mcp.db import AuthorizationCode as CodeRow
        from with_intelligence_mcp.db import transaction

        async with transaction(factory) as session:
            row = await session.get(CodeRow, code)
            assert row is not None
            row.expires_at = (datetime.now(UTC) - timedelta(minutes=1)).timestamp()
        assert await provider.load_authorization_code(client, code) is None
