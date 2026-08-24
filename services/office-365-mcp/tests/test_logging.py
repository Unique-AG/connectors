"""What every log line this service writes must and must not carry.

Asserted through the **real** handler, because the defects are all properties of a formatter this
service does not own: it copies every `extra=` into the payload and serialises whole exception
stacks. A test that formatted the records itself would assert against the wrong opponent.
"""

import ast
import inspect
import io
import json
import logging
import os
import pathlib
import socket
import subprocess
import sys
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import IO, Protocol, cast, override

import httpx
import mcp.server.lowlevel.server as sdk_server
import pytest
from azure.core.exceptions import ClientAuthenticationError
from fastmcp.server.auth.providers.azure import AzureProvider
from fastmcp.server.dependencies import AccessToken
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from starlette.applications import Starlette
from starlette.testclient import TestClient
from unique_mcp.logging import _PinoJson  # pyright: ignore[reportPrivateUsage]

from office_365_mcp.app import create_app
from office_365_mcp.config import AppConfig, DatabaseConfig, EntraConfig, SurfaceConfig, ToolsPreset
from office_365_mcp.logging import (
    CENSORED,
    TRUNCATED,
    UNPRINTABLE,
    RedactionFilter,
    StaleMessageLineFilter,
    configure_logging,
)

_PUBLIC_BASE_URL = "https://office-365-mcp.example"
_TENANT_ID = "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81"
_CLIENT_ID = "1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061"

# Three base64url segments beginning `eyJ`, which is what every Entra and Graph JWT looks like.
_JWT = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJub2JvZHkifQ.c2lnbmF0dXJl"

# Two requests, two traces, different on purpose: that is the whole experiment (`test_tracing.py`).
_INITIALIZE_TRACE = "cc3333333333333333333333333333cc"
_TOOL_CALL_TRACE = "dd4444444444444444444444444444dd"
_INITIALIZE_TRACEPARENT = f"00-{_INITIALIZE_TRACE}-3333333333333333-01"
_TOOL_CALL_TRACEPARENT = f"00-{_TOOL_CALL_TRACE}-4444444444444444-01"

# Spelled here rather than imported from `office_365_mcp.logging`, so a rename there is a failing
# test.
_SDK_LOGGER = "mcp.server.lowlevel.server"
_SDK_LINE = "Processing request of type %s"


class _HttpResponse(Protocol):
    """`starlette.testclient` returns httpx responses this repo's type checking sees as partial."""

    @property
    def status_code(self) -> int: ...
    @property
    def headers(self) -> Mapping[str, str]: ...


@dataclass(frozen=True)
class _Sink:
    stream: io.StringIO
    handler: logging.Handler

    def lines(self) -> list[Mapping[str, object]]:
        return [
            cast("Mapping[str, object]", json.loads(line))
            for line in self.stream.getvalue().splitlines()
            if line.strip()
        ]

    def one(self) -> Mapping[str, object]:
        lines = self.lines()
        assert len(lines) == 1, f"expected exactly one line, got {len(lines)}: {lines}"
        return lines[0]


def _pino_handler() -> logging.Handler:
    """Found by the formatter upstream puts on it, not by this service's own filters:
    `configure_logging` installs those on *every* root handler, and under pytest there are five.
    """
    handlers = [
        handler
        for handler in logging.getLogger().handlers
        if isinstance(handler.formatter, _PinoJson)
    ]
    assert len(handlers) == 1, (
        f"expected one handler with unique_mcp's pino formatter, found {len(handlers)}. "
        + "See unique_mcp.logging.configure_logging and src/office_365_mcp/logging.py"
    )
    return handlers[0]


@pytest.fixture
def sink() -> Iterator[_Sink]:
    """Restores the stream rather than the handler: removing the handler would leave a later
    `create_app` in this session with none to reinstall.
    """
    root = logging.getLogger()
    level = root.level
    configure_logging(AppConfig.model_validate({"public_base_url": _PUBLIC_BASE_URL}))
    handler = _pino_handler()
    stream_handler = cast("logging.StreamHandler[IO[str]]", handler)
    stream = io.StringIO()
    previous = stream_handler.setStream(stream)
    try:
        yield _Sink(stream=stream, handler=handler)
    finally:
        if previous is not None:
            _ = stream_handler.setStream(previous)
        root.setLevel(level)


