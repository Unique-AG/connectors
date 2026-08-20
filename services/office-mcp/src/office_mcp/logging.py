"""Structured logging: `unique_mcp`'s pino-json contract, and what it does not do on its own.

`unique_mcp.logging.configure_logging` owns the format — one `StreamHandler` on stderr whose
formatter renders a pino-json object, which is what the chart's `logging.unique.app/format:
pino-json` pod label promises the log pipeline. That formatter is upstream code this service does
not own, and it does two things this service has to live with:

* it copies **every** non-reserved `LogRecord` attribute into the payload, so anything a caller
  passes as `extra=` is logged verbatim — a header map, a config object, a DSN;
* it serialises the whole exception chain of `exc_info` into `err.stack`, so anything carried on an
  exception is logged verbatim too.

Neither is fixable where the log call is written: the leak is a property of the formatter, not of
the caller. So the correction is a `logging.Filter` on the handler, which is the one seam that sits
between a record and that formatter. `logging.Handler.handle` calls `self.filter(record)` and only
then `self.emit(record)` → `self.format(record)`, so a filter here runs **before** the formatter,
every time, for every record that handler emits — and a handler's filters do not care which logger
produced the record, so no logger name and no `propagate = False` can slip past one. A filter on a
*logger* would have both holes: it would see only that logger's own records, and none from its
children.

Design decision: these filters mutate the record they are given, which the house rule against
mutating arguments would otherwise forbid. A `logging.Filter` has no return path other than the
record — the stdlib documents "modify the record in-place" as what a filter is for — and the record
is a per-emit object the caller does not keep. What is *not* mutated is anything the caller still
owns: a dict passed as `extra=` is rebuilt rather than edited in place, so redaction never reaches
back into the header map the caller is still using. See `_redact`.

Four filters, each for one defect, installed in this order:

`StaleMessageLineFilter` drops the MCP SDK's own per-message INFO line. See its docstring: that line
is emitted before any middleware of ours can run, so it is the one line in a tool call that carries
the wrong trace id, and `MessageLogMiddleware` below emits a strictly more informative replacement
in the right one.

`ColorMessageFilter` drops uvicorn's `color_message` extra. uvicorn's own lifecycle lines carry the
message a second time with ANSI escapes in it, for a formatter this service does not use.

`CorrelationFilter` gives every line something joinable — a trace id, an MCP request id, an HTTP
request id, or failing all three the id of this process's boot. See its docstring.

`RedactionFilter` is the redaction, by field name and by value shape. See its docstring.
"""

import logging
import re
import traceback
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping, MutableMapping, Sequence
from contextvars import ContextVar
from typing import cast, override

from fastmcp.server.dependencies import get_context, get_http_request
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from opentelemetry import trace
from unique_mcp.logging import configure_logging as configure_pino_logging

from office_mcp.config import AppConfig

__all__ = [
    "CENSORED",
    "TRUNCATED",
    "ColorMessageFilter",
    "CorrelationFilter",
    "HttpRequestIdMiddleware",
    "MessageLogMiddleware",
    "RedactionFilter",
    "StaleMessageLineFilter",
    "configure_logging",
    "install_filters",
]

# Local ASGI aliases rather than Starlette's, for the reason `tracing.py` gives at the same place:
# Starlette spells `Scope` as `MutableMapping[str, Any]`, and every read off it is then an `Any`
# this service's type checking rejects.
type ASGIScope = MutableMapping[str, object]
type ASGIMessage = MutableMapping[str, object]
type ASGIReceive = Callable[[], Awaitable[ASGIMessage]]
type ASGISend = Callable[[ASGIMessage], Awaitable[None]]
type ASGIApp = Callable[[ASGIScope, ASGIReceive, ASGISend], Awaitable[None]]

logger = logging.getLogger(__name__)

# What replaces a secret, spelled exactly as `packages/logger/src/options.ts` spells it, so one
# grep over a mixed Node-and-Python deployment's logs finds every redaction in both.
CENSORED = "[Redacted]"


# --------------------------------------------------------------------------------------------
# Redaction
# --------------------------------------------------------------------------------------------

# A field whose *name* contains one of these never has its value logged. Matched on the name with
# every separator removed and folded to lower case, so `Authorization`, `x-api-key`, `X_API_KEY`,
# `apiKey` and `api key` are all one marker — the TypeScript reference lists four spellings of two
# of those as four separate redact paths, and a fifth spelling is what a differently-named key is.
#
# Substrings rather than whole names on purpose: `entra_client_secret` and `graph_access_token` are
# the names this service would actually reach for, and neither is in any list of exact header names.
# The cost is a false positive on a field whose name merely contains one — `token_count` would be
# censored — which is the right way round for a log line.
#
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

