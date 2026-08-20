"""What every log line this service writes must and must not carry.

Asserted through the **real** handler: `configure_logging` installs it, `unique_mcp`'s own pino
formatter renders it, and the only thing these tests change is where its stream points. That is
deliberate. The defects here are properties of a formatter this service does not own — it copies
every `extra=` into the payload, serialises whole exception stacks, and says nothing at all about a
line emitted with no span — so a test that formatted the records itself would assert against the
wrong opponent.
"""

import io
import json
import logging
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import IO, Protocol, cast

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from starlette.applications import Starlette
from starlette.testclient import TestClient
from unique_mcp.logging import _PinoJson  # pyright: ignore[reportPrivateUsage]

from office_mcp.app import create_app
from office_mcp.config import AppConfig, DatabaseConfig, EntraConfig, SurfaceConfig, ToolsPreset
from office_mcp.logging import CENSORED, TRUNCATED, RedactionFilter, configure_logging

_PUBLIC_BASE_URL = "https://office-mcp.example"
_TENANT_ID = "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81"
_CLIENT_ID = "1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061"

# A token-shaped string that is not a token: three base64url segments beginning `eyJ`, which is
# what every Entra and Graph JWT looks like on the wire.
_JWT = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJub2JvZHkifQ.c2lnbmF0dXJl"


class _HttpResponse(Protocol):
    """`starlette.testclient` returns httpx responses this repo's type checking sees as partial."""

    @property
    def status_code(self) -> int: ...
    @property
    def headers(self) -> Mapping[str, str]: ...


@dataclass(frozen=True)
class _Sink:
    """Everything the real handler wrote, as the JSON objects the log pipeline would receive."""

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
    """The handler `configure_logging` installed, found by the formatter upstream puts on it.

    Not found by this service's own filters, which is the obvious way and the wrong one:
    `configure_logging` installs those on *every* root handler, and under pytest there are five —
    which is the property `test_no_handler_escapes_the_filters` asserts. The pino formatter is what
    makes exactly one of them the one the pod's log pipeline reads.
    """
    handlers = [
        handler
        for handler in logging.getLogger().handlers
        if isinstance(handler.formatter, _PinoJson)
    ]
    assert len(handlers) == 1, (
        f"expected one handler with unique_mcp's pino formatter, found {len(handlers)}. "
        + "See unique_mcp.logging.configure_logging and src/office_mcp/logging.py"
    )
    return handlers[0]


