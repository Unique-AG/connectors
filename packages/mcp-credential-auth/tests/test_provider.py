import asyncio
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from mcp.server.auth.provider import AuthorizationCode, AuthorizationParams, TokenError
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mcp_credential_auth import CredentialOAuthProvider

_REDIRECT_URI = "https://client.example/callback"


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


def _client(client_id: str) -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id=client_id,
        redirect_uris=[AnyUrl(_REDIRECT_URI)],
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


async def test_custom_access_token_ttl(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = _provider(session_factory, access_token_ttl=timedelta(seconds=42))
    client = _client("client-ttl")
    await provider.register_client(client)
    authorization_code = await _authorization_code(provider, client)

    tokens = await provider.exchange_authorization_code(client, authorization_code)

    assert tokens.expires_in == 42
