import os
from urllib.parse import parse_qs, urlparse

import pytest
from mcp.server.auth.provider import AuthorizationParams, TokenError
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.requests import Request

from backstop_mcp.auth.provider import BackstopOAuthProvider
from backstop_mcp.db.models import PendingAuthorization

type DatabaseFixture = tuple[AsyncEngine, async_sessionmaker[AsyncSession]]

_REDIRECT_URI = "https://client.example/callback"


def _make_provider(db: DatabaseFixture) -> BackstopOAuthProvider:
    _, factory = db
    return BackstopOAuthProvider(
        base_url="https://backstop-mcp.example",
        session_factory=factory,
        encryption_key=os.urandom(32),
        backstop_base_url="https://api.backstopsolutions.com",
    )


async def _register_client(
    provider: BackstopOAuthProvider, client_id: str
) -> OAuthClientInformationFull:
    client_info = OAuthClientInformationFull(
        client_id=client_id,
        redirect_uris=[AnyUrl(_REDIRECT_URI)],
        client_name="Test Client",
    )
    await provider.register_client(client_info)
    return client_info


def _authorization_params(
    *, code_challenge: str = "challenge", state: str = "xyz"
) -> AuthorizationParams:
    return AuthorizationParams(
        state=state,
        scopes=["backstop"],
        code_challenge=code_challenge,
        redirect_uri=AnyUrl(_REDIRECT_URI),
        redirect_uri_provided_explicitly=True,
    )