# The second net, and the one that does not depend on a name at all: a value shaped like a
# credential is censored wherever it appears — in a message, in a field, in an exception's stack.
# A bearer token reaches this service on every single request, so the shape is not hypothetical, and
# the places it turns up are places no key name covers: an httpx exception's `repr` of the request,
# a Graph SDK error quoting the header it sent, an access line quoting the query string.
_CREDENTIAL_SHAPES: tuple[tuple[re.Pattern[str], str], ...] = (
    # An `Authorization` header's own shape. The scheme word is kept, so a line still says which
    # kind of credential was there.
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9\-._~+/=]{8,}"), r"\1 " + CENSORED),
    # A bare JWT, which is what every Entra and Graph token is: three dot-separated base64url
    # segments whose first one always begins `eyJ` ('{"' encoded).
    (re.compile(r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]*"), CENSORED),
    # `scheme://user:password@host`. Reachable today: `server/readiness.py` logs the store's
    # connection failure with `exc_info=True`, and asyncpg quotes the DSN it could not reach.
    (re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^\s:/@]+:[^\s/@]+@"), r"\1" + CENSORED + "@"),
    # A credential in a query string, which is the vector the reference calls
    # `req.query["api-key"]`. uvicorn's access line quotes the path *with* its query string, so
    # this one is about a line this service now emits itself.
    (
        re.compile(
            r"(?i)([?&][A-Za-z0-9_.%\[\]-]*(?:token|key|secret|password|auth)"
            + r"[A-Za-z0-9_.%\[\]-]*=)[^&\s\"']+"
        ),
        r"\1" + CENSORED,
    ),
)

# How deep into a structure passed as `extra=` redaction walks, and what stands in for what is
# below that. A log line is not a data structure and nothing sane nests further.
#
# Trap: the cap has to replace the container rather than pass it through. An ASGI scope can contain
# itself, and handing the original back at the cap would put the cycle straight into the payload —
# where `json.dumps` raises, `logging` swallows the error, and the line is lost entirely. That is
# what happens today to any cyclic `extra=`.
_MAX_DEPTH = 5
TRUNCATED = "[Truncated]"

# The record attributes the upstream formatter never copies into the payload, computed the way it
# computes them so the two cannot drift. `msg`, `args` and `exc_info` are in here and are handled
# explicitly in `RedactionFilter` instead: they do reach the payload, through `getMessage()` and
# through `err`, just not by being copied.
_NEVER_IN_THE_PAYLOAD = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message"
}

# The field the upstream formatter builds from `exc_info` — and skips building when the record
# already carries a dict under it, which is the seam a redacted exception goes through.
_ERR_FIELD = "err"


