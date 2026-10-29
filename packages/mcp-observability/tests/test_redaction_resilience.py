import asyncio
import json
import logging
import random
import re
from collections.abc import Callable
from collections.abc import Iterator
from typing import cast
from typing import override

import pytest
from mcp_configs import ErrorDetailsPolicy
from mcp_configs import LoggingSettings
from opentelemetry import trace
from opentelemetry.trace import NonRecordingSpan
from opentelemetry.trace import SpanContext

from mcp_observability import PinoJsonFormatter
from mcp_observability import configure_logging
from mcp_observability import log_secrets
from mcp_observability.redaction import SecretRedactor
from mcp_observability.redaction import failed_line

_SECRET = "resilience-secret-0123"
_log = logging.getLogger("tests.resilience")
# None of these characters occur in `[Redacted]`, so a secret built from them cannot reappear
# across the edge of a replacement and every leftover occurrence is a real leak.
_SECRET_ALPHABET = (
    *('"', "\\", "\n", "\t", "é", "😀", "\ud800", "$", "&", "%", "+", "/", " "),
    *("x", "y", "z", "0", "7"),
)
_TEXT_ALPHABET = (
    *_SECRET_ALPHABET,
    *("{", "}", ":", ",", "[", "]", "Bearer ", "password=", "\u0000", "\u2028"),
)


@pytest.fixture(autouse=True)
def root_handlers() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    root.handlers = []
    yield
    root.handlers, root.level = handlers, level


def _random_string(rng: random.Random, alphabet: tuple[str, ...], length: int) -> str:
    return "".join(rng.choice(alphabet) for _ in range(length))


def _string_values(value: object) -> list[str]:
    match value:
        case str():
            return [value]
        case list():
            items = cast("list[object]", value)
            return [found for item in items for found in _string_values(item)]
        case dict():
            items = cast("dict[str, object]", value).values()
            return [found for item in items for found in _string_values(item)]
        case _:
            return []


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_random_lines_never_raise_stay_valid_json_and_never_leak(seed: int) -> None:
    rng = random.Random(seed)
    known = [_random_string(rng, _SECRET_ALPHABET, rng.randint(8, 15)) for _ in range(3)]
    in_context = [_random_string(rng, _SECRET_ALPHABET, rng.randint(8, 15)) for _ in range(2)]
    every_secret = [*known, *in_context]
    redactor = SecretRedactor(known)

    def with_secrets() -> str:
        text = _random_string(rng, _TEXT_ALPHABET, rng.randint(0, 20))
        return f"{text}{rng.choice(every_secret)}{text}" if rng.random() < 0.5 else text

    with log_secrets(*in_context):
        for index in range(400):
            record = {
                "level": 30,
                "msg": with_secrets(),
                "nested": {"value": with_secrets(), "list": [with_secrets(), 42, None, True]},
                "count": index,
            }
            redacted = redactor.redact_line(json.dumps(record, ensure_ascii=False))
            line = cast("dict[str, object]", json.loads(redacted))

            assert line["level"] == 30
            assert line["count"] == index
            for value in _string_values(line):
                for secret in every_secret:
                    assert secret not in value


@pytest.mark.parametrize(
    "line",
    [
        "",
        "\n",
        "not json at all",
        '"unterminated',
        '{"msg":"dangling backslash \\',
        '{"msg":"bad \\x escape"}',
        '{"msg":"short unicode \\u12"}',
        '{"msg":"lone quote " inside"}',
        '}{"]["',
        '\\\\\\"',
    ],
)
def test_a_malformed_line_does_not_raise(line: str) -> None:
    SecretRedactor((_SECRET,)).redact_line(line)


