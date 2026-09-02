"""Structured logging on `unique_mcp.logging`'s pino-json formatter, corrected by handler filters.

That formatter renders the format the chart's `logging.unique.app/format: pino-json` pod label
promises the log pipeline. It copies every non-reserved `LogRecord` attribute into the payload and
serialises the whole `exc_info` chain into `err.stack`, so secrets leak from `extra=` and from
exceptions. The correction must sit on the *handler*: `Handler.handle` filters before it formats,
and a handler's filters see every record it emits, whatever logger produced it. A filter on a
logger sees only that logger's own records.

These filters mutate the record they are given, against the house rule on arguments: a
`logging.Filter` has no other return path, and the record is a per-emit object the caller does not
keep. Anything the caller still owns is rebuilt rather than edited.
"""

import logging
import re
import traceback
import uuid
from collections.abc import Iterable, Mapping, Sequence
from contextvars import ContextVar
from types import TracebackType
from typing import cast, override

from fastmcp.server.dependencies import get_context, get_http_request
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from opentelemetry import trace
from unique_mcp.logging import configure_logging as configure_pino_logging

from office_365_mcp.asgi import ASGIApp, ASGIReceive, ASGIScope, ASGISend
from office_365_mcp.config import AppConfig

__all__ = [
    "CENSORED",
    "TRUNCATED",
    "UNPRINTABLE",
    "ColorMessageFilter",
    "HttpRequestIdMiddleware",
    "MessageLogMiddleware",
    "RedactionFilter",
    "StaleMessageLineFilter",
    "configure_logging",
]

logger = logging.getLogger(__name__)

# Spelled as `packages/logger/src/options.ts` spells it, so one grep finds both stacks' redactions.
CENSORED = "[Redacted]"


# Matched as substrings, so `entra_client_secret` and `graph_access_token` are covered and the cost
# is a false positive like `token_count`.
# Trap: `auth` is deliberately NOT a marker. It matches `author`, and a Teams message has one.
_SENSITIVE_MARKERS: tuple[str, ...] = (
    "apikey",
    "assertion",
    "authorization",
    "cookie",
    "credential",
    "passwd",
    "password",
    "privatekey",
    "secret",
    "token",
)

_NOT_ALPHANUMERIC = re.compile(r"[^a-z0-9]")

_CREDENTIAL_SHAPES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9\-._~+/=]{8,}"), r"\1 " + CENSORED),
    # A bare JWT: `eyJ` is base64url of `{"`, so every Entra and Graph token starts with it.
    (re.compile(r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]*"), CENSORED),
    # `scheme://user:password@host`: `server/readiness.py` logs a store failure with
    # `exc_info=True`, and asyncpg quotes the DSN it failed to reach.
    (re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^\s:/@]+:[^\s/@]+@"), r"\1" + CENSORED + "@"),
    # A credential in a query string, which is the vector the reference calls
    # `req.query["api-key"]`. uvicorn's access line quotes the path *with* its query string, so
    # this one is about a line this service now emits itself.
    #
    # `code` is matched as a whole parameter name and the rest as substrings, because the OAuth
    # callback's credential is spelled exactly `code` — `GET /auth/callback?code=...`, which
    # upstream's `_SKIP_PATHS` does not quiet — while `postcode` and `encoding` merely contain it.
    #
    # Trap: this alternation is hand-written and must stay that way. `_SENSITIVE_MARKERS` is
    # matched against names with every separator *removed*, this pattern against raw URL text, so
    # rebuilding one from the other stops `?api-key=` being redacted.
    (
        re.compile(
            r"(?i)([?&](?:[A-Za-z0-9_.%\[\]-]*(?:token|key|secret|password|auth)"
            + r"[A-Za-z0-9_.%\[\]-]*|code)=)[^&\s\"']+"
        ),
        r"\1" + CENSORED,
    ),
)

