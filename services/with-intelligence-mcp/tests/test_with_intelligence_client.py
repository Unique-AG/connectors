"""The transport: status mapping, the one token renewal, retries, and paging."""

import httpx
import pytest
import respx
from pydantic import BaseModel, TypeAdapter

from tests.helpers import (
    BASE_URL,
    FakeSession,
    build_client,
    page_body,
    sent_header,
    sent_query,
    sign_in_ok,
    wi_factory,
)
from with_intelligence_mcp.with_intelligence_client import (
    ApiError,
    AuthError,
    NotEntitled,
    NotFound,
    Page,
    RateLimited,
    SignInFailed,
    Unreachable,
    WiCredential,
)

_JSON = TypeAdapter(object)
_PAGE = TypeAdapter(Page[dict[str, object]])


class _TypedResponse(BaseModel):
    ok: bool


_TYPED_RESPONSE = TypeAdapter(_TypedResponse)


class _PageResult(BaseModel):
    id: int


_TYPED_PAGE = TypeAdapter(Page[_PageResult])


class _RecordingMetric:
    def __init__(self) -> None:
        self.records: list[tuple[int, dict[str, bool]]] = []

    def add(self, value: int, attributes: dict[str, bool]) -> None:
        self.records.append((value, attributes))


class _RecordingHistogram:
    def __init__(self) -> None:
        self.attributes: list[dict[str, str]] = []

    def record(self, _value: float, attributes: dict[str, str]) -> None:
        self.attributes.append(attributes)


class _RecordingCounter:
    def __init__(self) -> None:
        self.records: list[tuple[int, dict[str, str]]] = []

    def add(self, value: int, attributes: dict[str, str]) -> None:
        self.records.append((value, attributes))


class TestAuthentication:
    @respx.mock
    async def test_sign_in_deserializes_the_session(self) -> None:
        respx.post(f"{BASE_URL}/v3/auth/sign-in").mock(return_value=sign_in_ok())
        factory = wi_factory()
        credential = WiCredential.model_validate({"username": "user", "password": "password"})
        try:
            session = await factory.sign_in(credential)
        finally:
            await factory.aclose()
        assert session.access_token.get_secret_value() == "access-1"
        assert session.refresh_token.get_secret_value() == "refresh-1"

    @pytest.mark.parametrize(
        "body",
        [{}, {"accessToken": 1, "refreshToken": True}, []],
    )
    @respx.mock
    async def test_invalid_auth_responses_are_rejected(self, body: object) -> None:
        respx.post(f"{BASE_URL}/v3/auth/sign-in").mock(return_value=httpx.Response(200, json=body))
        factory = wi_factory()
        credential = WiCredential.model_validate({"username": "user", "password": "password"})
        try:
            with pytest.raises(SignInFailed):
                await factory.sign_in(credential)
        finally:
            await factory.aclose()

    @pytest.mark.parametrize(
        ("status_code", "error_type"),
        [(429, RateLimited), (503, Unreachable)],
    )
    @respx.mock
    async def test_transient_failures_are_not_retried(
        self, status_code: int, error_type: type[Exception]
    ) -> None:
        route = respx.post(f"{BASE_URL}/v3/auth/sign-in").mock(
            return_value=httpx.Response(status_code)
        )
        factory = wi_factory(max_attempts=2)
        credential = WiCredential.model_validate({"username": "user", "password": "password"})
        try:
            with pytest.raises(error_type):
                await factory.sign_in(credential)
        finally:
            await factory.aclose()
        assert route.call_count == 1

    @respx.mock
    async def test_credential_rejection_is_not_retried(self) -> None:
        route = respx.post(f"{BASE_URL}/v3/auth/sign-in").mock(return_value=httpx.Response(401))
        factory = wi_factory(max_attempts=3)
        credential = WiCredential.model_validate({"username": "user", "password": "wrong"})
        try:
            with pytest.raises(SignInFailed):
                await factory.sign_in(credential)
        finally:
            await factory.aclose()
        assert route.call_count == 1


