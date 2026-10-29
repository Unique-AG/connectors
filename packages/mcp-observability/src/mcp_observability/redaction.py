"""Known secrets and secret-shaped text replaced with `[Redacted]` in every log line."""

import json
import re
import threading
import time
import traceback
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Iterable
from contextlib import contextmanager
from contextvars import ContextVar
from functools import partial
from typing import cast
from typing import override
from urllib.parse import quote

import mcp_types as mt
from fastmcp.server.middleware import CallNext
from fastmcp.server.middleware import Middleware
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools import ToolResult
from starlette.requests import Request
from starlette.types import ASGIApp
from starlette.types import Receive
from starlette.types import Scope
from starlette.types import Send

from mcp_observability.stacktrace import scrub_stacktrace

# Shorter values are skipped: replacing them would hit ordinary words and numbers.
MIN_SECRET_LENGTH = 8
_REDACTED = "[Redacted]"

# Applied to every log line unless `default_patterns` is false, and exported one by one so a
# consumer that opts out can pick its own. When a pattern has a `secret` group, only that group is
# replaced, so the context around it (`Bearer `, `password=`) stays readable. A pattern that can
# fail after a long run starts only where that run starts: one that tried again inside the run
# would take seconds on a large value. Kept in step with `packages/logger`.

# A credential has a digit, an inner capital or a symbol, or is too long to be a word, so prose such
# as "Basic authentication failed" keeps its words.
AUTHORIZATION_SCHEME_PATTERN = re.compile(
    r"\b(?:Bearer|Basic)\s+(?P<secret>(?=[A-Za-z0-9\-._~+/]+[0-9A-Z_~+/=]|[A-Za-z0-9\-._~+/]{20})"
    r"[A-Za-z0-9\-._~+/]{8,}=*)"
)
JWT_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
API_KEY_PATTERN = re.compile(
    r"\b(?:x-)?api[-_]?key\s*[=:]\s*(?P<secret>[^\s&,;\"']+)", re.IGNORECASE
)
CREDENTIAL_PARAMETER_PATTERN = re.compile(
    r"\b(?:access[-_]?token|refresh[-_]?token|id[-_]?token|client[-_]?secret|password|passwd"
    r"|secret|token)=(?P<secret>[^\s&,;\"']+)",
    re.IGNORECASE,
)
URL_CREDENTIALS_PATTERN = re.compile(
    r"(?<![a-z0-9+.-])[a-z][a-z0-9+.-]*://[^/\s:@]+:(?P<secret>[^/\s@]+)@", re.IGNORECASE
)
PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----(?:(?!-----BEGIN )[\s\S])*?"
    r"-----END [A-Z ]*PRIVATE KEY-----"
)
SK_PREFIXED_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")
GITHUB_TOKEN_PATTERN = re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}")
SLACK_TOKEN_PATTERN = re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")
AWS_ACCESS_KEY_ID_PATTERN = re.compile(r"\bAKIA[0-9A-Z]{16}\b")

DEFAULT_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    AUTHORIZATION_SCHEME_PATTERN,
    JWT_PATTERN,
    API_KEY_PATTERN,
    CREDENTIAL_PARAMETER_PATTERN,
    URL_CREDENTIALS_PATTERN,
    PRIVATE_KEY_PATTERN,
    SK_PREFIXED_KEY_PATTERN,
    GITHUB_TOKEN_PATTERN,
    SLACK_TOKEN_PATTERN,
    AWS_ACCESS_KEY_ID_PATTERN,
)


# A JSON string literal, and the colon after it when it is an object key.
_JSON_STRING = re.compile(r'("(?:[^"\\]|\\.)*")(\s*:)?')
# `PinoJsonFormatter` writes `msg` before any logged value that could nest one.
_MSG = re.compile(r'"msg":\s*("(?:[^"\\]|\\.)*")')

# Describes a log call from fields that hold no logged value: its logger, level, code location and
# trace ids.
type Source = Callable[[], dict[str, object]]

# The variants to replace, longest first, already expanded by `_secret_variants`.


class _LogScope:
    """The secrets of one `log_secrets` block or redaction middleware. Every task started in it
    shares this object, so a secret `add_log_secrets` adds late reaches them all, and the lines
    logged after the call that added it returns or raises."""

    def __init__(
        self, parent: _LogScope | None, secrets: tuple[str, ...], failure: str | None = None
    ) -> None:
        self._parent: _LogScope | None = parent
        # The variants to replace, longest first, already expanded by `_secret_variants`.
        self._secrets: tuple[str, ...] = secrets
        # Why secrets of this scope could not be read, as JSON added to every line logged in it.
        self._failure: str | None = failure
        self._lock: threading.Lock = threading.Lock()

    def add(self, secrets: tuple[str, ...]) -> None:
        with self._lock:
            self._secrets = _longest_first((*self._secrets, *secrets))

    def fail(self, failure: str) -> None:
        self._failure = failure

    def secrets(self) -> tuple[str, ...]:
        outer = self._parent.secrets() if self._parent is not None else ()
        return (*outer, *self._secrets)

    def failure(self) -> str | None:
        if self._failure is not None or self._parent is None:
            return self._failure
        return self._parent.failure()