# Trap: at the cap the container must be replaced, not passed through. An ASGI scope can contain
# itself, and a cycle in the payload makes `json.dumps` raise. `logging` swallows that exception and
# drops the line entirely.
_MAX_DEPTH = 5
TRUNCATED = "[Truncated]"

# What stands in for a value whose own `str` raised. Distinct from `TRUNCATED`, which says the
# structure went deeper than redaction walks, and from `CENSORED`, which says a secret was there.
UNPRINTABLE = "[Unprintable]"

# The record attributes the upstream formatter never copies into the payload, computed the way it
# computes them so the two cannot drift. `msg`, `args` and `exc_info` are in here and are handled
# explicitly in `RedactionFilter` instead: they do reach the payload, through `getMessage()` and
# through `err`, just not by being copied.
_NEVER_IN_THE_PAYLOAD = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message"
}

# The formatter builds this from `exc_info`, and skips building it when the record already carries a
# dict here — the seam a redacted exception goes through.
_ERR_FIELD = "err"


def _as_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _rendered_text(value: object) -> str | None:
    """`value` as text, or `None` when rendering it raised.

    Every string a record carries can be one a dependency's own `__str__` or `__repr__` produces,
    and a `logging.Filter` that raises raises out of the `logger.info(...)` call that built the
    record: `Handler.handle` runs its filters *outside* the `handleError` guard that covers `emit`.
    So a `__str__` this service does not own must not turn one log line into the caller's exception,
    and the `except` clause is broad because a log filter must not propagate any exception.

    Nothing is lost by giving up here: the upstream formatter also fails on the same object, since
    it serialises with `json.dumps(..., default=str)`.
    """
    try:
        return _as_text(value)
    except Exception:
        return None


def _is_sensitive(name: object) -> bool:
    text = _rendered_text(name)
    if text is None:
        # A name that cannot be read is a decision that cannot be made, and the safe half of it is
        # to censor: the name is what decides whether the value is logged at all.
        return True
    normalised = _NOT_ALPHANUMERIC.sub("", text.lower())
    return any(marker in normalised for marker in _SENSITIVE_MARKERS)


def _censor_text(text: str) -> str:
    censored = text
    for pattern, replacement in _CREDENTIAL_SHAPES:
        censored = pattern.sub(replacement, censored)
    return censored


def _censor_bytes(value: bytes) -> bytes:
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError:
        return value
    censored = _censor_text(text)
    return censored.encode("utf-8") if censored != text else value


def _redact(value: object, depth: int = 0) -> object:
    """Secrets removed, as **new** data: a caller who passed `extra={"headers": headers}` is still
    holding that dict and still going to send it."""
    if isinstance(value, str):
        return _censor_text(value)
    if isinstance(value, bytes):
        return _censor_bytes(value)
    if isinstance(value, Mapping):
        if depth >= _MAX_DEPTH:
            return TRUNCATED
        entries = cast("Mapping[object, object]", value)
        return {
            _key_text(key): CENSORED if _is_sensitive(key) else _redact(item, depth + 1)
            for key, item in entries.items()
        }
    if isinstance(value, list | tuple | set | frozenset):
        if depth >= _MAX_DEPTH:
            return TRUNCATED
        members = cast("Iterable[object]", value)
        return [_redact_member(member, depth + 1) for member in members]
    return value


def _redacted_object_text(value: object) -> str:
    """One object as censored text, or a placeholder when it cannot be rendered at all."""
    text = _rendered_text(value)
    return UNPRINTABLE if text is None else _censor_text(text)


def _key_text(key: object) -> str:
    """A mapping key as the payload field name it becomes.

    A key whose own `str` raised has no name to be logged under. It keeps its value's censoring,
    because `_is_sensitive` reads the same key and treats an unreadable one as sensitive.
    """
    text = _rendered_text(key)
    return UNPRINTABLE if text is None else text


def _redact_member(member: object, depth: int) -> object:
    """`scope["headers"]` is a list of `(name, value)` byte pairs, not a dict. Without pairing them,
    the name half is seen and the value half is logged."""
    pair = _sensitive_pair(member)
    if pair is not None:
        return [_redact(pair[0], depth + 1), CENSORED]
    return _redact(member, depth)


