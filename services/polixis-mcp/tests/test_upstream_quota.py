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

from fastmcp import Client
import httpx2
from pydantic import AnyHttpUrl
import pytest

from polixis_mcp.mcp import create_server
from polixis_mcp.upstream import open_upstream
from polixis_mcp.upstream import PolixisQuotaSpentError
from polixis_mcp.upstream import SEARCH_ENTITIES
from polixis_mcp.upstream import SearchEntitiesRequest
from polixis_mcp.upstream import SearchRequestInput
from polixis_mcp.upstream import Upstream
from polixis_mcp.upstream import upstream_http
from polixis_mcp.upstream import UpstreamError
from tests.offline_server import fake_persistence
from tests.offline_server import fake_upstream_settings
from tests.tool_calls import tool_error

_WHEN = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
_QUOTA_SPENT = httpx2.Response(
    429,
    headers={"x-amzn-errortype": "LimitExceededException"},
    json={"message": "Limit Exceeded"},
)
_QUOTA_SPENT_ANSWER = (
    "The Polixis API request limit was exceeded. This server does not retry the request, since "
    "Polixis answers no more requests until more are added to the limit. Do not call this tool "
    "or any other Polixis tool again in this conversation. Tell the user that the Polixis API "
    "request limit was exceeded and that they should ask their administrator to get more "
    "Polixis API requests."
)


async def _search_error(upstream: Upstream) -> UpstreamError:
    with pytest.raises(UpstreamError) as raised:
        await upstream.call(
            SEARCH_ENTITIES, SearchEntitiesRequest(body=SearchRequestInput(name="Example"))
        )
    return raised.value


def _quota_spent_polixis(sent: list[httpx2.Request]) -> httpx2.MockTransport:
    def respond(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "auth.example.com":
            return httpx2.Response(200, json={"access_token": "token", "expires_in": 3600})
        sent.append(request)
        return _QUOTA_SPENT

    return httpx2.MockTransport(respond)


async def test_a_spent_quota_is_not_retried_and_stops_every_call_until_the_cooldown_ends() -> None:
    moments = [_WHEN]
    sent: list[httpx2.Request] = []
    settings = fake_upstream_settings()
    async with (
        upstream_http(settings, _quota_spent_polixis(sent), now=lambda: moments[-1]) as http,
        open_upstream(http, settings) as upstream,
    ):
        answered = await _search_error(upstream)
        refused = await _search_error(upstream)
        moments.append(_WHEN + timedelta(minutes=15))
        answered_again = await _search_error(upstream)

    assert len(sent) == 2
    assert all(
        isinstance(error, PolixisQuotaSpentError) and error.status_code == 429
        for error in (answered, refused, answered_again)
    )


async def test_a_request_waiting_for_a_slot_is_not_sent_once_the_quota_is_spent() -> None:
    sent: list[httpx2.Request] = []
    answer = asyncio.Event()

    async def respond(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "auth.example.com":
            return httpx2.Response(200, json={"access_token": "token", "expires_in": 3600})
        sent.append(request)
        await answer.wait()
        return _QUOTA_SPENT

    settings = fake_upstream_settings().model_copy(update={"max_concurrent_requests": 1})
    async with (
        upstream_http(settings, httpx2.MockTransport(respond), now=lambda: _WHEN) as http,
        open_upstream(http, settings) as upstream,
    ):
        first = asyncio.create_task(_search_error(upstream))
        waiting = asyncio.create_task(_search_error(upstream))
        while not sent:
            await asyncio.sleep(0)
        answer.set()
        errors = await asyncio.gather(first, waiting)

    assert len(sent) == 1
    assert all(isinstance(error, PolixisQuotaSpentError) for error in errors)


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("search_entities", {"name": "Example"}),
        ("resolve_permanent_id", {"pid": "O00000000000000000000000000000100"}),
    ],
)
async def test_a_spent_quota_tells_the_agent_to_stop_and_send_the_user_to_an_administrator(
    tool: str, arguments: dict[str, object]
) -> None:
    sent: list[httpx2.Request] = []
    server = create_server(fake_upstream_settings(), fake_persistence(), _quota_spent_polixis(sent))
    async with Client(server) as client:
        answered = await tool_error(client, tool, arguments)
        refused = await tool_error(client, tool, arguments)

    assert len(sent) == 1
    assert answered == refused == _QUOTA_SPENT_ANSWER


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