def _log(message: str, *args: object, **extra: object) -> None:
    """From a logger this service has never heard of: the filters are on the handler, so what
    redacts a line does not depend on which logger wrote it."""
    logging.getLogger("some.vendor.module").info(message, *args, extra=extra or None)


class TestNothingSecretReachesTheLog:
    """The first net is the field name, the second is the value's shape. Every vector here is one
    the TypeScript reference redacts (`packages/logger/src/options.ts:22-34`) or one this service
    reaches on its own.
    """

    def test_the_authorization_header_is_censored_by_name(self, sink: _Sink) -> None:
        _log("outbound", authorization=f"Bearer {_JWT}")

        assert sink.one()["authorization"] == CENSORED

    @pytest.mark.parametrize(
        "spelling",
        ["x-api-key", "x_api_key", "X-API-KEY", "apiKey", "api key", "graph_api_key"],
        ids=repr,
    )
    def test_no_spelling_of_a_key_name_gets_through(self, sink: _Sink, spelling: str) -> None:
        """The reference lists four spellings of two header names as four redact paths; a fifth is
        the bypass. So the name is matched with its separators removed, not against a list."""
        _log("inbound", headers={spelling: "opaque-key-value"})

        assert sink.one()["headers"] == {spelling: CENSORED}

    def test_a_nested_config_header_is_reached(self, sink: _Sink) -> None:
        """`config.headers.Authorization` in the reference: the leak is two levels down."""
        _log(
            "calling",
            config={
                "url": "https://graph.microsoft.com",
                "headers": {"Authorization": f"Bearer {_JWT}"},
            },
        )

        config = cast("Mapping[str, object]", sink.one()["config"])
        assert cast("Mapping[str, object]", config["headers"]) == {"Authorization": CENSORED}
        assert config["url"] == "https://graph.microsoft.com", (
            "the rest of the field is still there"
        )

    def test_an_asgi_header_list_is_reached(self, sink: _Sink) -> None:
        """ASGI spells headers as a list of byte pairs, which is neither a dict nor a string."""
        _log(
            "request", headers=[(b"host", b"office-365-mcp"), (b"authorization", b"Bearer opaque")]
        )

        headers = json.dumps(sink.one()["headers"], default=str)
        assert "Bearer opaque" not in headers, headers
        assert CENSORED in headers, headers
        assert "host" in headers, "the rest of the header list is gone"

    def test_a_secret_this_service_names_itself_is_censored(self, sink: _Sink) -> None:
        """No list of HTTP header names contains these, and both are this service's own."""
        _log("config", entra_client_secret="s3cr3t", graph_access_token="opaque")

        line = sink.one()
        assert line["entra_client_secret"] == CENSORED
        assert line["graph_access_token"] == CENSORED

    def test_a_bearer_token_in_a_value_is_censored_under_an_innocent_name(
        self, sink: _Sink
    ) -> None:
        """An httpx exception's `repr` of the request it failed to send is a string, and this is
        that string."""
        _log("failed", detail=f"<Request headers={{'authorization': 'Bearer {_JWT}'}}>")

        assert CENSORED in cast("str", sink.one()["detail"])
        assert _JWT not in cast("str", sink.one()["detail"])

    def test_a_bare_jwt_in_a_value_is_censored(self, sink: _Sink) -> None:
        _log("exchanged", assertion_result=_JWT)

        assert sink.one()["assertion_result"] == CENSORED

    def test_a_field_name_that_cannot_be_rendered_censors_its_value(self, sink: _Sink) -> None:
        """The same guard on the other half of a field, and the direction of the fallback is the
        point: the name is what decides whether the value is logged at all, so a name that cannot
        be read is a decision that cannot be made — and answering "not sensitive" would log a value
        that the same key spelled readably would have censored."""

        class _HostileKey:
            @override
            def __str__(self) -> str:
                raise RuntimeError("this key refuses to be logged")

        _log("inbound", headers={_HostileKey(): "opaque-key-value"})

        assert sink.one()["headers"] == {UNPRINTABLE: CENSORED}

    def test_a_message_that_cannot_be_interpolated_keeps_the_line(self, sink: _Sink) -> None:
        """A `%`-template and the arguments meant to fill it are written in two places, so they
        disagree: `logger.info("100%", 1)` raises `ValueError: incomplete format`. Stdlib survives
        that with a stderr note, and a filter on the root handler must not do worse to a mistake in
        uvicorn, kiota, asyncpg or msal — least of all inside their own `except:
        logger.exception(...)`, where it would replace the error being reported.

        The template that is kept is still censored, and the arguments are dropped with it:
        `Handler.handleError` writes both out verbatim, so nothing may reach it."""
        _log("connecting to postgresql://office:hunter2@db.internal 100%", "unused")

        line = sink.one()
        assert line["msg"] == f"connecting to postgresql://{CENSORED}@db.internal 100%"
        assert "hunter2" not in sink.stream.getvalue()

    def test_a_token_interpolated_into_the_message_is_censored(self, sink: _Sink) -> None:
        """`%s` of a token is a token, and the message is not an attribute the name check sees."""
        _log("retrying with %s", f"Bearer {_JWT}")

        message = cast("str", sink.one()["msg"])
        assert message == f"retrying with Bearer {CENSORED}", message

    def test_a_credential_in_a_query_string_is_censored(self, sink: _Sink) -> None:
        """`req.query["api-key"]` in the reference; uvicorn's access line quotes the query
        string."""
        _log('127.0.0.1:1 - "GET /mcp?api-key=opaque-value&page=2 HTTP/1.1" 200')

        message = cast("str", sink.one()["msg"])
        assert f"api-key={CENSORED}&page=2" in message, message

    def test_an_authorization_code_in_a_query_string_is_censored(self, sink: _Sink) -> None:
        """The parameter no name check would suspect and every sign-in carries. `/auth/callback` is
        not one of the paths upstream's access filter drops, so uvicorn writes a live Entra
        authorization code into the log pipeline on every successful consent."""
        _log('127.0.0.1:1 - "GET /auth/callback?code=1.AXcAlive-auth-code&state=x HTTP/1.1" 302')

        message = cast("str", sink.one()["msg"])
        assert f"code={CENSORED}&state=x" in message, message
        assert "1.AXcAlive-auth-code" not in sink.stream.getvalue()

    @pytest.mark.parametrize("parameter", ["postcode", "encoding", "areacode"], ids=repr)
    def test_a_parameter_that_merely_contains_code_is_kept(
        self, sink: _Sink, parameter: str
    ) -> None:
        """Why `code` is matched as a whole parameter name: as a substring it would censor these,
        and a censored line answers no question about the request it describes."""
        _log(f'127.0.0.1:1 - "GET /mcp?{parameter}=8000 HTTP/1.1" 200')

        message = cast("str", sink.one()["msg"])
        assert f"{parameter}=8000" in message, message

    def test_a_password_in_a_url_is_censored(self, sink: _Sink) -> None:
        """Reachable today: `server/readiness.py` logs the store's failure with `exc_info=True`,
        and asyncpg quotes the DSN it could not reach."""
        _log("unreachable", dsn="postgresql://office:hunter2@db.internal:5432/office")

        assert sink.one()["dsn"] == f"postgresql://{CENSORED}@db.internal:5432/office"

    def test_an_exception_stack_is_censored(self, sink: _Sink) -> None:
        """The formatter serialises the whole chain into `err.stack`, so the chain is a vector."""
        try:
            raise ConnectionRefusedError(
                "could not connect to postgresql://office:hunter2@db.internal:5432/office"
            )
        except ConnectionRefusedError:
            logging.getLogger("some.vendor.module").warning("store unreachable", exc_info=True)

        err = cast("Mapping[str, object]", sink.one()["err"])
        assert err["name"] == "ConnectionRefusedError"
        assert "hunter2" not in json.dumps(err), err
        assert CENSORED in cast("str", err["message"])
        assert "ConnectionRefusedError" in cast("str", err["stack"]), "the stack is still a stack"

    def test_an_exception_whose_message_cannot_be_rendered_keeps_the_line(
        self, sink: _Sink
    ) -> None:
        """`str(exc)` is a dependency's `__str__` like any other, and this one is reached from a
        filter — where an exception raised replaces the error the caller was reporting. The rest of
        the field survives: `traceback` renders a raising `__str__` as `<exception str() failed>`
        rather than propagating it, so the cause is still there and still censored."""

        class _Hostile(RuntimeError):
            @override
            def __str__(self) -> str:
                raise RuntimeError("this exception refuses to be rendered")

        try:
            try:
                raise ConnectionRefusedError("postgresql://office:hunter2@db.internal:5432/office")
            except ConnectionRefusedError as cause:
                raise _Hostile from cause
        except _Hostile:
            logging.getLogger("some.vendor.module").warning("store unreachable", exc_info=True)

        err = cast("Mapping[str, object]", sink.one()["err"])
        assert err["name"] == "_Hostile"
        assert err["message"] == UNPRINTABLE
        assert "hunter2" not in json.dumps(err), err
        assert CENSORED in cast("str", err["stack"]), "the cause is still in the stack"

    def test_a_stack_that_cannot_be_formatted_does_not_raise_out_of_the_filter(self) -> None:
        """`exc_info` is whatever the caller passed — `logging` forwards any three-tuple through
        untouched — and `traceback.format_exception` raises `AttributeError: 'str' object has no
        attribute 'tb_frame'` on a third element that is not a traceback.

        The one case in this class asserted without the real handler, and the reason is the vector
        itself: a malformed `exc_info` also breaks every *other* handler on the root logger, because
        stdlib's own `Formatter.format` calls `formatException` on it — and pytest's capture handler
        re-raises what it cannot format. So what is asserted here is only what this filter owes its
        caller: it renders what it can, censors that, and returns True.
        """
        broken = ConnectionRefusedError("postgresql://office:hunter2@db.internal:5432/office")
        record = logging.LogRecord(
            "some.vendor.module",
            logging.WARNING,
            __file__,
            1,
            "store unreachable",
            None,
            # The cast is the vector, not a convenience: this is the tuple a dependency assembling
            # `exc_info` by hand passes in, and the type checker is why this service never does.
            cast(
                "tuple[type[BaseException], BaseException, TracebackType | None]",
                (ConnectionRefusedError, broken, "not a traceback"),
            ),
        )

        assert RedactionFilter().filter(record) is True

        err = cast("Mapping[str, object]", cast("Mapping[str, object]", record.__dict__)["err"])
        assert err["name"] == "ConnectionRefusedError"
        assert err["stack"] == UNPRINTABLE
        assert err["message"] == f"postgresql://{CENSORED}@db.internal:5432/office"

    def test_the_callers_own_dictionary_is_not_touched(self, sink: _Sink) -> None:
        """The caller is still going to send these headers, so censoring in place would corrupt
        the request the line is about."""
        headers = {"Authorization": f"Bearer {_JWT}"}

        _log("sending", headers=headers)

        assert sink.one()["headers"] == {"Authorization": CENSORED}
        assert headers == {"Authorization": f"Bearer {_JWT}"}, "the caller's dict was mutated"

    def test_a_self_referencing_structure_terminates(self, sink: _Sink) -> None:
        """An ASGI scope can contain itself. A walk with no depth cap ends the process."""
        looping: dict[str, object] = {"authorization": "Bearer opaque"}
        looping["itself"] = looping

        _log("scope", scope=looping)

        scope = cast("Mapping[str, object]", sink.one()["scope"])
        assert scope["authorization"] == CENSORED
        assert TRUNCATED in json.dumps(scope), "the cycle was passed through rather than cut"

    def test_the_filter_runs_before_the_formatter(self, sink: _Sink) -> None:
        """`Handler.handle` filters and only then emits, so the bytes the formatter produced are
        the proof."""
        _log("outbound", authorization=f"Bearer {_JWT}")

        assert _JWT not in sink.stream.getvalue()