def _sensitive_pair(member: object) -> Sequence[object] | None:
    if not isinstance(member, list | tuple):
        return None
    pair = cast("Sequence[object]", member)
    return pair if len(pair) == 2 and _is_sensitive(pair[0]) else None


def _rendered_message(record: logging.LogRecord) -> str | None:
    """The record's interpolated message, or `None` when it cannot be interpolated at all.

    The one rendering in this filter that fails with no hostile object anywhere near it: a
    `%`-template and the arguments meant to fill it are written in two places, and
    `logger.info("progress: 100%", 1)` raises `ValueError: incomplete format`. Stdlib survives that
    — the same failure inside `emit` is what `handleError` writes its stderr note about — and a
    filter installed on the root handler must not do worse to a mistake in uvicorn, kiota, asyncpg
    or msal than stdlib does, least of all inside their own `except: logger.exception(...)`.
    """
    try:
        return record.getMessage()
    except Exception:
        return None


def _redacted_stack(
    exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None
) -> str:
    """The whole exception chain as censored text, or a placeholder when formatting it raised.

    Guarded separately from the exception's own `str` because it is a separate call into code this
    service does not own, not because it is likelier to fail: `traceback` wraps each `str` it needs
    itself and renders a raising one as `<exception str() failed>`, where `str(exc)` above
    propagates. What is left is everything else formatting a chain touches — the tracebacks, the
    notes, each frame's source line — and this guard makes sure that none of it raises out of a
    filter.
    """
    try:
        formatted = "".join(traceback.format_exception(exc_type, exc, tb))
    except Exception:
        return UNPRINTABLE
    return _censor_text(formatted)


class RedactionFilter(logging.Filter):
    """Take the secrets out of a record before the formatter can serialise them.

    Two independent nets, name and value shape, because neither alone holds. What gets through both
    is a secret with an innocent name and no recognizable shape.
    """

    @override
    def filter(self, record: logging.LogRecord) -> bool:
        attributes = cast("Mapping[str, object]", record.__dict__)
        for key, value in list(attributes.items()):
            if key in _NEVER_IN_THE_PAYLOAD or key.startswith("_"):
                continue
            setattr(record, key, CENSORED if _is_sensitive(key) else _redact(value))

        rendered = _rendered_message(record)
        if rendered is None:
            # Nothing has censored this pair, so this filter must not let it leave the process. The
            # formatter cannot interpolate it either, and its failure lands in
            # `Handler.handleError`, which writes `record.msg` and `record.args` to stderr
            # verbatim — un-redacted, and outside the pino stream. So the template is kept as
            # censored text and the args dropped.
            record.msg = _redacted_object_text(record.msg)
            record.args = None
        elif (censored := _censor_text(rendered)) != rendered:
            # The args are dropped with the template they filled: the censored text is already
            # interpolated, and `%`-formatting the same text a second time fails on its own
            # literals.
            record.msg = censored
            record.args = None
        # A clean message keeps its template and args, which the formatter then interpolates a
        # second time — so an argument whose `__str__` returns something different on that second
        # call reaches the payload as text nothing censored. Unclosable from a filter: the only
        # rendering a filter can censor is its own.

        exc_type, exc, tb = record.exc_info or (None, None, None)
        already_given = attributes.get(_ERR_FIELD)
        if exc_type is not None and exc is not None and not isinstance(already_given, dict):
            # The same three keys the upstream formatter writes, so nothing reading `err.stack`
            # notices which of us built it. Writing them here also stops the formatter from
            # building them itself, from an exception that either rendering above can fail on.
            setattr(
                record,
                _ERR_FIELD,
                {
                    "name": exc_type.__name__,
                    "message": _redacted_object_text(exc),
                    "stack": _redacted_stack(exc_type, exc, tb),
                },
            )
        return True


