import asyncio
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    RegistrationError,
    TokenError,
)
from mcp.shared.auth import InvalidRedirectUriError, OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mcp_credential_auth import CredentialOAuthProvider, transaction
from mcp_credential_auth.models import AuthorizationCode as AuthorizationCodeRow
from mcp_credential_auth.models import OAuthClient as OAuthClientRow
from mcp_credential_auth.models import PendingAuthorization

_REDIRECT_URI = "https://claude.ai/api/mcp/auth_callback"


def _provider(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    access_token_ttl: timedelta | None = None,
) -> CredentialOAuthProvider:
    return CredentialOAuthProvider(
        base_url="https://mcp.example",
        session_factory=session_factory,
        login_path="/login",
        access_token_ttl=access_token_ttl,
    )


def _client(client_id: str, redirect_uris: list[str] | None = None) -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id=client_id,
        redirect_uris=[AnyUrl(uri) for uri in redirect_uris or [_REDIRECT_URI]],
        client_name="Test Client",
    )


def _params(*, scopes: list[str] | None = None) -> AuthorizationParams:
    return AuthorizationParams(
        state="state",
        scopes=scopes or ["read"],
        code_challenge="challenge",
        redirect_uri=AnyUrl(_REDIRECT_URI),
        redirect_uri_provided_explicitly=True,
    )


async def _authorization_code(
    provider: CredentialOAuthProvider,
    client: OAuthClientInformationFull,
    *,
    subject: str = "subject",
    scopes: list[str] | None = None,
) -> AuthorizationCode:
    location = await provider.authorize(client, _params(scopes=scopes))
    request_id = parse_qs(urlparse(location).query)["request_id"][0]
    pending = await provider.load_pending_authorization(request_id)
    assert pending is not None

    async def subject_factory(_session: AsyncSession) -> str:
        return subject

    redirect = await provider.complete_authorization(pending, subject_factory)
    assert redirect is not None
    code = parse_qs(urlparse(redirect).query)["code"][0]
    authorization_code = await provider.load_authorization_code(client, code)
    assert authorization_code is not None
    return authorization_code


