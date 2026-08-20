"""What every log line this service writes must not carry.

Asserted through the **real** handler: `configure_logging` installs it, `unique_mcp`'s own pino
formatter renders it, and the only thing these tests change is where its stream points. That is
deliberate. The defect here is a property of a formatter this service does not own — it copies
every `extra=` into the payload and serialises whole exception stacks — so a test that formatted the
records itself would assert against the wrong opponent.
"""

import io
import json
import logging
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import IO, cast

import pytest
from unique_mcp.logging import _PinoJson  # pyright: ignore[reportPrivateUsage]

from office_mcp.config import AppConfig
from office_mcp.logging import CENSORED, TRUNCATED, RedactionFilter, configure_logging

_PUBLIC_BASE_URL = "https://office-mcp.example"

# A token-shaped string that is not a token: three base64url segments beginning `eyJ`, which is
# what every Entra and Graph JWT looks like on the wire.
_JWT = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJub2JvZHkifQ.c2lnbmF0dXJl"


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