_CORRELATION_FIELD = "correlation_id"
_REQUEST_FIELD = "request_id"
_SESSION_FIELD = "session_id"
_HTTP_REQUEST_FIELD = "http_request_id"

# Last resort: the only id a line emitted before any request can have. One per process boot.
_BOOT_ID = f"boot-{uuid.uuid4().hex}"

_http_request_id: ContextVar[str | None] = ContextVar(
    "office_365_mcp_http_request_id", default=None
)

# A gateway's own id, preferred so both systems' logs join. Capped: it is attacker-controlled.
_FORWARDED_REQUEST_ID_HEADER = b"x-request-id"
_MAX_FORWARDED_REQUEST_ID = 128


def _mcp_request_id() -> str | None:
    try:
        return get_context().request_id
    except Exception:
        # Broad on purpose: this function must not let an exception propagate out of a log filter.
        return None


def _mcp_session_id() -> str | None:
    """Read from the header, not `Context.session_id`. That property mints and memoises a uuid of
    its own when a session has none, as `initialize` has none, and reports an id the transport
    never knew."""
    try:
        return get_http_request().headers.get("mcp-session-id")
    except Exception:
        return None


def _correlation_id(request_id: str | None) -> str:
    """Fallback order, widest scope first: trace, MCP message, HTTP request, process boot."""
    span = trace.get_current_span().get_span_context()
    if span.is_valid:
        return format(span.trace_id, "032x")
    if request_id is not None:
        return f"mcp-{request_id}"
    forwarded = _http_request_id.get()
    return forwarded if forwarded is not None else _BOOT_ID


class CorrelationFilter(logging.Filter):
    """Give every line an id that groups it with the rest of its request.

    The formatter adds `trace_id` only while a span is recording, so without this a line logged with
    tracing off cannot be grouped at all. Same fallback as
    `services/teams-mcp/src/app.module.ts:73-79`.
    """

    @override
    def filter(self, record: logging.LogRecord) -> bool:
        request_id = _mcp_request_id()
        if request_id is not None and _REQUEST_FIELD not in record.__dict__:
            setattr(record, _REQUEST_FIELD, request_id)
        session_id = _mcp_session_id()
        if session_id is not None and _SESSION_FIELD not in record.__dict__:
            setattr(record, _SESSION_FIELD, session_id)
        # Also its own field: a trace id outranks it in `_correlation_id`, so this field is the
        # only place it shows when tracing is on.
        http_request_id = _http_request_id.get()
        if http_request_id is not None and _HTTP_REQUEST_FIELD not in record.__dict__:
            setattr(record, _HTTP_REQUEST_FIELD, http_request_id)
        if _CORRELATION_FIELD not in record.__dict__:
            setattr(record, _CORRELATION_FIELD, _correlation_id(request_id))
        return True


