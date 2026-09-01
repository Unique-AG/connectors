"""The transport: status mapping, the one token renewal, retries, and paging."""

import httpx
import pytest
import respx

from tests.helpers import BASE_URL, FakeSession, build_client, page_body, sent_header, sent_query
from with_intelligence_mcp.with_intelligence_client import (
    ApiError,
    AuthError,
    NotEntitled,
    NotFound,
    RateLimited,
    Unreachable,
)


class TestStatusMapping:
    @respx.mock
    async def test_403_is_not_entitled_and_names_the_path(self) -> None:
        respx.get(f"{BASE_URL}/v3/intentions").mock(return_value=httpx.Response(403))
        client, _ = build_client()
        with pytest.raises(NotEntitled) as caught:
            await client.get_json("/v3/intentions")
        assert caught.value.path == "/v3/intentions"
        assert "licensed" in str(caught.value)

    @respx.mock
    async def test_404_is_not_found(self) -> None:
        respx.get(f"{BASE_URL}/v3/investors/1").mock(return_value=httpx.Response(404))
        client, _ = build_client()
        with pytest.raises(NotFound):
            await client.get_json("/v3/investors/1")

    @respx.mock
    async def test_400_is_a_plain_api_error_and_is_not_retried(self) -> None:
        route = respx.get(f"{BASE_URL}/v3/investors").mock(return_value=httpx.Response(400))
        client, _ = build_client()
        with pytest.raises(ApiError):
            await client.get_json("/v3/investors")
        assert route.call_count == 1

    @respx.mock
    async def test_500_is_unreachable_not_refused(self) -> None:
        respx.get(f"{BASE_URL}/v3/investors").mock(return_value=httpx.Response(500))
        client, _ = build_client(max_attempts=1)
        with pytest.raises(Unreachable):
            await client.get_json("/v3/investors")

    @respx.mock
    async def test_a_network_failure_is_unreachable(self) -> None:
        respx.get(f"{BASE_URL}/v3/investors").mock(side_effect=httpx.ConnectError("nope"))
        client, _ = build_client(max_attempts=1)
        with pytest.raises(Unreachable):
            await client.get_json("/v3/investors")


class TestTokenRenewal:
    @respx.mock
    async def test_a_401_renews_once_and_retries(self) -> None:
        route = respx.get(f"{BASE_URL}/v3/investors").mock(
            side_effect=[httpx.Response(401), httpx.Response(200, json={"ok": True})]
        )
        client, session = build_client()
        assert await client.get_json("/v3/investors") == {"ok": True}
        assert session.renewals == 1
        assert route.call_count == 2

    @respx.mock
    async def test_the_retry_carries_the_new_token(self) -> None:
        route = respx.get(f"{BASE_URL}/v3/investors").mock(
            side_effect=[httpx.Response(401), httpx.Response(200, json={})]
        )
        client, _ = build_client(FakeSession("stale"))
        _ = await client.get_json("/v3/investors")
        assert sent_header(route, "authorization", 0) == "Bearer stale"
        assert sent_header(route, "authorization", 1) == "Bearer token-2"

    @respx.mock
    async def test_a_second_401_is_a_real_rejection(self) -> None:
        """Renewing forever would hide a revoked account behind an infinite loop."""
        route = respx.get(f"{BASE_URL}/v3/investors").mock(return_value=httpx.Response(401))
        client, session = build_client()
        with pytest.raises(AuthError):
            await client.get_json("/v3/investors")
        assert session.renewals == 1
        assert route.call_count == 2


class TestRetries:
    @respx.mock
    async def test_a_429_is_retried(self) -> None:
        route = respx.get(f"{BASE_URL}/v3/investors").mock(
            side_effect=[httpx.Response(429), httpx.Response(200, json={"ok": 1})]
        )
        client, _ = build_client()
        assert await client.get_json("/v3/investors") == {"ok": 1}
        assert route.call_count == 2

    @respx.mock
    async def test_the_retry_budget_is_finite(self) -> None:
        route = respx.get(f"{BASE_URL}/v3/investors").mock(return_value=httpx.Response(429))
        client, _ = build_client(max_attempts=2)
        with pytest.raises(RateLimited):
            await client.get_json("/v3/investors")
        assert route.call_count == 2


class TestQueryEncoding:
    @respx.mock
    async def test_a_list_filter_repeats_its_key(self) -> None:
        route = respx.get(f"{BASE_URL}/v3/investors").mock(
            return_value=httpx.Response(200, json=page_body([], total=0))
        )
        client, _ = build_client()
        _ = await client.get_page("/v3/investors", {"id": [1, 2], "name": ["Acme"]})
        query = sent_query(route)
        assert "id=1&id=2" in query
        assert "name=Acme" in query

    @respx.mock
    async def test_page_size_defaults_from_settings(self) -> None:
        route = respx.get(f"{BASE_URL}/v3/investors").mock(
            return_value=httpx.Response(200, json=page_body([], total=0))
        )
        client, _ = build_client()
        _ = await client.get_page("/v3/investors")
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
        seen = [record async for record in client.iterate("/v3/investors")]
        assert [record["id"] for record in seen] == [1, 2, 3]

    @respx.mock
    async def test_iterate_is_bounded_by_max_pages(self) -> None:
        """A broad filter must not be able to walk the whole database."""
        route = respx.get(f"{BASE_URL}/v3/investors").mock(
            return_value=httpx.Response(
                200, json=page_body([{"id": 1}], total=10_000, page=1, size=1)
            )
        )
        client, _ = build_client()
        seen = [record async for record in client.iterate("/v3/investors", max_pages=3)]
        assert len(seen) == 3
        assert route.call_count == 3

    @respx.mock
    async def test_a_non_json_body_is_unreachable_not_a_crash(self) -> None:
        respx.get(f"{BASE_URL}/v3/investors").mock(
            return_value=httpx.Response(200, text="<html>maintenance</html>")
        )
        client, _ = build_client()
        with pytest.raises(Unreachable):
            await client.get_json("/v3/investors")