class TestNoLineLeavesByAnotherDoor:
    """Redaction on the handler only holds while the handler is the only way out of the process."""

    @pytest.mark.usefixtures("sink")
    def test_no_handler_escapes_the_filters(self) -> None:
        """A second handler is a second way out."""
        for handler in logging.getLogger().handlers:
            installed = {type(existing) for existing in handler.filters}
            assert RedactionFilter in installed, f"{handler} has no redaction filter"

    @pytest.mark.usefixtures("sink")
    def test_no_logger_keeps_its_own_way_out(self) -> None:
        """A logger with handlers of its own and `propagate = False` bypasses both the formatter
        and the filters. FastMCP configures itself that way at import time. If this fails, add the
        logger to `_RECLAIMED_LOGGERS` after reading why it wanted its own handler.
        """
        registry = cast("Mapping[str, object]", logging.Logger.manager.loggerDict)
        escaping = [
            name
            for name, logger in registry.items()
            if isinstance(logger, logging.Logger) and logger.handlers and not logger.propagate
        ]

        assert not escaping, f"these loggers bypass the pino handler entirely: {escaping}"

    def test_a_fastmcp_line_arrives_as_pino_json(self, sink: _Sink) -> None:
        """The line that used to be rich-formatted text: unparseable *and* unredacted."""
        logging.getLogger("fastmcp.server.auth").warning("using %s", "Bearer aaaaaaaaaaaaaaaaaaaa")

        line = sink.one()
        assert line["context"] == "fastmcp.server.auth"
        assert line["msg"] == f"using Bearer {CENSORED}"