def _as_text(value: object) -> str:
    """A field name as text. ASGI spells a header name as bytes, and bytes is not `str`."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _is_sensitive(name: object) -> bool:
    normalised = _NOT_ALPHANUMERIC.sub("", _as_text(name).lower())
    return any(marker in normalised for marker in _SENSITIVE_MARKERS)


def _censor_text(text: str) -> str:
    """Every credential shape in one string, replaced. Returns the string itself when clean."""
    censored = text
    for pattern, replacement in _CREDENTIAL_SHAPES:
        censored = pattern.sub(replacement, censored)
    return censored


def _censor_bytes(value: bytes) -> bytes:
    """The same, for the bytes ASGI hands out. Undecodable bytes carry no credential we can read."""
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError:
        return value
    censored = _censor_text(text)
    return censored.encode("utf-8") if censored != text else value


def _redact(value: object, depth: int = 0) -> object:
    """A logged value with its secrets removed, as **new** data.

    Nothing here is edited in place. A caller who passes `extra={"headers": headers}` is still
    holding that dict and still going to send it: redacting it in place would corrupt the request
    the log line is about.
    """
    if isinstance(value, str):
        return _censor_text(value)
    if isinstance(value, bytes):
        return _censor_bytes(value)
    if isinstance(value, Mapping):
        if depth >= _MAX_DEPTH:
            return TRUNCATED
        entries = cast("Mapping[object, object]", value)
        return {
            _as_text(key): CENSORED if _is_sensitive(key) else _redact(item, depth + 1)
            for key, item in entries.items()
        }
    if isinstance(value, list | tuple | set | frozenset):
        if depth >= _MAX_DEPTH:
            return TRUNCATED
        members = cast("Iterable[object]", value)
        # A list, whatever came in: a log payload is JSON, where every sequence is one anyway, and
        # rebuilding the original type is not possible for a namedtuple or a frozen set of tuples.
        return [_redact_member(member, depth + 1) for member in members]
    return value


def _redact_member(member: object, depth: int) -> object:
    """One member of a sequence, read as a name/value pair when it looks like one.

    A two-element sequence whose first element is a sensitive name is how a header map arrives when
    it is not a dict: `scope["headers"]` is a list of `(name, value)` byte pairs, and
    `list(headers.items())` is the same shape. Without this, the name half would be seen and the
    value half would be logged.
    """
    pair = _sensitive_pair(member)
    if pair is not None:
        return [_redact(pair[0], depth + 1), CENSORED]
    return _redact(member, depth)


def _sensitive_pair(member: object) -> Sequence[object] | None:
    """A two-element sequence whose first element names a secret, or `None`."""
    if not isinstance(member, list | tuple):
        return None
    pair = cast("Sequence[object]", member)
    return pair if len(pair) == 2 and _is_sensitive(pair[0]) else None


class RedactionFilter(logging.Filter):
    """Take the secrets out of a record before the formatter can serialise them.

    Three ways in, because the formatter has three ways out:

    * every attribute the formatter copies — by name (`Authorization`, `x-api-key`, `client_secret`,
      however it is spelled) and by value shape, recursively, so a header map nested inside an
      `extra=` is reached;
    * the rendered message, because `%s` of a token is a token;
    * the exception, whose `str` and whose whole formatted stack are censored into the `err` field
      the formatter would otherwise build itself.

    What this cannot see is a secret with an innocent name and no recognisable shape — an opaque
    api-key logged as `extra={"handle": ...}`. That is the reason for two independent nets rather
    than one: a value that looks like a credential is caught under any name, and a field named for a
    credential is caught whatever its value looks like.
    """

    @override
    def filter(self, record: logging.LogRecord) -> bool:
        attributes = cast("Mapping[str, object]", record.__dict__)
        for key, value in list(attributes.items()):
            if key in _NEVER_IN_THE_PAYLOAD or key.startswith("_"):
                continue
            setattr(record, key, CENSORED if _is_sensitive(key) else _redact(value))

        rendered = record.getMessage()
        censored = _censor_text(rendered)
        if censored != rendered:
            # The args are dropped with the template they filled: the censored text is already
            # interpolated, and `%`-formatting it a second time would fail on its own literals.
            record.msg = censored
            record.args = None

        exc_type, exc, tb = record.exc_info or (None, None, None)
        already_given = attributes.get(_ERR_FIELD)
        if exc_type is not None and exc is not None and not isinstance(already_given, dict):
            # The same three keys the upstream formatter writes, so nothing reading `err.stack`
            # notices which of us built it.
            setattr(
                record,
                _ERR_FIELD,
                {
                    "name": exc_type.__name__,
                    "message": _censor_text(str(exc)),
                    "stack": _censor_text("".join(traceback.format_exception(exc_type, exc, tb))),
                },
            )
        return True


# --------------------------------------------------------------------------------------------
# Correlation
# --------------------------------------------------------------------------------------------

_CORRELATION_FIELD = "correlation_id"
_REQUEST_FIELD = "request_id"
_SESSION_FIELD = "session_id"
_HTTP_REQUEST_FIELD = "http_request_id"

# The last resort, and the only id available to a line emitted before anything is serving a
# request: startup, the tool-surface manifest, a lifespan failure. Every line of one pod's boot
# shares it, which is what makes those lines a group instead of a pile.
_BOOT_ID = f"boot-{uuid.uuid4().hex}"

# Set per HTTP request by `HttpRequestIdMiddleware`, read by `CorrelationFilter`.
_http_request_id: ContextVar[str | None] = ContextVar("office_mcp_http_request_id", default=None)

# An id a gateway already minted for this request, preferred over one of ours so the two systems'
# logs join. Capped, because it is a header and therefore attacker-controlled.
_FORWARDED_REQUEST_ID_HEADER = b"x-request-id"
_MAX_FORWARDED_REQUEST_ID = 128


def _mcp_request_id() -> str | None:
    """The MCP request id of the message being handled, or `None` outside one.

    This is FastMCP's own per-message identity and not a parallel scheme, which also makes it the
    one identity that is correct inside the streamable-HTTP session task: it is set per message,
    where anything set per HTTP request is stale there. See `tracing.py`.
    """
    try:
        return get_context().request_id
    except Exception:
        # Broad on purpose: there is no exception a log filter may propagate. FastMCP raises
        # `RuntimeError` for "no context" and `ValueError` for "no session yet", and a third
        # spelling in a later version must not turn one log line into a crash.
        return None


def _mcp_session_id() -> str | None:
    """The transport's own session id, read off the request being served.

    Read from the header rather than from `Context.session_id`, which mints and memoises a uuid of
    its own when a session has none — and the `initialize` message has none. That id would then be
    the one this service's logs report for a session the transport knows by a different one.
    """
    try:
        return get_http_request().headers.get("mcp-session-id")
    except Exception:
        return None


def _correlation_id(request_id: str | None) -> str:
    """Something joinable, whatever is running.

    The order is what each id is worth. A trace id spans this service and everything it called, so
    it wins whenever tracing is on. An MCP request id groups one message. An HTTP request id groups
    one request, including the lines uvicorn writes after the response. The boot id groups a
    process.
    """
    span = trace.get_current_span().get_span_context()
    if span.is_valid:
        return format(span.trace_id, "032x")
    if request_id is not None:
        return f"mcp-{request_id}"
    forwarded = _http_request_id.get()
    return forwarded if forwarded is not None else _BOOT_ID


class CorrelationFilter(logging.Filter):
    """Give every line an id that groups it with the rest of its request.

    The formatter adds `trace_id` when a span is recording and nothing at all when one is not, so
    without this a line emitted with tracing disabled — or before any request exists — cannot be
    grouped at all. `teams-mcp` has the same fallback for the same reason
    (`services/teams-mcp/src/app.module.ts:73-79`: the active span's trace id, or a generated id).

    An id a caller supplied is left alone, so a call that knows better than this filter can say so.
    """

    @override
    def filter(self, record: logging.LogRecord) -> bool:
        request_id = _mcp_request_id()
        if request_id is not None and _REQUEST_FIELD not in record.__dict__:
            setattr(record, _REQUEST_FIELD, request_id)
        session_id = _mcp_session_id()
        if session_id is not None and _SESSION_FIELD not in record.__dict__:
            setattr(record, _SESSION_FIELD, session_id)
        # Carried in its own field as well as being a candidate for `correlation_id`, because a
        # trace id outranks it: with tracing on it would otherwise never be visible, and it is the
        # only id shared with whatever gateway minted it.
        http_request_id = _http_request_id.get()
        if http_request_id is not None and _HTTP_REQUEST_FIELD not in record.__dict__:
            setattr(record, _HTTP_REQUEST_FIELD, http_request_id)
        if _CORRELATION_FIELD not in record.__dict__:
            setattr(record, _CORRELATION_FIELD, _correlation_id(request_id))
        return True


class HttpRequestIdMiddleware:
    """Mint an id for every HTTP request, for the lines that have no span and no MCP message.

    Mount outermost, so a request that fails before the app has it covered too.

    Trap: the contextvar is set and never reset. That is what puts the id on uvicorn's access line,
    which is written after the app has returned but inside the same per-request task — and a task's
    context dies with it, so nothing leaks into the next request. What it does reach is the
    streamable-HTTP session task, which snapshots the context of the `initialize` request that
    created it; `_correlation_id` therefore prefers the MCP request id, which is per message.
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


# --------------------------------------------------------------------------------------------
# The MCP SDK's own per-message line
# --------------------------------------------------------------------------------------------

# The line, and the logger that writes it: `mcp/server/lowlevel/server.py`, in `_handle_request`,
# immediately before the request handler — which is where FastMCP's whole middleware chain lives.
# Matched on the *template* rather than on the rendered text, because the template is a literal in
# that file and the rendered text is not: a ratchet in `tests/test_logging.py` reads it back out of
# the SDK and fails if it changed, so an SDK upgrade that renames the line is a failing test rather
# than a silently un-quieted one.
_SDK_MESSAGE_LOGGER = "mcp.server.lowlevel.server"
_SDK_PER_MESSAGE_LINE = "Processing request of type %s"


class StaleMessageLineFilter(logging.Filter):
    """Drop the SDK's per-message line, which is the one line that cannot carry the right trace id.

    The line is emitted inside the session task, before the request handler and therefore before
    any middleware of ours, so the ambient OpenTelemetry context it is formatted under is still the
    one the session task snapshotted at `initialize` — for the whole life of the session. See
    `tracing.py` for why that snapshot cannot be corrected from inside the task. At the chart's
    default `LOG_LEVEL=info` it is emitted for every message, so every tool call has exactly one
    line claiming the `initialize` request's trace.

    It carries nothing that is not in `MessageLogMiddleware`'s replacement: the SDK says the request
    *type* (`CallToolRequest`), the replacement says the JSON-RPC method (`tools/call`), the request
    id and the session id, under the trace of the request that actually carried the message.
    """

    @override
    def filter(self, record: logging.LogRecord) -> bool:
        return not (record.name == _SDK_MESSAGE_LOGGER and record.msg == _SDK_PER_MESSAGE_LINE)


class MessageLogMiddleware(Middleware):
    """One line per MCP message, in the trace of the request that carried it.

    Mount inside `TraceContextRestoreMiddleware`, which is what makes that true — outside it, this
    line would be the defect it replaces.
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


# --------------------------------------------------------------------------------------------
# uvicorn's second copy of its own message
# --------------------------------------------------------------------------------------------

# uvicorn puts an ANSI-coloured copy of the line in `extra` for its own coloured formatter. This
# service routes uvicorn through the pino formatter instead (see `main.py`), which copies every
# extra — so every uvicorn lifecycle line would carry its own message twice, once with escape codes
# in it.
_COLOR_MESSAGE_FIELD = "color_message"


class ColorMessageFilter(logging.Filter):
    @override
    def filter(self, record: logging.LogRecord) -> bool:
        if _COLOR_MESSAGE_FIELD in record.__dict__:
            delattr(record, _COLOR_MESSAGE_FIELD)
        return True


# --------------------------------------------------------------------------------------------
# Installation
# --------------------------------------------------------------------------------------------

# Loggers a dependency has taken out of the root handler's reach, and which this service takes back.
#
# `fastmcp/__init__.py:22-26` configures its own logger at **import** time — two `RichHandler`s on
# stderr and `propagate = False` — so every `fastmcp.*` line is ANSI-decorated plain text that never
# meets the pino formatter and never meets the filters above. That is not a formatting nit twice
# over: it is a line the log pipeline cannot parse *and* a line no redaction ran on, and one of
# those lines is the OAuth proxy warning about non-secure cookies.
#
# Reclaimed by removing the handlers and letting the records propagate, rather than by asking
# FastMCP not to configure itself: `FASTMCP_LOG_ENABLED` is read when `fastmcp` is imported, which
# has already happened by the time any function here runs.
_RECLAIMED_LOGGERS: tuple[str, ...] = ("fastmcp",)


def _reclaim(name: str) -> None:
    """Put one logger's records back on the path to the root handler."""
    reclaimed = logging.getLogger(name)
    for handler in list(reclaimed.handlers):
        reclaimed.removeHandler(handler)
    reclaimed.propagate = True


# Order is the order they run in, and it is the cheap-and-decisive one first: a dropped record is
# not worth identifying or redacting.
_FILTERS: tuple[type[logging.Filter], ...] = (
    StaleMessageLineFilter,
    ColorMessageFilter,
    CorrelationFilter,
    RedactionFilter,
)


def install_filters(handler: logging.Handler) -> None:
    """Put this service's filters on one handler, once. Idempotent, like `configure_logging`."""
    for filter_type in _FILTERS:
        if not any(isinstance(existing, filter_type) for existing in handler.filters):
            handler.addFilter(filter_type())


def configure_logging(config: AppConfig) -> None:
    configure_pino_logging(level=config.log_level.value.upper())
    # A Python warning is written to stderr by `warnings.showwarning`, as plain text, which is one
    # more way a line lands on the pino stream that the log pipeline cannot parse — and dependencies
    # of this service emit them (a store stability warning on every boot, deprecations from the
    # Graph SDK). This routes them through the `py.warnings` logger instead, so they arrive as
    # pino-json like everything else. Global, and belongs here for the same reason the handler
    # does: the contract is a property of the process, not of a call site.
    logging.captureWarnings(True)
    for name in _RECLAIMED_LOGGERS:
        _reclaim(name)
    # Every root handler, not only the one upstream just added: a second handler would be a second
    # way out of the process, and redaction that covers one of two is redaction that does not hold.
    for handler in logging.getLogger().handlers:
        install_filters(handler)