_log_scope: ContextVar[_LogScope | None] = ContextVar("log_scope", default=None)


class SecretRedactor:
    """Replaces known secrets, the current context's secrets and pattern matches inside every JSON
    string value of a serialized line, and the secrets alone inside keys. Structure is never touched
    and every changed string is re-encoded, so the line always stays valid JSON."""

    def __init__(
        self,
        secrets: Iterable[str] = (),
        patterns: Iterable[re.Pattern[str]] = (),
        *,
        default_patterns: bool = True,
    ) -> None:
        """`default_patterns=False` drops `DEFAULT_SECRET_PATTERNS`, leaving only `patterns`, which
        can pick from them."""
        self._secrets: tuple[str, ...] = _secret_variants(secrets)
        defaults = DEFAULT_SECRET_PATTERNS if default_patterns else ()
        self._patterns: tuple[re.Pattern[str], ...] = (*defaults, *patterns)

    def redact_line(self, line: str, *, source: Source | None = None) -> str:
        """Never raises: `logging` would print the unredacted record to stderr. `source` describes
        the log call for the line that replaces one that cannot be redacted."""
        try:
            redacted = _JSON_STRING.sub(partial(self._redact_token, self._current_secrets()), line)
            scope = _log_scope.get()
            return _with_failure(redacted, scope.failure() if scope is not None else None)
        except Exception as error:  # noqa: BLE001 - any failure must still produce a safe line
            return failed_line(
                "secret redaction",
                error,
                source=source,
                original_msg=partial(self._salvaged_msg, line),
            )

    def salvage(self, text: str) -> str:
        """`text` for a line that could not be redacted: the secrets are replaced, which cannot
        fail, and the patterns too unless they are what failed."""
        without_secrets = _replace_secrets(text, self._current_secrets())
        try:
            return self._replace_patterns(without_secrets)
        except Exception:  # noqa: BLE001 - the secrets are replaced, which is what can still be shown
            return without_secrets

    def _current_secrets(self) -> tuple[str, ...]:
        scope = _log_scope.get()
        return _longest_first((*self._secrets, *scope.secrets())) if scope else self._secrets

    def _redact_token(self, secrets: tuple[str, ...], token: re.Match[str]) -> str:
        literal, key_colon = token.group(1), token.group(2)
        text = _decoded(literal)
        if text is None:
            return token.group(0) if key_colon is not None else json.dumps(_REDACTED)
        if key_colon is not None:
            key = _replace_secrets(text, secrets)
            if key == text:
                return token.group(0)
            return json.dumps(key, ensure_ascii=False) + key_colon
        redacted = self._replace_patterns(_replace_secrets(text, secrets))
        return literal if redacted == text else json.dumps(redacted, ensure_ascii=False)

    def _replace_patterns(self, text: str) -> str:
        redacted = text
        for pattern in self._patterns:
            redacted = pattern.sub(_redact_match, redacted)
        return redacted

    def _salvaged_msg(self, line: str) -> str | None:
        found = _MSG.search(line)
        text = _decoded(found.group(1)) if found else None
        return None if text is None else self.salvage(text)


@contextmanager
def log_secrets(*secrets: str) -> Generator[None]:
    """Redact `secrets` from every line logged in this context, on top of the outer ones."""
    with _scope(_secret_variants(secrets)):
        yield


def add_log_secrets(*secrets: str) -> None:
    """Redact `secrets` from every line logged until the innermost `log_secrets` block or
    redaction middleware ends, also after the caller returns or raises, and in the tasks started
    in it. For a secret read partway through, such as the caller's token loaded from a database
    inside the tool. Outside such a scope it does nothing. It never raises: when it fails, the
    lines of the scope name the error in `log_secrets_failed`."""
    scope = _log_scope.get()
    if scope is None:
        return
    try:
        scope.add(_secret_variants(secrets))
    except Exception as error:  # noqa: BLE001 - the caller must run whatever it passed
        scope.fail(json.dumps(_error_fields(error)))


@contextmanager
def _scope(secrets: tuple[str, ...], failure: str | None = None) -> Generator[None]:
    token = _log_scope.set(_LogScope(_log_scope.get(), secrets, failure))
    try:
        yield
    finally:
        _log_scope.reset(token)


class RedactRequestSecretsMiddleware:
    """ASGI middleware that redacts what `secrets_of` returns for an HTTP request, such as its
    bearer token or API key, from every line logged while the request is handled."""

    def __init__(self, app: ASGIApp, secrets_of: Callable[[Request], Iterable[str]]) -> None:
        self._app: ASGIApp = app
        self._secrets_of: Callable[[Request], Iterable[str]] = secrets_of

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        with _secrets_read_safely(lambda: self._secrets_of(Request(scope))):
            await self._app(scope, receive, send)