class TestEveryLineIsJoinable:
    """A line nothing can group is a line nobody reads. `teams-mcp` generates an id when there is
    no span for the same reason (`services/teams-mcp/src/app.module.ts:73-79`)."""

    def test_a_line_with_no_span_and_no_request_still_carries_an_id(self, sink: _Sink) -> None:
        """No span and no request: the id is this process's boot."""
        _log("starting")

        correlation = cast("str", sink.one()["correlation_id"])
        assert correlation.startswith("boot-"), correlation

    def test_every_line_of_one_boot_carries_the_same_id(self, sink: _Sink) -> None:
        _log("first")
        _log("second")

        assert len({line["correlation_id"] for line in sink.lines()}) == 1

    def test_a_line_inside_a_span_carries_its_trace(self, sink: _Sink) -> None:
        _install_tracer_provider()

        with trace.get_tracer(__name__).start_as_current_span("unit"):
            _log("inside")

        line = sink.one()
        assert line["correlation_id"] == line["trace_id"], line
        assert line["correlation_id"] != f"boot-{line['correlation_id']}"

    def test_a_caller_that_supplies_its_own_id_keeps_it(self, sink: _Sink) -> None:
        _log("imported", correlation_id="from-upstream")

        assert sink.one()["correlation_id"] == "from-upstream"

    def test_a_readiness_line_joins_the_request_that_asked(
        self, sink: _Sink, app: Starlette
    ) -> None:
        """`/ready` is a plain HTTP route and with tracing off has no span, so the id comes from
        the ASGI middleware."""
        with TestClient(app) as client:
            sink.stream.truncate(0)
            _ = sink.stream.seek(0)
            response = cast("_HttpResponse", client.get("/ready"))  # pyright: ignore[reportUnknownMemberType]

        assert response.status_code in (200, 503), "the probe answered neither way"
        warnings = [
            line for line in sink.lines() if line["context"] == "office_365_mcp.server.readiness"
        ]
        assert warnings, "the probe against an unreachable database logged nothing"
        for line in warnings:
            assert line["correlation_id"] is not None
            assert cast("str", line["correlation_id"]).startswith(("req-", "boot-")) or line.get(
                "trace_id"
            ), line

    def test_a_forwarded_request_id_is_preferred_over_a_new_one(
        self, sink: _Sink, app: Starlette
    ) -> None:
        """A gateway that already minted an id is the identity that joins both systems' logs."""
        with TestClient(app) as client:
            sink.stream.truncate(0)
            _ = sink.stream.seek(0)
            _ = cast(
                "_HttpResponse",
                client.get("/ready", headers={"x-request-id": "gateway-42"}),  # pyright: ignore[reportUnknownMemberType]
            )

        forwarded = [line for line in sink.lines() if line.get("http_request_id") == "gateway-42"]
        assert forwarded, [line.get("http_request_id") for line in sink.lines()]


