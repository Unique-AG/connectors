"""Every MCP message's span belongs to the trace of the request that carried it.

Driven over real HTTP: the defect is a property of the per-session asyncio task the streamable-HTTP
transport starts during `initialize` and reuses for every later message, and an in-process client
has no session task, so it would pass with the fix deleted. Each request carries a *different*
`traceparent`, which is the whole experiment.
"""

from collections.abc import Iterator, Mapping, Sequence
from typing import Protocol, cast

import pytest
from fastmcp import Client, FastMCP
from fastmcp.client.transports import FastMCPTransport
from fastmcp.server.auth.providers.azure import AzureProvider
from fastmcp.server.dependencies import AccessToken
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanContext
from starlette.applications import Starlette
from starlette.testclient import TestClient

from office_365_mcp.app import create_app
from office_365_mcp.config import AppConfig, DatabaseConfig, EntraConfig, SurfaceConfig, ToolsPreset

_CLIENT_ID = "1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061"

_INITIALIZE_TRACE = "aa1111111111111111111111111111aa"
_TOOLS_LIST_TRACE = "bb2222222222222222222222222222bb"
_INITIALIZE_TRACEPARENT = f"00-{_INITIALIZE_TRACE}-1111111111111111-01"
_TOOLS_LIST_TRACEPARENT = f"00-{_TOOLS_LIST_TRACE}-2222222222222222-01"

_MESSAGE_SPAN = "tools/list"
_REQUEST_SPAN = "POST /mcp"


class _HttpResponse(Protocol):
    """`starlette.testclient` returns httpx responses this repo's type checking sees as partial."""

    @property
    def status_code(self) -> int: ...
    @property
    def headers(self) -> Mapping[str, str]: ...


def _post(client: TestClient, body: dict[str, object], headers: Mapping[str, str]) -> _HttpResponse:
    return cast(
        "_HttpResponse",
        client.post("/mcp", json=body, headers=dict(headers)),
    )


def _headers(traceparent: str, session: str | None = None) -> dict[str, str]:
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        "authorization": "Bearer synthetic-entra-access-token",
        "traceparent": traceparent,
    }
    if session is not None:
        headers["mcp-session-id"] = session
    return headers


def _context(span: ReadableSpan) -> SpanContext:
    """A finished span always has one. The SDK types it as optional."""
    context = span.get_span_context()
    assert context is not None, f"{span.name} has no span context"
    return context


def _trace_id(span: ReadableSpan) -> str:
    return format(_context(span).trace_id, "032x")


def _trace_ids(spans: Sequence[ReadableSpan], name: str) -> set[str]:
    return {_trace_id(span) for span in spans if span.name == name}


@pytest.fixture(autouse=True)
def entra(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the token check is stubbed. The transport's session-owner check still runs against what
    this returns, which is what lets a second request reuse the first request's session — and
    reusing that session is the condition the defect lives in."""

    async def verify_token(_self: AzureProvider, token: str) -> AccessToken:
        return AccessToken(token=token, client_id=_CLIENT_ID, scopes=["access_as_user"])

    monkeypatch.setattr(AzureProvider, "verify_token", verify_token)


@pytest.fixture
def app() -> Starlette:
    """The real app. Nothing here reaches Postgres, so the URL only has to parse."""
    return create_app(
        config=AppConfig.model_validate({"public_base_url": "https://office-365-mcp.example"}),
        database_config=DatabaseConfig.model_validate(
            {"url": "postgresql://user:pass@127.0.0.1:1/nope"}
        ),
        entra_config=EntraConfig.model_validate(
            {
                "tenant_id": "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81",
                "client_id": _CLIENT_ID,
                "client_secret": "s3cr3t",
            }
        ),
        surface_config=SurfaceConfig.model_validate({"tools_preset": ToolsPreset.TEAMS}),
    )


@pytest.fixture
def exporter() -> Iterator[InMemorySpanExporter]:
    """The tracer provider is process-wide and settable only once, so the exporter attaches to
    whichever is already in play — the same shape `test_mcp_tools.py` uses."""
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    yield exporter
    # A span processor cannot be removed, and the provider outlives this test: the shutdown is what
    # stops the exporter collecting every span the rest of the session emits.
    exporter.shutdown()


@pytest.fixture
def session_spans(app: Starlette, exporter: InMemorySpanExporter) -> Sequence[ReadableSpan]:
    with TestClient(app) as client:
        # Cleared after the lifespan, not before: the startup manifest calls list_tools with no
        # request to parent it, a benign root trace a reader mistakes for the defect.
        exporter.clear()

        initialize = _post(
            client,
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
        assert initialize.status_code == 200, "initialize was refused"
        session = initialize.headers["mcp-session-id"]

        initialized = _post(
            client,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            _headers(_INITIALIZE_TRACEPARENT, session),
        )
        assert initialized.status_code == 202

        # Post to "/mcp" and not "/mcp/": the trailing slash redirects, doubling every span.
        listed = _post(
            client,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            _headers(_TOOLS_LIST_TRACEPARENT, session),
        )
        assert listed.status_code == 200, "tools/list was refused"

    return exporter.get_finished_spans()


class TestEachMessageJoinsTheTraceOfItsOwnRequest:
    def test_the_message_span_lands_in_the_trace_of_the_request_that_carried_it(
        self, session_spans: Sequence[ReadableSpan]
    ) -> None:
        message_traces = _trace_ids(session_spans, _MESSAGE_SPAN)

        assert message_traces == {_TOOLS_LIST_TRACE}, (
            f"the {_MESSAGE_SPAN} span belongs in the trace of the request that carried it "
            + f"({_TOOLS_LIST_TRACE}), and is in {sorted(message_traces)}"
        )

    def test_the_request_that_carried_it_is_in_that_trace_too(
        self, session_spans: Sequence[ReadableSpan]
    ) -> None:
        assert _TOOLS_LIST_TRACE in _trace_ids(session_spans, _REQUEST_SPAN)

    def test_no_message_span_lands_in_the_initialize_requests_trace(
        self, session_spans: Sequence[ReadableSpan]
    ) -> None:
        assert _INITIALIZE_TRACE in _trace_ids(session_spans, _REQUEST_SPAN), (
            "initialize's own traceparent never reached a span, so this test proves nothing"
        )
        assert _INITIALIZE_TRACE not in _trace_ids(session_spans, _MESSAGE_SPAN), (
            "a message span is in the initialize request's trace — the session task's stale "
            + "OpenTelemetry context is back. See src/office_365_mcp/tracing.py"
        )

    def test_the_message_span_is_a_child_of_its_own_requests_server_span(
        self, session_spans: Sequence[ReadableSpan]
    ) -> None:
        server_spans = {
            _context(span).span_id
            for span in session_spans
            if span.name == _REQUEST_SPAN and _trace_id(span) == _TOOLS_LIST_TRACE
        }
        parents = {
            span.parent.span_id
            for span in session_spans
            if span.name == _MESSAGE_SPAN and span.parent is not None
        }

        assert parents & server_spans, "no message span descends from its own request's server span"


class TestAMessageWithNoRequestIsLeftAlone:
    async def test_an_in_process_client_still_lists_tools(self, app: Starlette) -> None:
        """The stdio path: `get_http_request` raises, and there is nothing stale to correct."""
        server = cast("FastMCP[None]", app.state.fastmcp_server)

        async with Client(FastMCPTransport(server)) as client:
            tools = await client.list_tools()

        assert tools, "an in-process client got no tools"
