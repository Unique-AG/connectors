"""Known secrets and secret-shaped text replaced with `[Redacted]` in every log line."""

import json
import re
import string
import threading
import time
import traceback
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Iterable
from contextlib import contextmanager
from contextvars import ContextVar
from functools import partial
from typing import ClassVar
from typing import cast
from typing import override

import mcp_types as mt
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import CallNext
from fastmcp.server.middleware import Middleware
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools import ToolResult
from pydantic import BaseModel
from pydantic import ConfigDict
from starlette.requests import Request
from starlette.types import ASGIApp
from starlette.types import Receive
from starlette.types import Scope
from starlette.types import Send

from mcp_observability.stacktrace import scrub_stacktrace

# A secret shorter than this is replaced only where it stands alone, not inside a longer word or
# number: it would otherwise hit ordinary words, such as `test` in `testserver`.
SHORT_SECRET_LENGTH = 8
_REDACTED = "[Redacted]"
_ENCODED_BYTE = re.compile(r"%[0-9A-F]{2}")
_ESCAPE = re.compile(r"%[0-9a-fA-F]{2}")

# A `secret` group narrows what is replaced, so `Bearer ` or `password=` stays readable. Kept in
# step with `packages/logger`.

# The scheme in any case. The credential needs a digit, an inner capital or a symbol, or 20
# characters, so prose such as "Basic authentication failed" keeps its words.
_AUTHORIZATION_SCHEME_PATTERN = re.compile(
    r"\b(?i:Bearer|Basic)\s+(?P<secret>(?=[A-Za-z0-9\-._~+/]+[0-9A-Z_~+/=]|[A-Za-z0-9\-._~+/]{20})"
    r"[A-Za-z0-9\-._~+/]{8,}=*)"
)
_JWT_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
# No letter or digit before the name, unlike `\b`, so `x_api_key=` and `csrf_token=` match too. The
# divider is `=` or `:` as in a header, and the name and value may be quoted as in JSON, so an
# upstream error body quoting `{"client_secret":"…"}` is caught.
_API_KEY_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:x-)?api[-_]?key[\"']?\s*[=:]\s*[\"']?(?P<secret>[^\s&,;\"']+)",
    re.IGNORECASE,
)
# A bare `token:` stays readable, as in "refresh token: invalid_grant". Only `=` or a quoted name
# before the colon marks a credential.
_CREDENTIAL_PARAMETER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:access[-_]?token|refresh[-_]?token|id[-_]?token|client[-_]?secret"
    r"|password|passwd|secret|token)(?:\s*=\s*|[\"']\s*:\s*)[\"']?(?P<secret>[^\s&,;\"']+)",
    re.IGNORECASE,
)
_URL_CREDENTIALS_PATTERN = re.compile(
    r"(?<![a-z0-9+.-])[a-z][a-z0-9+.-]*://[^/\s:@]+:(?P<secret>[^/\s@]+)@", re.IGNORECASE
)
_PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----(?:(?!-----BEGIN )[\s\S])*?"
    r"-----END [A-Z ]*PRIVATE KEY-----"
)
_SK_PREFIXED_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")
_GITHUB_TOKEN_PATTERN = re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}")
_SLACK_TOKEN_PATTERN = re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")
_AWS_ACCESS_KEY_ID_PATTERN = re.compile(r"\bAKIA[0-9A-Z]{16}\b")

# Secret-shaped text: authorization credentials, JWTs, `key=value` credentials, URL userinfo, PEM
# private keys, and `sk-`, GitHub, Slack and AWS keys. Off unless passed as `patterns`, since they
# can also replace text that is not a secret.
DEFAULT_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    _AUTHORIZATION_SCHEME_PATTERN,
    _JWT_PATTERN,
    _API_KEY_PATTERN,
    _CREDENTIAL_PARAMETER_PATTERN,
    _URL_CREDENTIALS_PATTERN,
    _PRIVATE_KEY_PATTERN,
    _SK_PREFIXED_KEY_PATTERN,
    _GITHUB_TOKEN_PATTERN,
    _SLACK_TOKEN_PATTERN,
    _AWS_ACCESS_KEY_ID_PATTERN,
)

# The characters each encoder leaves as they are besides letters and digits, and how it writes a
# space. Kept in step with `packages/logger`.
_URL_ENCODINGS: tuple[tuple[str, str], ...] = (
    ("-_.!~*'()", "%20"),  # JavaScript's `encodeURIComponent`
    ("-_.~", "%20"),  # RFC 3986, as `quote(safe="")`
    ("-_.~", "+"),  # `quote_plus`
    ("-_.*", "+"),  # `URLSearchParams` and HTML forms
)
_ALPHANUMERIC = frozenset(string.ascii_letters + string.digits)