class TestTheSdkLineThisServiceQuiets:
    def test_the_sdk_still_writes_the_line_this_service_matches(self) -> None:
        """Quieting is matched on the SDK's own message template, so an SDK that renamed it would
        leave this service emitting a stale trace id again, silently. When this fails, re-read
        `mcp/server/lowlevel/server.py` and `src/office_365_mcp/logging.py`: either the template
        moved, or the line no longer runs before the request handler.
        """
        source = pathlib.Path(inspect.getfile(sdk_server)).read_text(encoding="utf-8")

        assert source.count(_SDK_LINE) == 1, (
            f"{_SDK_LINE!r} is no longer written exactly once in {inspect.getfile(sdk_server)}; "
            + "StaleMessageLineFilter in src/office_365_mcp/logging.py matches it by template"
        )

        handler = _sdk_handle_request(source)
        logged = [
            index for index, statement in enumerate(handler.body) if _is_the_sdk_line(statement)
        ]
        assert logged == [0], (
            "the SDK's per-message line is no longer the first statement of _handle_request, so "
            + "what runs before it may now be correctable from inside the session task. Re-read "
            + "mcp/server/lowlevel/server.py and src/office_365_mcp/logging.py"
        )

    def test_only_that_line_is_dropped(self, sink: _Sink) -> None:
        sdk = logging.getLogger(_SDK_LOGGER)

        sdk.info(_SDK_LINE, "CallToolRequest")
        sdk.info("Request %s cancelled - duplicate response suppressed", 7)

        assert [line["msg"] for line in sink.lines()] == [
            "Request 7 cancelled - duplicate response suppressed"
        ]


