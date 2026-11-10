import asyncio
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from datetime import timedelta
from datetime import UTC
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
import json
import threading
import time
from typing import ClassVar, override

import httpx2
from pydantic import AnyHttpUrl
import pytest

from polixis_mcp.upstream import open_upstream
from polixis_mcp.upstream import PolixisQuotaSpentError
from polixis_mcp.upstream import SEARCH_ENTITIES
from polixis_mcp.upstream import SearchEntitiesRequest
from polixis_mcp.upstream import SearchRequestInput
from polixis_mcp.upstream import Upstream
from polixis_mcp.upstream import upstream_http
from polixis_mcp.upstream import UpstreamError
from tests.offline_server import fake_upstream_settings

_WHEN = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
_QUOTA_SPENT = httpx2.Response(
    429,
    headers={"x-amzn-errortype": "LimitExceededException"},
    json={"message": "Limit Exceeded"},
)


async def _search_error(upstream: Upstream) -> UpstreamError:
    with pytest.raises(UpstreamError) as raised:
        await upstream.call(
            SEARCH_ENTITIES, SearchEntitiesRequest(body=SearchRequestInput(name="Example"))
        )
    return raised.value


async def test_a_spent_quota_is_not_retried_and_stops_every_call_until_the_cooldown_ends() -> None:
    moments = [_WHEN]
    sent = 0

    def respond(request: httpx2.Request) -> httpx2.Response:
        nonlocal sent
        if request.url.host == "auth.example.com":
            return httpx2.Response(200, json={"access_token": "token", "expires_in": 3600})
        sent += 1
        return _QUOTA_SPENT

    settings = fake_upstream_settings()
    transport = httpx2.MockTransport(respond)
    async with (
        upstream_http(settings, transport, now=lambda: moments[-1]) as http,
        open_upstream(http, settings) as upstream,
    ):
        answered = await _search_error(upstream)
        refused = await _search_error(upstream)
        moments.append(_WHEN + timedelta(minutes=15))
        answered_again = await _search_error(upstream)

    assert sent == 2
    assert (answered.status_code, type(answered_again)) == (429, UpstreamError)
    assert isinstance(refused, PolixisQuotaSpentError)
    assert str(refused) == (
        "Polixis's request quota for this API key is spent. POST "
        "https://api.example.com/search/api was not sent: this server does not ask Polixis "
        "again before 12:15 UTC, and the quota itself may reset later than that."
    )


async def test_a_throttled_request_is_still_retried() -> None:
    attempts = 0

    def respond(request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        if request.url.host == "auth.example.com":
            return httpx2.Response(200, json={"access_token": "token", "expires_in": 3600})
        attempts += 1
        if attempts == 1:
            return httpx2.Response(429, headers={"x-amzn-errortype": "TooManyRequestsException"})
        return httpx2.Response(200, json={"hits": [], "pagination": {"totalHits": 0}})

    settings = fake_upstream_settings()
    transport = httpx2.MockTransport(respond)
    async with (
        upstream_http(settings, transport, now=lambda: _WHEN) as http,
        open_upstream(http, settings) as upstream,
    ):
        response = await upstream.call(
            SEARCH_ENTITIES, SearchEntitiesRequest(body=SearchRequestInput(name="Example"))
        )

    assert (response.hits, attempts) == ([], 2)


class _SlowPolixis(BaseHTTPRequestHandler):
    """Answers a token, or after a pause any other request, counting how many are in flight."""

    lock: ClassVar[threading.Lock] = threading.Lock()
    in_flight: ClassVar[int] = 0
    most_in_flight: ClassVar[int] = 0

    def do_POST(self) -> None:  # noqa: N802 - the name http.server dispatches POST to
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if self.path == "/token":
            self._answer({"access_token": "token", "expires_in": 3600})
            return
        with _SlowPolixis.lock:
            _SlowPolixis.in_flight += 1
            _SlowPolixis.most_in_flight = max(_SlowPolixis.most_in_flight, _SlowPolixis.in_flight)
        time.sleep(0.2)
        with _SlowPolixis.lock:
            _SlowPolixis.in_flight -= 1
        self._answer({"hits": [], "pagination": {"totalHits": 0}})

    def _answer(self, body: dict[str, object]) -> None:
        content = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    @override
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - the name http.server passes it by
        return


@contextmanager
def _slow_polixis() -> Generator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SlowPolixis)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


async def test_at_most_the_configured_requests_reach_polixis_at_once() -> None:
    with _slow_polixis() as url:
        settings = fake_upstream_settings().model_copy(
            update={
                "api_url": AnyHttpUrl(url),
                "token_url": AnyHttpUrl(f"{url}/token"),
                "max_concurrent_requests": 4,
            }
        )
        async with (
            upstream_http(settings, now=lambda: _WHEN) as http,
            open_upstream(http, settings) as upstream,
        ):
            await asyncio.gather(
                *(
                    upstream.call(
                        SEARCH_ENTITIES,
                        SearchEntitiesRequest(body=SearchRequestInput(name=f"Example {number}")),
                    )
                    for number in range(10)
                )
            )

    assert _SlowPolixis.most_in_flight == 4
