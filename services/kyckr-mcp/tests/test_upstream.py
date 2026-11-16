import httpx2
from pydantic import ValidationError
import pytest

from kyckr_mcp.upstream import upstream_http
from kyckr_mcp.upstream import UpstreamSettings


async def send(
    settings: UpstreamSettings, url: str = "/companies", headers: dict[str, str] | None = None
) -> httpx2.Request:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json={})

    async with upstream_http(settings, httpx2.MockTransport(handler)) as client:
        await client.get(url, headers=headers)
    return seen[0]


async def test_the_kyckr_key_is_sent_as_a_bearer_token(upstream_settings: UpstreamSettings) -> None:
    request = await send(upstream_settings)

    assert request.headers["authorization"] == "Bearer dummy-api-key"
    assert request.url.host == "test-api.kyckr.com"


async def test_the_kyckr_key_is_not_sent_to_another_origin(
    upstream_settings: UpstreamSettings,
) -> None:
    request = await send(upstream_settings, "https://elsewhere.example.com/companies")

    assert "authorization" not in request.headers


async def test_headers_of_the_mcp_caller_are_not_passed_to_kyckr(
    upstream_settings: UpstreamSettings,
) -> None:
    caller = {
        "Authorization": "Bearer caller-token",
        "X-Forwarded-For": "203.0.113.9",
        "Origin": "https://evil.example.com",
    }

    request = await send(upstream_settings, headers=caller)

    assert "x-forwarded-for" not in request.headers
    assert "origin" not in request.headers
    assert request.headers["authorization"] == "Bearer dummy-api-key"


async def test_the_configured_timeout_is_the_clients_timeout(
    upstream_settings: UpstreamSettings,
) -> None:
    settings = upstream_settings.model_copy(update={"timeout_seconds": 7})

    async with upstream_http(settings) as client:
        assert client.timeout == httpx2.Timeout(7)


@pytest.mark.parametrize(("field", "value"), [("api_key", ""), ("default_contact_email", "ops@")])
def test_a_setting_that_is_empty_or_malformed_is_rejected_at_startup(
    upstream_settings: UpstreamSettings, field: str, value: str
) -> None:
    fields = {**upstream_settings.model_dump(), field: value}

    with pytest.raises(ValidationError):
        UpstreamSettings.model_validate(fields)