async def test_client_registration_round_trips(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = _provider(session_factory)
    client = _client("client-registration")

    await provider.register_client(client)

    assert await provider.get_client(client.client_id or "") == client


@pytest.mark.parametrize(
    "redirect_uris",
    [
        ["https://claude.ai/api/mcp/auth_callback"],
        ["http://localhost:3118/callback", "http://127.0.0.1:33418/"],
        [
            "cursor://anysphere.cursor-mcp/oauth/callback",
            "http://localhost:8787/callback",
            "https://www.cursor.com/agents/mcp/oauth/callback",
        ],
    ],
)
async def test_registers_clients_with_allowed_redirect_uris(
    session_factory: async_sessionmaker[AsyncSession], redirect_uris: list[str]
) -> None:
    provider = _provider(session_factory)
    client = _client(f"client-allowed-{len(redirect_uris)}", redirect_uris)

    await provider.register_client(client)

    assert await provider.get_client(client.client_id or "") == client


@pytest.mark.parametrize(
    ("redirect_uri", "description"),
    [
        (
            "https://attacker.example/callback",
            "Redirect URI https://attacker.example/callback has host attacker.example, "
            + "which is not on the allowlist",
        ),
        ("javascript:alert(1)", "Redirect URI javascript:alert(1) uses the javascript: scheme"),
        ("data:text/html,hi", "Redirect URI data:text/html,hi uses the data: scheme"),
        ("file:///etc/passwd", "Redirect URI file:///etc/passwd uses the file: scheme"),
        (
            "https://claude.ai/api/mcp/auth_callback#x",
            "Redirect URI https://claude.ai/api/mcp/auth_callback#x has a fragment",
        ),
    ],
)
async def test_rejects_registration_with_a_disallowed_redirect_uri(
    session_factory: async_sessionmaker[AsyncSession], redirect_uri: str, description: str
) -> None:
    provider = _provider(session_factory)
    client = _client("client-rejected", [_REDIRECT_URI, redirect_uri])

    with pytest.raises(RegistrationError) as raised:
        await provider.register_client(client)

    assert raised.value.error == "invalid_redirect_uri"
    assert raised.value.error_description == description
    assert await provider.get_client("client-rejected") is None


async def test_registration_follows_a_configured_allowlist(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = CredentialOAuthProvider(
        base_url="https://mcp.example",
        session_factory=session_factory,
        login_path="/login",
        allowed_redirect_hosts=["client.example"],
        allowed_redirect_schemes=[],
    )
    allowed = _client("client-configured", ["https://client.example/callback"])

    await provider.register_client(allowed)

    with pytest.raises(RegistrationError):
        await provider.register_client(_client("client-default-host"))


async def test_previously_registered_client_loses_disallowed_redirect_uris(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = _provider(session_factory)
    legacy = _client("client-legacy", ["https://attacker.example/callback", _REDIRECT_URI])
    async with transaction(session_factory) as session:
        session.add(
            OAuthClientRow(
                client_id="client-legacy", client_metadata=legacy.model_dump(mode="json")
            )
        )

    loaded = await provider.get_client("client-legacy")

    assert loaded is not None
    assert loaded.redirect_uris == [AnyUrl(_REDIRECT_URI)]
    with pytest.raises(InvalidRedirectUriError):
        loaded.validate_redirect_uri(AnyUrl("https://attacker.example/callback"))


async def test_previously_registered_client_with_no_allowed_redirect_uri_cannot_authorize(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = _provider(session_factory)
    legacy = _client("client-legacy-only", ["https://attacker.example/callback"])
    async with transaction(session_factory) as session:
        session.add(
            OAuthClientRow(
                client_id="client-legacy-only", client_metadata=legacy.model_dump(mode="json")
            )
        )

    loaded = await provider.get_client("client-legacy-only")

    assert loaded is not None
    assert loaded.redirect_uris is None
    with pytest.raises(InvalidRedirectUriError):
        loaded.validate_redirect_uri(None)


async def test_authorization_completion_is_single_use(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = _provider(session_factory)
    client = _client("client-completion")
    await provider.register_client(client)
    location = await provider.authorize(client, _params())
    request_id = parse_qs(urlparse(location).query)["request_id"][0]
    pending = await provider.load_pending_authorization(request_id)
    assert pending is not None

    async def subject_factory(_session: AsyncSession) -> str:
        return "subject"

    first, second = await asyncio.gather(
        provider.complete_authorization(pending, subject_factory),
        provider.complete_authorization(pending, subject_factory),
    )

    assert len([result for result in (first, second) if result is not None]) == 1


async def test_authorization_completion_rechecks_expiry(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = _provider(session_factory)
    client = _client("client-expired-pending")
    await provider.register_client(client)
    location = await provider.authorize(client, _params())
    request_id = parse_qs(urlparse(location).query)["request_id"][0]
    pending = await provider.load_pending_authorization(request_id)
    assert pending is not None
    async with transaction(session_factory) as session:
        await session.execute(
            update(PendingAuthorization)
            .where(PendingAuthorization.request_id == request_id)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )

    async def subject_factory(_session: AsyncSession) -> str:
        return "subject"

    assert await provider.complete_authorization(pending, subject_factory) is None


async def test_authorization_code_exchange_is_single_use(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = _provider(session_factory)
    client = _client("client-code")
    await provider.register_client(client)
    authorization_code = await _authorization_code(provider, client)

    results = await asyncio.gather(
        provider.exchange_authorization_code(client, authorization_code),
        provider.exchange_authorization_code(client, authorization_code),
        return_exceptions=True,
    )

    assert len([result for result in results if isinstance(result, OAuthToken)]) == 1
    assert len([result for result in results if isinstance(result, TokenError)]) == 1


async def test_authorization_code_exchange_rechecks_expiry(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = _provider(session_factory)
    client = _client("client-expired-code-claim")
    await provider.register_client(client)
    authorization_code = await _authorization_code(provider, client)
    async with transaction(session_factory) as session:
        await session.execute(
            update(AuthorizationCodeRow)
            .where(AuthorizationCodeRow.code == authorization_code.code)
            .values(expires_at=datetime.now(UTC).timestamp() - 1)
        )

    with pytest.raises(TokenError):
        await provider.exchange_authorization_code(client, authorization_code)


async def test_refresh_rotation_detects_reuse(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = _provider(session_factory)
    client = _client("client-refresh")
    await provider.register_client(client)
    authorization_code = await _authorization_code(provider, client)
    tokens = await provider.exchange_authorization_code(client, authorization_code)
    assert tokens.refresh_token is not None
    refresh = await provider.load_refresh_token(client, tokens.refresh_token)
    assert refresh is not None

    rotated = await provider.exchange_refresh_token(client, refresh, [])
    replay = await provider.load_refresh_token(client, tokens.refresh_token)
    assert replay is not None

    with pytest.raises(TokenError) as exc_info:
        await provider.exchange_refresh_token(client, replay, [])

    assert exc_info.value.error_description == "Refresh token has already been used"
    assert await provider.load_access_token(rotated.access_token) is None


async def test_concurrent_refresh_revokes_the_winner_without_grace(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = _provider(session_factory)
    client = _client("client-concurrent-refresh")
    await provider.register_client(client)
    authorization_code = await _authorization_code(provider, client)
    tokens = await provider.exchange_authorization_code(client, authorization_code)
    assert tokens.refresh_token is not None
    refresh = await provider.load_refresh_token(client, tokens.refresh_token)
    assert refresh is not None

    results = await asyncio.gather(
        provider.exchange_refresh_token(client, refresh, []),
        provider.exchange_refresh_token(client, refresh, []),
        return_exceptions=True,
    )

    succeeded = [result for result in results if isinstance(result, OAuthToken)]
    assert len(succeeded) == 1
    assert await provider.load_access_token(succeeded[0].access_token) is None


async def test_refresh_reuse_within_grace_preserves_family(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider(session_factory)
    monkeypatch.setattr(type(provider), "REFRESH_TOKEN_REUSE_GRACE", timedelta(minutes=1))
    client = _client("client-refresh-grace")
    await provider.register_client(client)
    authorization_code = await _authorization_code(provider, client)
    tokens = await provider.exchange_authorization_code(client, authorization_code)
    assert tokens.refresh_token is not None
    refresh = await provider.load_refresh_token(client, tokens.refresh_token)
    assert refresh is not None

    rotated = await provider.exchange_refresh_token(client, refresh, [])
    replay = await provider.load_refresh_token(client, tokens.refresh_token)
    assert replay is not None

    with pytest.raises(TokenError):
        await provider.exchange_refresh_token(client, replay, [])

    assert await provider.load_access_token(rotated.access_token) is not None


async def test_refresh_rejects_scope_escalation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = _provider(session_factory)
    client = _client("client-scope")
    await provider.register_client(client)
    authorization_code = await _authorization_code(provider, client, scopes=["read"])
    tokens = await provider.exchange_authorization_code(client, authorization_code)
    assert tokens.refresh_token is not None
    refresh = await provider.load_refresh_token(client, tokens.refresh_token)
    assert refresh is not None

    with pytest.raises(TokenError) as exc_info:
        await provider.exchange_refresh_token(client, refresh, ["read", "write"])

    assert exc_info.value.error == "invalid_scope"


async def test_revoke_all_tokens_for_subject(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = _provider(session_factory)
    client = _client("client-revoke")
    await provider.register_client(client)
    authorization_code = await _authorization_code(provider, client, subject="owner")
    tokens = await provider.exchange_authorization_code(client, authorization_code)

    await provider.revoke_all_tokens_for_subject("owner")

    assert await provider.load_access_token(tokens.access_token) is None


async def test_expired_authorization_code_is_not_loaded(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider(session_factory)
    client = _client("client-expired-code")
    await provider.register_client(client)
    authorization_code = await _authorization_code(provider, client)
    monkeypatch.setattr(
        "mcp_credential_auth.provider.time.time",
        lambda: authorization_code.expires_at + 1,
    )

    assert await provider.load_authorization_code(client, authorization_code.code) is None


async def test_custom_access_token_ttl(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = _provider(session_factory, access_token_ttl=timedelta(seconds=42))
    client = _client("client-ttl")
    await provider.register_client(client)
    authorization_code = await _authorization_code(provider, client)

    tokens = await provider.exchange_authorization_code(client, authorization_code)

    assert tokens.expires_in == 42