class TestStatusMapping:
    @respx.mock
    async def test_403_preserves_the_error_context(self) -> None:
        respx.get(f"{BASE_URL}/v3/intentions").mock(
            return_value=httpx.Response(
                403,
                json={
                    "message": "Subscription required",
                    "error": "Forbidden",
                    "statusCode": 403,
                },
            )
        )
        client, _ = build_client()
        with pytest.raises(NotEntitled) as caught:
            await client.get_json("/v3/intentions", _JSON)
        assert caught.value.path == "/v3/intentions"
        assert "licensed" in str(caught.value)
        assert "Forbidden: Subscription required" in str(caught.value)

    @respx.mock
    async def test_404_is_not_found(self) -> None:
        respx.get(f"{BASE_URL}/v3/investors/1").mock(return_value=httpx.Response(404))
        client, _ = build_client()
        with pytest.raises(NotFound):
            await client.get_json("/v3/investors/1", _JSON)

    @respx.mock
    async def test_400_is_a_plain_api_error_and_is_not_retried(self) -> None:
        route = respx.get(f"{BASE_URL}/v3/investors").mock(return_value=httpx.Response(400))
        client, _ = build_client()
        with pytest.raises(ApiError):
            await client.get_json("/v3/investors", _JSON)
        assert route.call_count == 1

    @respx.mock
    async def test_500_is_unreachable_not_refused(self) -> None:
        respx.get(f"{BASE_URL}/v3/investors").mock(return_value=httpx.Response(500))
        client, _ = build_client(max_attempts=1)
        with pytest.raises(Unreachable):
            await client.get_json("/v3/investors", _JSON)

    @respx.mock
    async def test_a_network_failure_is_unreachable(self) -> None:
        respx.get(f"{BASE_URL}/v3/investors").mock(side_effect=httpx.ConnectError("nope"))
        client, _ = build_client(max_attempts=1)
        with pytest.raises(Unreachable):
            await client.get_json("/v3/investors", _JSON)


class TestTokenRenewal:
    @respx.mock
    async def test_a_401_renews_once_and_retries(self) -> None:
        route = respx.get(f"{BASE_URL}/v3/investors").mock(
            side_effect=[httpx.Response(401), httpx.Response(200, json={"ok": True})]
        )
        client, session = build_client()
        response = await client.get_json("/v3/investors", _TYPED_RESPONSE)
        assert response == _TypedResponse(ok=True)
        assert session.renewals == 1
        assert route.call_count == 2

    @respx.mock
    async def test_the_retry_carries_the_new_token(self) -> None:
        route = respx.get(f"{BASE_URL}/v3/investors").mock(
            side_effect=[httpx.Response(401), httpx.Response(200, json={})]
        )
        client, _ = build_client(FakeSession("stale"))
        _ = await client.get_json("/v3/investors", _JSON)
        assert sent_header(route, "authorization", 0) == "Bearer stale"
        assert sent_header(route, "authorization", 1) == "Bearer token-2"

    @respx.mock
    async def test_a_second_401_is_a_real_rejection(self) -> None:
        """Renewing forever would hide a revoked account behind an infinite loop."""
        route = respx.get(f"{BASE_URL}/v3/investors").mock(return_value=httpx.Response(401))
        client, session = build_client()
        with pytest.raises(AuthError):
            await client.get_json("/v3/investors", _JSON)
        assert session.renewals == 1
        assert route.call_count == 2


