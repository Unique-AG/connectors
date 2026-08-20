"""Structured logging: `unique_mcp`'s pino-json contract, and what it carries that it must not.

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

Design decision: the filters here mutate the record they are given, which the house rule against
mutating arguments would otherwise forbid. A `logging.Filter` has no return path other than the
record — the stdlib documents "modify the record in-place" as what a filter is for — and the record
is a per-emit object the caller does not keep. What is *not* mutated is anything the caller still
owns: a dict passed as `extra=` is rebuilt rather than edited in place, so redaction never reaches
back into the header map the caller is still using. See `_redact`.
"""

import logging
import re
import traceback
from collections.abc import Iterable, Mapping, Sequence
from typing import cast, override

from unique_mcp.logging import configure_logging as configure_pino_logging

from office_mcp.config import AppConfig

__all__ = [
    "CENSORED",
    "TRUNCATED",
    "RedactionFilter",
    "configure_logging",
    "install_filters",
]

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
# Installation
# --------------------------------------------------------------------------------------------

_FILTERS: tuple[type[logging.Filter], ...] = (RedactionFilter,)


def install_filters(handler: logging.Handler) -> None:
    """Put this service's filters on one handler, once. Idempotent, like `configure_logging`."""
    for filter_type in _FILTERS:
        if not any(isinstance(existing, filter_type) for existing in handler.filters):
            handler.addFilter(filter_type())


def configure_logging(config: AppConfig) -> None:
    configure_pino_logging(level=config.log_level.value.upper())
    # Every root handler, not only the one upstream just added: a second handler would be a second
    # way out of the process, and redaction that covers one of two is redaction that does not hold.
    for handler in logging.getLogger().handlers:
        install_filters(handler)
