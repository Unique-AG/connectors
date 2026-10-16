import asyncio

import httpx2

from kyckr_mcp.client import create_client
from kyckr_mcp.settings import Settings


def send(settings: Settings, headers: dict[str, str]) -> httpx2.Request:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={})

    async def run() -> None:
        async with create_client(settings, httpx2.MockTransport(handler)) as client:
            await client.get("/companies", headers=headers)

    asyncio.run(run())
    return seen[0]


def test_the_kyckr_key_is_sent_as_a_bearer_token(settings: Settings) -> None:
    request = send(settings, {})

    assert request.headers["authorization"] == "Bearer test-kyckr-key"
    assert request.url.host == "test-api.kyckr.com"


def test_headers_of_the_mcp_caller_are_not_passed_to_kyckr(settings: Settings) -> None:
    request = send(settings, {"X-Forwarded-For": "203.0.113.9", "Origin": "https://evil.example"})

    assert "x-forwarded-for" not in request.headers
    assert "origin" not in request.headers


def test_the_client_uses_the_configured_timeout(settings: Settings) -> None:
    configured = settings.model_copy(update={"kyckr_timeout_seconds": 7})

    assert create_client(configured).timeout == httpx2.Timeout(7)