class TestRetries:
    @respx.mock
    async def test_request_metrics_sanitize_ids(self, monkeypatch: pytest.MonkeyPatch) -> None:
        duration_metric = _RecordingHistogram()
        request_metric = _RecordingCounter()
        monkeypatch.setattr(
            "with_intelligence_mcp.with_intelligence_client.client.UPSTREAM_REQUEST_DURATION",
            duration_metric,
        )
        monkeypatch.setattr(
            "with_intelligence_mcp.with_intelligence_client.client.UPSTREAM_REQUESTS",
            request_metric,
        )
        respx.get(f"{BASE_URL}/v3/investors/123").mock(return_value=httpx.Response(200, json={}))
        client, _ = build_client()
        _ = await client.get_json("/v3/investors/123", _JSON)
        assert duration_metric.attributes == [{"method": "GET", "path": "/v3/investors/:id"}]
        assert request_metric.records == [
            (
                1,
                {"method": "GET", "outcome": "200", "path": "/v3/investors/:id"},
            )
        ]

    @respx.mock
    async def test_rate_limit_metric_has_no_path_attribute(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        metric = _RecordingMetric()
        monkeypatch.setattr(
            "with_intelligence_mcp.with_intelligence_client.client.UPSTREAM_RATE_LIMITED",
            metric,
        )
        respx.get(f"{BASE_URL}/v3/investors/123").mock(return_value=httpx.Response(429))
        client, _ = build_client(max_attempts=1)
        with pytest.raises(RateLimited):
            await client.get_json("/v3/investors/123", _JSON)
        assert metric.records == [(1, {"retried": False})]

    @respx.mock
    async def test_a_429_is_retried(self, monkeypatch: pytest.MonkeyPatch) -> None:
        metric = _RecordingMetric()
        monkeypatch.setattr(
            "with_intelligence_mcp.with_intelligence_client.client.UPSTREAM_RATE_LIMITED",
            metric,
        )
        route = respx.get(f"{BASE_URL}/v3/investors").mock(
            side_effect=[httpx.Response(429), httpx.Response(200, json={"ok": 1})]
        )
        client, _ = build_client()
        assert await client.get_json("/v3/investors", _JSON) == {"ok": 1}
        assert route.call_count == 2
        assert metric.records == [(1, {"retried": True})]

    @respx.mock
    async def test_the_retry_budget_is_finite(self) -> None:
        route = respx.get(f"{BASE_URL}/v3/investors").mock(return_value=httpx.Response(429))
        client, _ = build_client(max_attempts=2)
        with pytest.raises(RateLimited):
            await client.get_json("/v3/investors", _JSON)
        assert route.call_count == 2


class TestQueryEncoding:
    @respx.mock
    async def test_a_boolean_filter_uses_lowercase(self) -> None:
        route = respx.get(f"{BASE_URL}/v3/investors").mock(
            return_value=httpx.Response(200, json=page_body([], total=0))
        )
        client, _ = build_client()
        _ = await client.get_page("/v3/investors", _PAGE, {"active": True})
        assert "active=true" in sent_query(route)

    @respx.mock
    async def test_a_list_filter_repeats_its_key(self) -> None:
        route = respx.get(f"{BASE_URL}/v3/investors").mock(
            return_value=httpx.Response(200, json=page_body([], total=0))
        )
        client, _ = build_client()
        _ = await client.get_page("/v3/investors", _PAGE, {"id": [1, 2], "name": ["Acme"]})
        query = sent_query(route)
        assert "id=1&id=2" in query
        assert "name=Acme" in query

    @respx.mock
    async def test_page_size_defaults_from_settings(self) -> None:
        route = respx.get(f"{BASE_URL}/v3/investors").mock(
            return_value=httpx.Response(200, json=page_body([], total=0))
        )
        client, _ = build_client()
        _ = await client.get_page("/v3/investors", _PAGE)
        assert "page_size=50" in sent_query(route)


class TestPaging:
    @respx.mock
    async def test_iterate_walks_until_the_total_is_covered(self) -> None:
        respx.get(f"{BASE_URL}/v3/investors", params={"page": "1"}).mock(
            return_value=httpx.Response(
                200, json=page_body([{"id": 1}, {"id": 2}], total=3, page=1, size=2)
            )
        )
        respx.get(f"{BASE_URL}/v3/investors", params={"page": "2"}).mock(
            return_value=httpx.Response(200, json=page_body([{"id": 3}], total=3, page=2, size=2))
        )
        client, _ = build_client()
        seen = [record async for record in client.iterate("/v3/investors", _TYPED_PAGE)]
        assert [record.id for record in seen] == [1, 2, 3]

    @respx.mock
    async def test_iterate_is_bounded_by_max_pages(self) -> None:
        """A broad filter must not be able to walk the whole database."""
        route = respx.get(f"{BASE_URL}/v3/investors").mock(
            return_value=httpx.Response(
                200, json=page_body([{"id": 1}], total=10_000, page=1, size=1)
            )
        )
        client, _ = build_client()
        seen = [record async for record in client.iterate("/v3/investors", _PAGE, max_pages=3)]
        assert len(seen) == 3
        assert route.call_count == 3

    @respx.mock
    async def test_a_non_json_body_is_unreachable_not_a_crash(self) -> None:
        respx.get(f"{BASE_URL}/v3/investors").mock(
            return_value=httpx.Response(200, text="<html>maintenance</html>")
        )
        client, _ = build_client()
        with pytest.raises(Unreachable):
            await client.get_json("/v3/investors", _JSON)