class TestOneLinePerMessageInTheRightTrace:
    """Driven over real HTTP: the wrong trace id is a property of the per-session asyncio task the
    streamable-HTTP transport starts during `initialize`, and an in-process client has no session
    task. See `src/office_365_mcp/tracing.py`.
    """

    def test_the_sdk_line_carries_the_initialize_requests_trace(
        self, unquieted_lines: Sequence[Mapping[str, object]]
    ) -> None:
        stale = [
            line
            for line in unquieted_lines
            if line["context"] == _SDK_LOGGER
            and line["msg"] == "Processing request of type CallToolRequest"
        ]

        assert stale, "the SDK no longer logs a per-message line, so this proves nothing"
        assert {line["trace_id"] for line in stale} == {_INITIALIZE_TRACE}, (
            "the SDK's line for the tool call was expected in the initialize request's trace — "
            + f"got {[line.get('trace_id') for line in stale]}"
        )

    def test_that_line_is_gone(self, lines: Sequence[Mapping[str, object]]) -> None:
        assert not [line for line in lines if line["context"] == _SDK_LOGGER], (
            "the SDK's per-message line is back in the log"
        )

    def test_the_replacement_line_is_in_the_trace_of_its_own_request(
        self, lines: Sequence[Mapping[str, object]]
    ) -> None:
        replacements = [line for line in lines if line.get("mcp_method") == "tools/call"]

        assert replacements, "no line names the tool call at all"
        assert {line["trace_id"] for line in replacements} == {_TOOL_CALL_TRACE}
        assert {line["correlation_id"] for line in replacements} == {_TOOL_CALL_TRACE}

    def test_the_replacement_says_more_than_the_line_it_replaces(
        self, lines: Sequence[Mapping[str, object]]
    ) -> None:
        """Nothing is lost: the SDK said the request *type*, this says the JSON-RPC method, the MCP
        request id and the transport's session id."""
        replacement = next(line for line in lines if line.get("mcp_method") == "tools/call")

        assert replacement["mcp_method"] == "tools/call"
        assert replacement["request_id"] is not None
        assert replacement["session_id"] is not None

    def test_no_line_about_the_tool_call_is_in_the_initialize_trace(
        self, lines: Sequence[Mapping[str, object]]
    ) -> None:
        """The first assertion guards the second: `initialize` really did run under its own
        traceparent, so this is the trace lines used to be swept into."""
        assert any(line.get("trace_id") == _INITIALIZE_TRACE for line in lines), (
            "initialize's traceparent never reached a log line, so this test proves nothing"
        )
        during_the_call = [
            line
            for line in lines
            if line.get("mcp_method") == "tools/call" or line.get("operation") == "get_me"
        ]
        assert during_the_call, "the tool call logged nothing"
        assert all(line.get("trace_id") == _TOOL_CALL_TRACE for line in during_the_call), [
            (line.get("msg"), line.get("trace_id")) for line in during_the_call
        ]

    def test_the_tool_call_really_ran(self, lines: Sequence[Mapping[str, object]]) -> None:
        """Guards every assertion above: a session that never called the tool would pass them."""
        assert any(line.get("operation") == "get_me" for line in lines), (
            "the operations layer logged no get_me call"
        )