class RedactToolCallSecretsMiddleware(Middleware):
    """FastMCP middleware that redacts what `secrets_of` returns for a tool call, such as the
    caller's token from `get_access_token()`, from every line logged while the tool runs. List it
    before `ToolCallObservabilityMiddleware`, so the lines that one writes are redacted too."""

    def __init__(
        self,
        secrets_of: Callable[[MiddlewareContext[mt.CallToolRequestParams]], Iterable[str]],
    ) -> None:
        super().__init__()
        self._secrets_of: Callable[[MiddlewareContext[mt.CallToolRequestParams]], Iterable[str]] = (
            secrets_of
        )

    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        with _secrets_read_safely(lambda: self._secrets_of(context)):
            return await call_next(context)


@contextmanager
def _secrets_read_safely(read: Callable[[], Iterable[str]]) -> Generator[None]:
    """Secrets that cannot be read must not fail the caller: its lines are still written, redacted
    for every other secret and naming the error in `log_secrets_failed`."""
    try:
        secrets, failure = tuple(read()), None
    except Exception as error:  # noqa: BLE001 - the caller must run whatever the consumer raised
        secrets, failure = (), json.dumps(_error_fields(error))
    with _scope(_secret_variants(secrets), failure):
        yield


def _with_failure(line: str, failure: str | None) -> str:
    """A `PinoJsonFormatter` line always opens with `{"level":`, so the field goes first."""
    if failure is None or not line.startswith('{"'):
        return line
    return f'{{"log_secrets_failed": {failure}, {line[1:]}'


def _decoded(literal: str) -> str | None:
    """None for a literal that is not valid JSON, which the caller redacts whole: an exception
    here would reach `Handler.handleError`, which prints the record's message to stderr."""
    if "\\" not in literal:
        return literal[1:-1]
    try:
        value = cast(object, json.loads(literal))
    except ValueError:
        return None
    assert isinstance(value, str), "A JSON string literal decodes to a string"
    return value


def _redact_match(match: re.Match[str]) -> str:
    if "secret" not in match.re.groupindex or match.group("secret") is None:
        return _REDACTED
    start, end = match.span("secret")
    offset = match.start()
    whole = match.group(0)
    return whole[: start - offset] + _REDACTED + whole[end - offset :]


def _secret_variants(secrets: Iterable[str]) -> tuple[str, ...]:
    """Each secret as written and URL-encoded, as a query string carries it."""
    return _longest_first(
        variant
        for secret in secrets
        # A consumer reading an absent header passes `None` whatever the types say.
        if isinstance(secret, str) and len(secret) >= MIN_SECRET_LENGTH  # pyright: ignore[reportUnnecessaryIsInstance]
        for variant in (secret, *_url_encoded(secret))
    )


def _url_encoded(secret: str) -> tuple[str, ...]:
    """`quote` raises on a lone surrogate, which no URL can carry anyway."""
    try:
        # The same characters `encodeURIComponent` leaves as they are.
        return (quote(secret, safe="!'()*"),)
    except UnicodeEncodeError:
        return ()


def failed_line(
    stage: str,
    error: Exception,
    *,
    source: Source | None = None,
    original_msg: Callable[[], str | None] | None = None,
) -> str:
    """The line written in place of one whose `stage` failed. It points at the log call through
    `source`, keeps the message as `original_msg` salvages it, and names the error and its frames,
    never its message, which can quote the secret. It does not log, so it cannot loop back here,
    and it cannot raise: it falls back to less."""
    failed: dict[str, object] = {
        "level": 50,
        "log_level": "error",
        "time": int(time.time() * 1000),
        "msg": f"Log line replaced: {stage} failed",
    }
    try:
        described = source() if source is not None else {}
    except Exception:  # noqa: BLE001 - the replacement line must always be written
        described = {}
    try:
        message = original_msg() if original_msg is not None else None
    except Exception:  # noqa: BLE001 - the replacement line must always be written
        message = None
    salvaged = {} if message is None else {"original_msg": message}
    try:
        return json.dumps({**failed, **described, **salvaged, "err": _error_fields(error)})
    except Exception:  # noqa: BLE001 - the replacement line must always be written
        return json.dumps(failed)


def _error_fields(error: Exception) -> dict[str, str]:
    """The error's type and frames, never its message, which can quote the secret."""
    try:
        return {
            "name": type(error).__name__,
            "stack": scrub_stacktrace("".join(traceback.format_exception(error))),
        }
    except Exception:  # noqa: BLE001 - a line naming the failure must always be written
        return {"name": "unknown"}


def _replace_secrets(text: str, secrets: tuple[str, ...]) -> str:
    redacted = text
    for secret in secrets:
        redacted = redacted.replace(secret, _REDACTED)
    return redacted


def _longest_first(secrets: Iterable[str]) -> tuple[str, ...]:
    """Longest first, so a secret that contains another is replaced whole."""
    return tuple(sorted(set(secrets), key=len, reverse=True))