class HttpRequestIdMiddleware:
    """Mint an id for every HTTP request, for lines with no span or MCP message. Mount outermost.

    Trap: the contextvar is set and never reset. That is what puts the id on uvicorn's access line,
    written after the app returns but inside the same task, whose context dies with it. The
    streamable-HTTP session task does inherit the `initialize` request's id, so `_correlation_id`
    prefers the per-message MCP request id.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app: ASGIApp = app

    async def __call__(self, scope: ASGIScope, receive: ASGIReceive, send: ASGISend) -> None:
        if scope.get("type") == "http":
            _ = _http_request_id.set(_request_id(scope))
        await self._app(scope, receive, send)


def _request_id(scope: ASGIScope) -> str:
    forwarded = _forwarded_request_id(scope)
    return forwarded if forwarded is not None else f"req-{uuid.uuid4().hex}"


def _forwarded_request_id(scope: ASGIScope) -> str | None:
    raw = scope.get("headers")
    if not isinstance(raw, Iterable):
        return None
    headers: Iterable[object] = raw
    for header in headers:
        if not isinstance(header, list | tuple):
            continue
        pair = cast("Sequence[object]", header)
        if len(pair) != 2 or pair[0] != _FORWARDED_REQUEST_ID_HEADER:
            continue
        value = _as_text(pair[1]).strip()
        if value:
            return value[:_MAX_FORWARDED_REQUEST_ID]
    return None


# `mcp/server/lowlevel/server.py`, in `_handle_request`, immediately before the request handler —
# which is where FastMCP's whole middleware chain lives. Matched on the template, a literal in that
# file. A drift guard in `tests/test_logging.py` reads it back out of the SDK and fails if it moved.
_SDK_MESSAGE_LOGGER = "mcp.server.lowlevel.server"
_SDK_PER_MESSAGE_LINE = "Processing request of type %s"


class StaleMessageLineFilter(logging.Filter):
    """Drop the SDK's per-message line, the one line that cannot carry the right trace id.

    It is emitted inside the session task before any middleware of ours, so it is formatted under
    the OpenTelemetry context that task snapshotted at `initialize`, for the session's whole life.
    `tracing.py` says why that cannot be corrected from inside the task. `MessageLogMiddleware`
    emits the replacement.
    """

    @override
    def filter(self, record: logging.LogRecord) -> bool:
        return not (record.name == _SDK_MESSAGE_LOGGER and record.msg == _SDK_PER_MESSAGE_LINE)


class MessageLogMiddleware(Middleware):
    """One line per MCP message, in the trace of the request that carried it.

    Mount inside `TraceContextRestoreMiddleware`. Outside it, this line is the defect it replaces.
    """

    @override
    async def on_message(
        self,
        context: MiddlewareContext[object],
        call_next: CallNext[object, object],
    ) -> object:
        method = context.method or "unknown"
        logger.info(
            "processing %s %s",
            context.type,
            method,
            extra={"mcp_method": method, "mcp_type": context.type},
        )
        return await call_next(context)


# uvicorn puts an ANSI copy of the line in `extra` for its own formatter. The pino formatter copies
# every extra, so uncorrected, each uvicorn lifecycle line carries its message twice.
_COLOR_MESSAGE_FIELD = "color_message"


class ColorMessageFilter(logging.Filter):
    @override
    def filter(self, record: logging.LogRecord) -> bool:
        if _COLOR_MESSAGE_FIELD in record.__dict__:
            delattr(record, _COLOR_MESSAGE_FIELD)
        return True


# `fastmcp/__init__.py:22-26` configures its own logger at import time — `RichHandler`s on stderr
# plus `propagate = False` — so every `fastmcp.*` line skips the pino formatter and every filter
# above. Reclaimed by removing those handlers rather than via `FASTMCP_LOG_ENABLED`, which is read
# when `fastmcp` is imported and so is already too late.
_RECLAIMED_LOGGERS: tuple[str, ...] = ("fastmcp",)


def _reclaim(name: str) -> None:
    reclaimed = logging.getLogger(name)
    for handler in list(reclaimed.handlers):
        reclaimed.removeHandler(handler)
    reclaimed.propagate = True


# Order is the order they run in: drop first, so nothing is identified or redacted for nothing.
_FILTERS: tuple[type[logging.Filter], ...] = (
    StaleMessageLineFilter,
    ColorMessageFilter,
    CorrelationFilter,
    RedactionFilter,
)


def _install_filters(handler: logging.Handler) -> None:
    """Put this service's filters on one handler, once. Idempotent, like `configure_logging`."""
    for filter_type in _FILTERS:
        if not any(isinstance(existing, filter_type) for existing in handler.filters):
            handler.addFilter(filter_type())


def configure_logging(config: AppConfig) -> None:
    configure_pino_logging(level=config.log_level.value.upper())
    # Python warnings otherwise reach stderr as plain text the log pipeline cannot parse, and this
    # service's dependencies emit them on every boot.
    logging.captureWarnings(True)
    for name in _RECLAIMED_LOGGERS:
        _reclaim(name)
    # Every root handler: a second handler is a second way out, and partial redaction does not hold.
    for handler in logging.getLogger().handlers:
        _install_filters(handler)