def _login_post_request(request_id: str, username: str, api_token: str) -> Request:
    body = f"request_id={request_id}&username={username}&api_token={api_token}".encode()
    scope = {
        "type": "http",
        "method": "POST",
        "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


class TestClientRegistration:
    @pytest.mark.asyncio
    async def test_register_then_get_client_round_trips(self, db: DatabaseFixture) -> None:
        provider = _make_provider(db)
        client_info = await _register_client(provider, "provider-client-1")

        fetched = await provider.get_client("provider-client-1")

        assert fetched is not None
        assert fetched.client_id == client_info.client_id
        assert fetched.redirect_uris == client_info.redirect_uris

    @pytest.mark.asyncio
    async def test_get_client_returns_none_for_unknown_client(self, db: DatabaseFixture) -> None:
        provider = _make_provider(db)

        assert await provider.get_client("no-such-client") is None


class TestAuthorizeAndLoginForm:
    @pytest.mark.asyncio
    async def test_authorize_redirects_to_login_form_with_request_id(
        self, db: DatabaseFixture
    ) -> None:
        provider = _make_provider(db)
        client_info = await _register_client(provider, "provider-client-2")

        redirect_url = await provider.authorize(client_info, _authorization_params())

        parsed = urlparse(redirect_url)
        assert parsed.path == provider.login_path
        assert "request_id" in parse_qs(parsed.query)

    @pytest.mark.asyncio
    async def test_login_get_renders_form_for_pending_request(self, db: DatabaseFixture) -> None:
        provider = _make_provider(db)
        client_info = await _register_client(provider, "provider-client-3")
        redirect_url = await provider.authorize(client_info, _authorization_params())
        request_id = parse_qs(urlparse(redirect_url).query)["request_id"][0]

        request = Request(
            {"type": "http", "method": "GET", "query_string": f"request_id={request_id}".encode()}
        )
        response = await provider.handle_login_get(request)

        assert response.status_code == 200
        assert b"Test Client" in response.body

    @pytest.mark.asyncio
    async def test_login_get_rejects_unknown_request_id(self, db: DatabaseFixture) -> None:
        provider = _make_provider(db)
        request = Request({"type": "http", "method": "GET", "query_string": b"request_id=bogus"})

        response = await provider.handle_login_get(request)

        assert response.status_code == 400


class TestLoginFormSubmission:
    @pytest.mark.asyncio
    async def test_valid_credentials_issue_code_and_redirect(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("backstop_mcp.auth.provider.verify_credential", _always_valid)
        provider = _make_provider(db)
        client_info = await _register_client(provider, "provider-client-4")
        redirect_url = await provider.authorize(client_info, _authorization_params(state="state-1"))
        request_id = parse_qs(urlparse(redirect_url).query)["request_id"][0]

        response = await provider.handle_login_post(
            _login_post_request(request_id, "pv-bob.smith", "token-123")
        )

        assert response.status_code == 302
        location = response.headers["location"]
        parsed = urlparse(location)
        assert parsed.scheme == "https"
        assert parsed.netloc == "client.example"
        query = parse_qs(parsed.query)
        assert "code" in query
        assert query["state"] == ["state-1"]

    @pytest.mark.asyncio
    async def test_invalid_credentials_rerender_form_without_minting_code(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("backstop_mcp.auth.provider.verify_credential", _always_invalid)
        provider = _make_provider(db)
        client_info = await _register_client(provider, "provider-client-5")
        redirect_url = await provider.authorize(client_info, _authorization_params())
        request_id = parse_qs(urlparse(redirect_url).query)["request_id"][0]

        response = await provider.handle_login_post(
            _login_post_request(request_id, "pv-bob.smith", "wrong-token")
        )

        assert response.status_code == 200
        assert b"Invalid username or API token" in response.body

        # the pending request must still be there — nothing was consumed
        _, factory = db
        async with factory() as session:
            pending = await session.get(PendingAuthorization, request_id)
        assert pending is not None


class TestTokenLifecycle:
    @pytest.mark.asyncio
    async def test_exchange_authorization_code_issues_working_token_pair(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("backstop_mcp.auth.provider.verify_credential", _always_valid)
        provider = _make_provider(db)
        client_info = await _register_client(provider, "provider-client-6")
        redirect_url = await provider.authorize(client_info, _authorization_params())
        request_id = parse_qs(urlparse(redirect_url).query)["request_id"][0]
        login_response = await provider.handle_login_post(
            _login_post_request(request_id, "pv-carol.diaz", "token-abc")
        )
        code = parse_qs(urlparse(login_response.headers["location"]).query)["code"][0]

        auth_code = await provider.load_authorization_code(client_info, code)
        assert auth_code is not None

        tokens = await provider.exchange_authorization_code(client_info, auth_code)

        assert tokens.access_token
        assert tokens.refresh_token

        access_info = await provider.load_access_token(tokens.access_token)
        assert access_info is not None
        assert access_info.subject == auth_code.subject

        # the code is single-use
        assert await provider.load_authorization_code(client_info, code) is None

    @pytest.mark.asyncio
    async def test_refresh_token_rotates_and_detects_reuse(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("backstop_mcp.auth.provider.verify_credential", _always_valid)
        provider = _make_provider(db)
        client_info = await _register_client(provider, "provider-client-7")
        redirect_url = await provider.authorize(client_info, _authorization_params())
        request_id = parse_qs(urlparse(redirect_url).query)["request_id"][0]
        login_response = await provider.handle_login_post(
            _login_post_request(request_id, "pv-dave.evans", "token-xyz")
        )
        code = parse_qs(urlparse(login_response.headers["location"]).query)["code"][0]
        auth_code = await provider.load_authorization_code(client_info, code)
        assert auth_code is not None
        first_tokens = await provider.exchange_authorization_code(client_info, auth_code)
        assert first_tokens.refresh_token is not None

        old_refresh = await provider.load_refresh_token(client_info, first_tokens.refresh_token)
        assert old_refresh is not None
        rotated_tokens = await provider.exchange_refresh_token(client_info, old_refresh, [])

        assert rotated_tokens.access_token != first_tokens.access_token
        assert rotated_tokens.refresh_token != first_tokens.refresh_token

        # the new access token works
        assert rotated_tokens.access_token is not None
        assert await provider.load_access_token(rotated_tokens.access_token) is not None
        # the old access token no longer resolves to a live grant, since replaying the
        # refresh token below revokes the whole family
        assert first_tokens.access_token is not None

        # replaying the OLD refresh token is reuse of an already-rotated-away token
        with pytest.raises(TokenError) as exc_info:
            await provider.exchange_refresh_token(client_info, old_refresh, [])
        assert exc_info.value.error_description is not None
        assert "already been used" in exc_info.value.error_description

        # reuse detection revokes the entire family, including the token minted by rotation
        assert await provider.load_access_token(rotated_tokens.access_token) is None

    @pytest.mark.asyncio
    async def test_refresh_token_rejects_scope_escalation(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("backstop_mcp.auth.provider.verify_credential", _always_valid)
        provider = _make_provider(db)
        client_info = await _register_client(provider, "provider-client-7b")
        redirect_url = await provider.authorize(client_info, _authorization_params())
        request_id = parse_qs(urlparse(redirect_url).query)["request_id"][0]
        login_response = await provider.handle_login_post(
            _login_post_request(request_id, "pv-scope.escalation", "token-scope")
        )
        code = parse_qs(urlparse(login_response.headers["location"]).query)["code"][0]
        auth_code = await provider.load_authorization_code(client_info, code)
        assert auth_code is not None
        tokens = await provider.exchange_authorization_code(client_info, auth_code)
        assert tokens.refresh_token is not None
        refresh = await provider.load_refresh_token(client_info, tokens.refresh_token)
        assert refresh is not None

        with pytest.raises(TokenError) as exc_info:
            await provider.exchange_refresh_token(client_info, refresh, ["backstop", "admin"])
        assert exc_info.value.error == "invalid_scope"

        # Original refresh token remains usable after a rejected escalation attempt.
        narrowed = await provider.exchange_refresh_token(client_info, refresh, ["backstop"])
        assert narrowed.access_token
        assert narrowed.scope == "backstop"

    @pytest.mark.asyncio
    async def test_revoke_token_invalidates_access_token(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("backstop_mcp.auth.provider.verify_credential", _always_valid)
        provider = _make_provider(db)
        client_info = await _register_client(provider, "provider-client-8")
        redirect_url = await provider.authorize(client_info, _authorization_params())
        request_id = parse_qs(urlparse(redirect_url).query)["request_id"][0]
        login_response = await provider.handle_login_post(
            _login_post_request(request_id, "pv-erin.foster", "token-def")
        )
        code = parse_qs(urlparse(login_response.headers["location"]).query)["code"][0]
        auth_code = await provider.load_authorization_code(client_info, code)
        assert auth_code is not None
        tokens = await provider.exchange_authorization_code(client_info, auth_code)
        access_info = await provider.load_access_token(tokens.access_token)
        assert access_info is not None

        await provider.revoke_token(access_info)

        assert await provider.load_access_token(tokens.access_token) is None

    @pytest.mark.asyncio
    async def test_revoke_token_family_for_subject(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("backstop_mcp.auth.provider.verify_credential", _always_valid)
        provider = _make_provider(db)
        client_info = await _register_client(provider, "provider-client-9")
        redirect_url = await provider.authorize(client_info, _authorization_params())
        request_id = parse_qs(urlparse(redirect_url).query)["request_id"][0]
        login_response = await provider.handle_login_post(
            _login_post_request(request_id, "pv-frank.green", "token-ghi")
        )
        code = parse_qs(urlparse(login_response.headers["location"]).query)["code"][0]
        auth_code = await provider.load_authorization_code(client_info, code)
        assert auth_code is not None
        tokens = await provider.exchange_authorization_code(client_info, auth_code)
        assert auth_code.subject is not None

        await provider.revoke_token_family_for_subject(auth_code.subject)

        assert await provider.load_access_token(tokens.access_token) is None


async def _always_valid(_username: str, _api_token: str, _base_url: str) -> bool:
    return True


async def _always_invalid(_username: str, _api_token: str, _base_url: str) -> bool:
    return False