class TestABootedServerHonoursTheLogContract:
    """The chart labels the pod `logging.unique.app/format: pino-json` and the pipeline reads
    stderr, so a plain-text line, or any line at all on stdout, is lost. Left to its default,
    uvicorn applies its own `dictConfig` after this service configured logging and writes access
    lines to stdout in plain text; `main.py` passes `log_config=None` to stop that.
    """

    def test_nothing_is_written_to_stdout(self, booted: "_BootedServer") -> None:
        assert booted.stdout == "", f"uvicorn wrote to stdout: {booted.stdout!r}"

    def test_every_line_is_pino_json(self, booted: "_BootedServer") -> None:
        for line in booted.stderr.splitlines():
            fields = cast("Mapping[str, object]", json.loads(line))
            assert isinstance(fields, dict), line
            assert {"level", "time", "msg", "context"} <= set(fields), line

    def test_uvicorns_own_lifecycle_lines_are_in_it(self, booted: "_BootedServer") -> None:
        contexts = {line["context"] for line in booted.lines}

        assert "uvicorn.error" in contexts, sorted(cast("set[str]", contexts))

    def test_the_access_line_is_in_it(self, booted: "_BootedServer") -> None:
        access = [line for line in booted.lines if line["context"] == "uvicorn.access"]

        assert access, "no access line was logged as pino-json"
        assert any("/nope" in cast("str", line["msg"]) for line in access), [
            line["msg"] for line in access
        ]

    def test_the_access_line_carries_no_credential(self, booted: "_BootedServer") -> None:
        """End to end: the filter is on the handler uvicorn now propagates to."""
        assert "opaque-query-secret" not in booted.stderr
        assert any(f"api-key={CENSORED}" in cast("str", line["msg"]) for line in booted.lines), [
            line["msg"] for line in booted.lines
        ]

    def test_the_probes_own_access_line_is_still_quiet(self, booted: "_BootedServer") -> None:
        """`unique_mcp` drops access lines for the ops routes, and routing uvicorn through the root
        handler keeps that filter in the path."""
        assert not [
            line
            for line in booted.lines
            if line["context"] == "uvicorn.access" and "/probe" in cast("str", line["msg"])
        ]

    def test_every_line_is_joinable(self, booted: "_BootedServer") -> None:
        for line in booted.lines:
            assert line.get("correlation_id"), line


def _install_tracer_provider() -> None:
    """The tracer provider is process-wide and can be set only once, so this reuses whichever
    provider is in play, the same shape `test_tracing.py` uses."""
    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        trace.set_tracer_provider(TracerProvider())


def _sdk_handle_request(source: str) -> ast.FunctionDef:
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
            and node.name == "_handle_request"
        ):
            return ast.FunctionDef(
                name=node.name,
                args=node.args,
                body=node.body,
                decorator_list=node.decorator_list,
                returns=node.returns,
                type_comment=None,
                type_params=[],
            )
    raise AssertionError(
        f"the MCP SDK no longer defines _handle_request in {inspect.getfile(sdk_server)}"
    )


def _is_the_sdk_line(statement: ast.stmt) -> bool:
    if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
        return False
    first = next(iter(statement.value.args), None)
    return isinstance(first, ast.Constant) and first.value == _SDK_LINE


@pytest.fixture(autouse=True)
def entra(monkeypatch: pytest.MonkeyPatch) -> None:
    """The exchange is refused rather than stubbed: a tool call must not reach the network, and a
    refused exchange still produces the whole set of log lines.
    """

    async def verify_token(_self: AzureProvider, token: str) -> AccessToken:
        return AccessToken(token=token, client_id=_CLIENT_ID, scopes=["access_as_user"])

    async def get_obo_credential(_self: AzureProvider, *, user_assertion: str) -> object:
        assert user_assertion, "the exchange was attempted without the caller's token"
        raise ClientAuthenticationError("AADSTS65001: the user has not consented")

    monkeypatch.setattr(AzureProvider, "verify_token", verify_token)
    monkeypatch.setattr(AzureProvider, "get_obo_credential", get_obo_credential)


