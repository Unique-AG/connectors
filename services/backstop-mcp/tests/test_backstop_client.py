import base64

import httpx
import pytest
import respx
from pydantic import SecretStr

from backstop_mcp.auth.crypto import BackstopCredentialSecret
from backstop_mcp.backstop_client import (
    BackstopAuthError,
    BackstopUnreachableError,
    build_auth_headers,
    create_backstop_client,
    verify_credential,
)

_BASE_URL = "https://example.backstopsolutions.com"
_BASIC_AUTH = "Basic " + base64.b64encode(b"bob.smith:p@55W0rd321!").decode()


class TestBuildAuthHeaders:
    def test_builds_basic_auth_and_token_header(self) -> None:
        headers = build_auth_headers("bob.smith", "p@55W0rd321!")

        assert headers == {"authorization": _BASIC_AUTH, "token": "true"}


class TestCreateBackstopClient:
    def test_builds_client_scoped_to_the_credential(self) -> None:
        credential = BackstopCredentialSecret(
            username="bob.smith", api_token=SecretStr("p@55W0rd321!")
        )

        client = create_backstop_client(_BASE_URL, credential)

        assert client.headers["authorization"] == _BASIC_AUTH
        assert client.headers["token"] == "true"
        assert str(client.base_url) == _BASE_URL


class TestBackstopClientAutoRaises:
    """The client `create_backstop_client` returns checks every response automatically —
    tool implementations never need to call `raise_for_status()`/check status codes."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_raises_backstop_auth_error_on_401(self) -> None:
        respx.get(f"{_BASE_URL}/system-info").mock(return_value=httpx.Response(401))
        credential = BackstopCredentialSecret(username="bob.smith", api_token=SecretStr("token"))

        async with create_backstop_client(_BASE_URL, credential) as client:
            with pytest.raises(BackstopAuthError):
                await client.get("/system-info")

    @pytest.mark.asyncio
    @respx.mock
    async def test_raises_http_status_error_on_other_error_statuses(self) -> None:
        respx.get(f"{_BASE_URL}/system-info").mock(return_value=httpx.Response(500))
        credential = BackstopCredentialSecret(username="bob.smith", api_token=SecretStr("token"))

        async with create_backstop_client(_BASE_URL, credential) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await client.get("/system-info")

    @pytest.mark.asyncio
    @respx.mock
    async def test_does_not_raise_on_200(self) -> None:
        respx.get(f"{_BASE_URL}/system-info").mock(return_value=httpx.Response(200, json={}))
        credential = BackstopCredentialSecret(username="bob.smith", api_token=SecretStr("token"))

        async with create_backstop_client(_BASE_URL, credential) as client:
            response = await client.get("/system-info")

        assert response.status_code == 200


class TestVerifyCredential:
    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_true_on_200(self) -> None:
        respx.get(f"{_BASE_URL}/system-info").mock(return_value=httpx.Response(200))

        assert await verify_credential("bob.smith", "token", _BASE_URL) is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_false_on_401(self) -> None:
        respx.get(f"{_BASE_URL}/system-info").mock(return_value=httpx.Response(401))

        assert await verify_credential("bob.smith", "wrong-token", _BASE_URL) is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_false_on_403(self) -> None:
        respx.get(f"{_BASE_URL}/system-info").mock(return_value=httpx.Response(403))

        assert await verify_credential("bob.smith", "wrong-token", _BASE_URL) is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_raises_unreachable_on_5xx(self) -> None:
        respx.get(f"{_BASE_URL}/system-info").mock(return_value=httpx.Response(503))

        with pytest.raises(BackstopUnreachableError):
            await verify_credential("bob.smith", "token", _BASE_URL)

    @pytest.mark.asyncio
    @respx.mock
    async def test_raises_unreachable_on_network_error(self) -> None:
        respx.get(f"{_BASE_URL}/system-info").mock(side_effect=httpx.ConnectError("boom"))

        with pytest.raises(BackstopUnreachableError):
            await verify_credential("bob.smith", "token", _BASE_URL)

    @pytest.mark.asyncio
    @respx.mock
    async def test_sends_basic_auth_and_token_header(self) -> None:
        route = respx.get(f"{_BASE_URL}/system-info").mock(return_value=httpx.Response(200))

        await verify_credential("bob.smith", "p@55W0rd321!", _BASE_URL)

        assert route.called
        sent_request = route.calls.last.request
        assert sent_request.headers["authorization"] == _BASIC_AUTH
        assert sent_request.headers["token"] == "true"