class SecretRedaction(BaseModel):
    """What `configure_logging` replaces with `[Redacted]` in every line."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    secrets: tuple[str, ...] = ()
    """Known secret values, such as API keys from the settings. Empty and blank values are
    skipped. A value shorter than `SHORT_SECRET_LENGTH` is replaced only where it stands alone."""
    patterns: tuple[re.Pattern[str], ...] = ()
    """Secret-shaped text to replace, such as `DEFAULT_SECRET_PATTERNS`. A `secret` named group
    narrows what is replaced."""


_JSON_STRING = re.compile(r'("(?:[^"\\]|\\[\s\S])*(?:"|\\?\Z))(\s*:)?')
_MSG = re.compile(r'"msg":\s*("(?:[^"\\]|\\[\s\S])*(?:"|\\?\Z))')

type Source = Callable[[], dict[str, object]]


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
        self, secrets: Iterable[str] = (), patterns: Iterable[re.Pattern[str]] = ()
    ) -> None:
        self._secrets: tuple[str, ...] = _secret_variants(secrets)
        self._patterns: tuple[re.Pattern[str], ...] = tuple(patterns)

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
        fail, and every pattern that does not fail."""
        redacted = _replace_secrets(text, self._current_secrets())
        for pattern in self._patterns:
            try:
                redacted = pattern.sub(_redact_match, redacted)
            except Exception:  # noqa: BLE001 - one failing pattern must not skip the rest
                continue
        return redacted

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


def bearer_token(request: Request) -> tuple[str, ...]:
    """The token of a request's `Authorization: Bearer` header. RFC 6750 allows any whitespace after
    the scheme."""
    parts = request.headers.get("authorization", "").split()
    return (parts[1],) if len(parts) >= 2 and parts[0].lower() == "bearer" and parts[1] else ()


def caller_access_token(_context: MiddlewareContext[mt.CallToolRequestParams]) -> tuple[str, ...]:
    """The MCP access token of a tool call, which may not run in its HTTP request's context."""
    access_token = get_access_token()
    return (access_token.token,) if access_token is not None else ()


class RedactRequestSecretsMiddleware:
    """ASGI middleware that redacts what `secrets_of` returns for an HTTP request, its bearer token
    unless given, from every line logged while the request is handled."""

    def __init__(
        self, app: ASGIApp, secrets_of: Callable[[Request], Iterable[str]] = bearer_token
    ) -> None:
        self._app: ASGIApp = app
        self._secrets_of: Callable[[Request], Iterable[str]] = secrets_of

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        with _secrets_read_safely(lambda: self._secrets_of(Request(scope))):
            await self._app(scope, receive, send)


class RedactToolCallSecretsMiddleware(Middleware):
    """FastMCP middleware that redacts what `secrets_of` returns for a tool call, the caller's
    access token unless given, from every line logged while the tool runs. List it before
    `ToolCallObservabilityMiddleware`, so the lines that one writes are redacted too."""

    def __init__(
        self,
        secrets_of: Callable[
            [MiddlewareContext[mt.CallToolRequestParams]], Iterable[str]
        ] = caller_access_token,
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
    if len(literal) < 2 or not literal.endswith('"'):
        return None
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
    """Each secret as written and in each way a URL or form body encodes it. A lone `str` is one
    secret, not the characters it is made of."""
    return _longest_first(
        variant
        for secret in ((secrets,) if isinstance(secrets, str) else secrets)
        # A consumer reading an absent header passes `None` whatever the types say. A blank value
        # would match everywhere, so it is no secret.
        if isinstance(secret, str) and secret.strip()  # pyright: ignore[reportUnnecessaryIsInstance]
        for variant in (secret, *_url_encoded(secret))
    )


def _url_encoded(secret: str) -> tuple[str, ...]:
    """A lone surrogate has no UTF-8 encoding, so no URL can carry it."""
    try:
        data = secret.encode()
    except UnicodeEncodeError:
        return ()
    return tuple(_percent_encoded(data, safe, space) for safe, space in _URL_ENCODINGS)


def _percent_encoded(data: bytes, safe: str, space: str) -> str:
    return "".join(
        chr(byte)
        if chr(byte) in _ALPHANUMERIC or chr(byte) in safe
        else space
        if byte == 0x20
        else f"%{byte:02X}"
        for byte in data
    )


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
        redacted = _replace_secret(redacted, secret)
    return redacted


def _replace_secret(text: str, secret: str) -> str:
    encoded = _ENCODED_BYTE.search(secret) is not None
    if len(secret) >= SHORT_SECRET_LENGTH and not encoded:
        return text.replace(secret, _REDACTED)
    # A URL encodes a byte as upper-case hex, but a DSN written by hand may say `%2f`. Both spell
    # the same length, so a match in the folded text is a match in the original.
    haystack = _ESCAPE.sub(lambda escape: escape.group().upper(), text) if encoded else text
    parts: list[str] = []
    copied = 0
    index = haystack.find(secret)
    while index != -1:
        end = index + len(secret)
        if index >= copied and (
            len(secret) >= SHORT_SECRET_LENGTH or _stands_alone(text, secret, index, end)
        ):
            parts.extend((text[copied:index], _REDACTED))
            copied = end
        index = haystack.find(secret, index + 1)
    parts.append(text[copied:])
    return "".join(parts)


def _stands_alone(text: str, secret: str, start: int, end: int) -> bool:
    """An edge that is not a word character, such as a symbol, can touch a word and still be the
    secret."""
    touches_before = start > 0 and _is_word(text[start - 1]) and _is_word(secret[0])
    touches_after = end < len(text) and _is_word(text[end]) and _is_word(secret[-1])
    return not touches_before and not touches_after


def _is_word(character: str) -> bool:
    return character.isalnum() or character == "_"


def _longest_first(secrets: Iterable[str]) -> tuple[str, ...]:
    """Longest first, so a secret that contains another is replaced whole."""
    return tuple(sorted(set(secrets), key=len, reverse=True))
