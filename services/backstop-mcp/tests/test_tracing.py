"""The tool-call span belongs to the request that carried it, and probes are not traced."""

from collections.abc import Iterator, Mapping, Sequence
from typing import Protocol, cast

import pytest
from mcp.server.auth.provider import AccessToken
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from starlette.testclient import TestClient
from testcontainers.community.postgres import PostgresContainer

from backstop_mcp.features.auth import BackstopOAuthProvider

_TOOL = "parse_backstop_link"
_TOOL_SPAN = f"tools/call {_TOOL}"
_REQUEST_SPAN = "POST /mcp"
_INITIALIZE_TRACE = "aa1111111111111111111111111111aa"
_CALL_TRACE = "bb2222222222222222222222222222bb"
_INITIALIZE_TRACEPARENT = f"00-{_INITIALIZE_TRACE}-1111111111111111-01"
_CALL_TRACEPARENT = f"00-{_CALL_TRACE}-2222222222222222-01"


class _HttpResponse(Protocol):
    @property
    def status_code(self) -> int: ...
    @property
    def headers(self) -> Mapping[str, str]: ...
    @property
    def text(self) -> str: ...


def _post(client: TestClient, body: dict[str, object], headers: Mapping[str, str]) -> _HttpResponse:
    return cast("_HttpResponse", client.post("/mcp", json=body, headers=dict(headers)))


def _get(client: TestClient, path: str) -> _HttpResponse:
    return cast("_HttpResponse", client.get(path))


def _headers(traceparent: str, session: str | None = None) -> dict[str, str]:
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        "authorization": "Bearer synthetic-access-token",
        "traceparent": traceparent,
    }
    if session is not None:
        headers["mcp-session-id"] = session
    return headers


def _trace_id(span: ReadableSpan) -> str:
    context = span.get_span_context()
    assert context is not None
    return format(context.trace_id, "032x")


@pytest.fixture
def _token(monkeypatch: pytest.MonkeyPatch) -> None:
    async def load_access_token(_self: BackstopOAuthProvider, token: str) -> AccessToken:
        return AccessToken(
            token=token,
            client_id="client-1",
            scopes=["backstop"],
            subject="11111111-1111-1111-1111-111111111111",
        )

    monkeypatch.setattr(BackstopOAuthProvider, "load_access_token", load_access_token)


@pytest.fixture
def app_client(
    postgres_container: PostgresContainer,
    monkeypatch: pytest.MonkeyPatch,
    _token: None,
    exporter: InMemorySpanExporter,
) -> Iterator[TestClient]:
    from tests.test_app import _set_app_env  # pyright: ignore[reportPrivateUsage]

    _set_app_env(monkeypatch, postgres_container)
    from backstop_mcp.app import create_app

    app = create_app()
    with TestClient(app) as client:
        exporter.clear()
        yield client


@pytest.fixture
def call_spans(app_client: TestClient, exporter: InMemorySpanExporter) -> Sequence[ReadableSpan]:
    initialize = _post(
        app_client,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
        _headers(_INITIALIZE_TRACEPARENT),
    )
    assert initialize.status_code == 200, initialize.text
    session = initialize.headers["mcp-session-id"]
    initialized = _post(
        app_client,
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        _headers(_INITIALIZE_TRACEPARENT, session),
    )
    assert initialized.status_code == 202

    called = _post(
        app_client,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": _TOOL,
                "arguments": {
                    "url": "https://tenant.example.test/backstop/crm/ManageOrganization.action?party_id=1"
                },
            },
        },
        _headers(_CALL_TRACEPARENT, session),
    )
    assert called.status_code == 200, called.text
    return exporter.get_finished_spans()


class TestEachMessageJoinsTheTraceOfItsOwnRequest:
    def test_the_tool_span_is_in_the_call_trace(self, call_spans: Sequence[ReadableSpan]) -> None:
        traces = {_trace_id(span) for span in call_spans if span.name == _TOOL_SPAN}

        assert traces == {_CALL_TRACE}

    def test_the_tool_span_is_a_child_of_its_request(
        self, call_spans: Sequence[ReadableSpan]
    ) -> None:
        server_ids: set[int] = set()
        for span in call_spans:
            if span.name != _REQUEST_SPAN or _trace_id(span) != _CALL_TRACE:
                continue
            context = span.get_span_context()
            if context is None:
                continue
            server_ids.add(context.span_id)
        parents: set[int] = set()
        for span in call_spans:
            parent = span.parent
            if span.name == _TOOL_SPAN and parent is not None:
                parents.add(parent.span_id)

        assert parents & server_ids

    def test_the_tool_span_is_not_in_the_initialize_trace(
        self, call_spans: Sequence[ReadableSpan]
    ) -> None:
        assert _INITIALIZE_TRACE not in {
            _trace_id(span) for span in call_spans if span.name == _TOOL_SPAN
        }


class TestProbesAreNotTraced:
    def test_health_ready_and_metrics_produce_no_span(
        self, app_client: TestClient, exporter: InMemorySpanExporter
    ) -> None:
        exporter.clear()

        assert _get(app_client, "/health").status_code == 200
        assert _get(app_client, "/ready").status_code == 200
        assert _get(app_client, "/metrics").status_code == 200

        assert not exporter.get_finished_spans()

    def test_metrics_omit_the_middleware_duration_histogram(self, app_client: TestClient) -> None:
        assert _get(app_client, "/.well-known/oauth-authorization-server").status_code == 200
        body = _get(app_client, "/metrics").text

        assert "http_server_duration" not in body