@pytest.fixture
def sink() -> Iterator[_Sink]:
    """The real pino handler, writing where a test can read it.

    `configure_logging` is idempotent and process-wide — `create_app` calls it too — so this
    restores the stream and the root level rather than the handler: removing it would leave a
    later `create_app` in this session with no handler to reinstall.
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
    """One line, from a logger this service has never heard of.

    The name is the point: the filters are on the handler, so what redacts a line does not depend
    on which logger wrote it — a vendor module, a framework, or a name invented in a later release.
    """
    logging.getLogger("some.vendor.module").info(message, *args, extra=extra or None)


class TestNothingSecretReachesTheLog:
    """The first net is the field name, the second is the value's shape, and both are needed.

    Every vector here is one the TypeScript reference redacts
    (`packages/logger/src/options.ts:22-34`) or one this service reaches on its own.
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
        """The reference lists four spellings of two header names as four redact paths. A fifth
        spelling is what "bypassed by a differently-named key" means, so the name is matched with
        its separators removed rather than compared to a list."""
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
        _log("request", headers=[(b"host", b"office-mcp"), (b"authorization", b"Bearer opaque")])

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
        """The second net. A token reaches this service on every request, and the field it ends up
        in is not always one a name check would suspect — an httpx exception's `repr` of the
        request it failed to send is a string, and this is that string."""
        _log("failed", detail=f"<Request headers={{'authorization': 'Bearer {_JWT}'}}>")

        assert CENSORED in cast("str", sink.one()["detail"])
        assert _JWT not in cast("str", sink.one()["detail"])

    def test_a_bare_jwt_in_a_value_is_censored(self, sink: _Sink) -> None:
        _log("exchanged", assertion_result=_JWT)

        assert sink.one()["assertion_result"] == CENSORED

    def test_a_token_interpolated_into_the_message_is_censored(self, sink: _Sink) -> None:
        """`%s` of a token is a token, and the message is not an attribute the name check sees."""
        _log("retrying with %s", f"Bearer {_JWT}")

        message = cast("str", sink.one()["msg"])
        assert message == f"retrying with Bearer {CENSORED}", message

    def test_a_credential_in_a_query_string_is_censored(self, sink: _Sink) -> None:
        """`req.query["api-key"]` in the reference. uvicorn's access line quotes the path with its
        query string, so this is about a line this service now emits itself."""
        _log('127.0.0.1:1 - "GET /mcp?api-key=opaque-value&page=2 HTTP/1.1" 200')

        message = cast("str", sink.one()["msg"])
        assert f"api-key={CENSORED}&page=2" in message, message

    def test_a_password_in_a_url_is_censored(self, sink: _Sink) -> None:
        """Reachable today: `server/readiness.py` logs the store's failure with `exc_info=True`,
        and asyncpg quotes the DSN it could not reach."""
        _log("unreachable", dsn="postgresql://office:hunter2@db.internal:5432/office")

        assert sink.one()["dsn"] == f"postgresql://{CENSORED}@db.internal:5432/office"

    def test_an_exception_stack_is_censored(self, sink: _Sink) -> None:
        """The formatter serialises the whole chain into `err.stack`, so the whole chain is a
        vector. The three keys it would have written are still the three keys here."""
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

    def test_the_callers_own_dictionary_is_not_touched(self, sink: _Sink) -> None:
        """Redaction rebuilds; it does not edit. The caller is still holding these headers and
        still going to send them, so censoring in place would corrupt the request the line is
        about."""
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
        """Stated as its own assertion because everything above depends on it. `Handler.handle`
        filters and only then emits, so the bytes the formatter produced are the proof: a filter
        that ran after it would have censored nothing that reached this stream."""
        _log("outbound", authorization=f"Bearer {_JWT}")

        assert _JWT not in sink.stream.getvalue()


class TestNoHandlerLeavesByAnotherDoor:
    """Redaction on the handler only holds while every handler carries it."""

    @pytest.mark.usefixtures("sink")
    def test_no_handler_escapes_the_filters(self) -> None:
        """Every root handler, not only the pino one. A second handler is a second way out, and
        redaction that covers one of two is redaction that does not hold."""
        for handler in logging.getLogger().handlers:
            installed = {type(existing) for existing in handler.filters}
            assert RedactionFilter in installed, f"{handler} has no redaction filter"


class TestEveryLineIsJoinable:
    """A line nothing can group is a line nobody reads. `teams-mcp` generates an id when there is
    no span for the same reason (`services/teams-mcp/src/app.module.ts:73-79`)."""

    def test_a_line_with_no_span_and_no_request_still_carries_an_id(self, sink: _Sink) -> None:
        """Startup, the tool-surface manifest, a readiness warning: no span, no request. The id is
        this process's boot, which is what makes one pod's startup a group instead of a pile."""
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
        """The mechanism has to work outside any MCP call. `/ready` is a plain HTTP route, and with
        tracing off there is no span on it either — so the id comes from the ASGI middleware."""
        with TestClient(app) as client:
            sink.stream.truncate(0)
            _ = sink.stream.seek(0)
            response = cast("_HttpResponse", client.get("/ready"))  # pyright: ignore[reportUnknownMemberType]

        assert response.status_code in (200, 503), "the probe answered neither way"
        warnings = [
            line for line in sink.lines() if line["context"] == "office_mcp.server.readiness"
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


# ------------------------------------------------------------------------------------------------
# Fixtures and helpers
# ------------------------------------------------------------------------------------------------


def _install_tracer_provider() -> None:
    """Make span contexts valid. A provider can only be installed once per process, so this reuses
    whichever one is already in play — the same shape `test_tracing.py` uses."""
    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        trace.set_tracer_provider(TracerProvider())


@pytest.fixture
def app() -> Starlette:
    """The real app. Nothing here reaches Postgres, so the URL only has to parse."""
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