def _written(capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    output = capsys.readouterr().err
    assert _SECRET not in output
    assert "Logging error" not in output
    return [cast("dict[str, object]", json.loads(line)) for line in output.splitlines()]


def test_a_redaction_failure_writes_a_line_naming_the_error_without_its_message(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_logging(LoggingSettings(), own_loggers=("tests",), secrets=(_SECRET,))

    def explode(_self: SecretRedactor, text: str) -> str:
        raise RuntimeError(f"matching exploded on {text}")

    monkeypatch.setattr(SecretRedactor, "_redact_text", explode)
    _log.info("leaking %s", _SECRET)
    monkeypatch.undo()
    _log.info("second %s", _SECRET)

    failed, second = _written(capsys)
    assert failed["level"] == 50
    assert failed["log_level"] == "error"
    assert failed["msg"] == "Log line replaced: secret redaction failed"
    assert isinstance(failed["time"], int)
    err = cast("dict[str, str]", failed["err"])
    assert err["name"] == "RuntimeError"
    assert "in explode" in err["stack"]
    assert err["stack"].endswith("\nRuntimeError")
    assert second["msg"] == "second [Redacted]"


def test_a_redaction_failure_points_at_the_log_call_and_its_trace(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_logging(LoggingSettings(), own_loggers=("tests",), secrets=(_SECRET,))

    def explode(_self: SecretRedactor, _text: str) -> str:
        raise RuntimeError("matching exploded")

    monkeypatch.setattr(SecretRedactor, "_redact_text", explode)
    span_context = SpanContext(
        trace_id=0x4BF92F3577B34DA6A3CE929D0E0E4736, span_id=0x00F067AA0BA902B7, is_remote=False
    )

    class UserSync:
        def sync_user(self) -> None:
            _log.warning("syncing %s", _SECRET)

    with trace.use_span(NonRecordingSpan(span_context)):
        UserSync().sync_user()

    (failed,) = _written(capsys)
    assert failed["context"] == _log.name
    assert failed["original_level"] == 40
    assert re.fullmatch(
        r"sync_user \(.*test_redaction_resilience\.py:\d+\)", str(failed["logged_from"])
    )
    assert failed["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert failed["span_id"] == "00f067aa0ba902b7"


def test_the_replacement_line_survives_its_source_failing() -> None:
    def broken_source() -> dict[str, object]:
        raise RuntimeError(f"source exploded on {_SECRET}")

    line = failed_line("formatting", ValueError("bad"), source=broken_source)

    assert _SECRET not in line
    parsed = cast("dict[str, object]", json.loads(line))
    assert set(parsed) == {"level", "log_level", "time", "msg", "err"}
    assert parsed["err"] == {"name": "ValueError", "stack": "ValueError"}


class _UnprintableValue:
    @override
    def __str__(self) -> str:
        raise ValueError(f"cannot print {_SECRET}")


class _UnprintableError(Exception):
    @override
    def __str__(self) -> str:
        raise ValueError(f"cannot print {_SECRET}")


def _log_with_mismatched_arguments() -> None:
    _log.info("value %d", _SECRET)


def _log_an_unprintable_extra() -> None:
    _log.info("value", extra={"upstream": _UnprintableValue()})


def _log_an_unprintable_exception() -> None:
    _log.error("failed", exc_info=_UnprintableError())


@pytest.mark.parametrize(
    "log_call",
    [_log_with_mismatched_arguments, _log_an_unprintable_extra, _log_an_unprintable_exception],
)
def test_a_formatting_failure_writes_a_line_instead_of_printing_the_record(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    log_call: Callable[[], None],
) -> None:
    configure_logging(
        LoggingSettings(error_details_policy=ErrorDetailsPolicy.DISCLOSE),
        own_loggers=("tests",),
        secrets=(_SECRET,),
    )
    # pytest's own capturing handler formats the record too, and raises where ours does not.
    root = logging.getLogger()
    ours = [
        handler for handler in root.handlers if isinstance(handler.formatter, PinoJsonFormatter)
    ]
    monkeypatch.setattr(root, "handlers", ours)

    log_call()
    _log.info("next line")

    failed, following = _written(capsys)
    assert failed["msg"] == "Log line replaced: formatting failed"
    assert failed["context"] == _log.name
    assert str(failed["logged_from"]).startswith(f"{log_call.__name__} (")
    assert "name" in cast("dict[str, str]", failed["err"])
    assert following["msg"] == "next line"


def test_the_replacement_line_survives_its_own_error_description_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(_error: BaseException) -> list[str]:
        raise RuntimeError("traceback exploded")

    monkeypatch.setattr("mcp_observability.redaction.traceback.format_exception", explode)

    line = cast("dict[str, object]", json.loads(failed_line("formatting", ValueError(_SECRET))))

    assert line["msg"] == "Log line replaced: formatting failed"
    assert line["err"] == {"name": "unknown"}


def test_secrets_that_are_not_strings_at_runtime_are_ignored() -> None:
    not_strings: list[str] = [None, 12345678, {"value": _SECRET}]  # pyright: ignore[reportAssignmentType]
    redactor = SecretRedactor([*not_strings, _SECRET])

    with log_secrets(*not_strings):
        assert redactor.redact_line(f'{{"msg":"value {_SECRET}"}}') == '{"msg":"value [Redacted]"}'


@pytest.mark.parametrize(
    "secret",
    [
        "$&$`$'$$(.*)",
        ".*+?^$}{()|[]\\",
        "clé-😀-secrète",
        "lone-\ud800-surrogate",
        "multi\nline\tx",
    ],
)
def test_a_secret_with_unusual_characters_is_redacted(secret: str) -> None:
    redactor = SecretRedactor((secret,))
    line = json.dumps({"msg": f"start {secret} end"}, ensure_ascii=False)

    assert json.loads(redactor.redact_line(line)) == {"msg": "start [Redacted] end"}


@pytest.mark.parametrize(
    "message",
    ["Refreshing token for user", "token value expired", "Basic auth failed", "a bearer of bad"],
)
def test_ordinary_text_is_left_alone(message: str) -> None:
    line = json.dumps({"msg": message})

    assert SecretRedactor().redact_line(line) == line


async def test_concurrent_contexts_stay_apart() -> None:
    redactor = SecretRedactor()
    line = '{"msg":"first-context-secret second-context-secret"}'

    async def redact_within(secret: str, delay: float) -> str:
        with log_secrets(secret):
            await asyncio.sleep(delay)
            return redactor.redact_line(line)

    first, second = await asyncio.gather(
        redact_within("first-context-secret", 0.005), redact_within("second-context-secret", 0.001)
    )

    assert json.loads(first)["msg"] == "[Redacted] second-context-secret"
    assert json.loads(second)["msg"] == "first-context-secret [Redacted]"