@pytest.fixture
def app() -> Starlette:
    """Nothing here reaches Postgres, so the URL only has to parse."""
    return create_app(
        config=AppConfig.model_validate({"public_base_url": _PUBLIC_BASE_URL}),
        database_config=DatabaseConfig.model_validate(
            {"url": "postgresql://user:pass@127.0.0.1:1/nope"}
        ),
        entra_config=EntraConfig.model_validate(
            {"tenant_id": _TENANT_ID, "client_id": _CLIENT_ID, "client_secret": "s3cr3t"}
        ),
        surface_config=SurfaceConfig.model_validate({"tools_preset": ToolsPreset.TEAMS}),
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


def _drive_a_tool_call(app: Starlette, sink: _Sink) -> list[Mapping[str, object]]:
    """One MCP session over HTTP: initialize, then `tools/call` under a *different* trace."""
    _install_tracer_provider()
    with TestClient(app) as client:
        # Cleared after the lifespan, so the startup manifest is not read as one of these lines.
        _ = sink.stream.truncate(0)
        _ = sink.stream.seek(0)

        initialize = cast(
            "_HttpResponse",
            client.post(  # pyright: ignore[reportUnknownMemberType]
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                },
                headers=_headers(_INITIALIZE_TRACEPARENT),
            ),
        )
        assert initialize.status_code == 200, "initialize was refused"
        session = initialize.headers["mcp-session-id"]

        # Trap: post to "/mcp" and not to "/mcp/". The trailing slash redirects.
        called = cast(
            "_HttpResponse",
            client.post(  # pyright: ignore[reportUnknownMemberType]
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "get_me", "arguments": {}},
                },
                headers=_headers(_TOOL_CALL_TRACEPARENT, session),
            ),
        )
        assert called.status_code == 200, "the tool call was refused by the transport"

    return sink.lines()


@pytest.fixture
def lines(app: Starlette, sink: _Sink) -> list[Mapping[str, object]]:
    return _drive_a_tool_call(app, sink)


@pytest.fixture
def unquieted_lines(app: Starlette, sink: _Sink) -> Iterator[list[Mapping[str, object]]]:
    """The same session with `StaleMessageLineFilter` taken off the handler: the before."""
    installed = list(sink.handler.filters)
    sink.handler.filters = [
        existing for existing in installed if not isinstance(existing, StaleMessageLineFilter)
    ]
    try:
        yield _drive_a_tool_call(app, sink)
    finally:
        sink.handler.filters = installed


@dataclass(frozen=True)
class _BootedServer:
    stdout: str
    stderr: str

    @property
    def lines(self) -> list[Mapping[str, object]]:
        return [
            cast("Mapping[str, object]", json.loads(line))
            for line in self.stderr.splitlines()
            if line.strip()
        ]


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return cast("tuple[str, int]", probe.getsockname())[1]


@pytest.fixture(scope="module")
def booted(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_BootedServer]:
    """Run from an empty directory, because `main.py` calls `load_dotenv()` and a developer's
    `.env` would otherwise decide this test's configuration.
    """
    port = _free_port()
    source_root = pathlib.Path(__file__).parent.parent / "src"
    environment = {
        **os.environ,
        "PYTHONPATH": str(source_root),
        "PYTHONUNBUFFERED": "1",
        "APP_ENV": "development",
        "PORT": str(port),
        "PUBLIC_BASE_URL": f"http://127.0.0.1:{port}",
        "LOG_LEVEL": "info",
        "DB_URL": "postgresql://office:hunter2@127.0.0.1:1/nope",
        "ENTRA_TENANT_ID": _TENANT_ID,
        "ENTRA_CLIENT_ID": _CLIENT_ID,
        "ENTRA_CLIENT_SECRET": "s3cr3t",
        "TOOLS_PRESET": ToolsPreset.TEAMS.value,
    }
    server = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "office_365_mcp.main"],
        cwd=tmp_path_factory.mktemp("booted"),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        _wait_until_up(server, f"{base}/probe")
        _ = httpx.get(f"{base}/probe", timeout=5)
        _ = httpx.get(f"{base}/nope?api-key=opaque-query-secret", timeout=5)
    finally:
        server.terminate()
        stdout, stderr = server.communicate(timeout=30)

    yield _BootedServer(stdout=stdout, stderr=stderr)


def _wait_until_up(server: subprocess.Popen[str], probe: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.poll() is not None:
            stdout, stderr = server.communicate()
            raise AssertionError(f"the server exited before it served:\n{stderr}\n{stdout}")
        try:
            if httpx.get(probe, timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.2)
    raise AssertionError(f"{probe} never answered")
