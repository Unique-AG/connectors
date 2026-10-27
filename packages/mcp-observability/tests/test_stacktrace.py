import traceback
from collections.abc import Callable

from mcp_observability.stacktrace import scrub_stacktrace

_CANARY = "zq-canary-value"


def _scrubbed(raising: Callable[[], None]) -> str:
    try:
        raising()
    except BaseException as error:  # noqa: BLE001
        return scrub_stacktrace("".join(traceback.format_exception(error)))
    raise AssertionError("did not raise")


def _chained(message: str = _CANARY) -> None:
    try:
        raise KeyError(message)
    except KeyError as error:
        raise RuntimeError(message) from error


def _multiline(message: str = f"first line\n{_CANARY}\n  indented {_CANARY}") -> None:
    raise ValueError(message)


def _group(message: str = _CANARY) -> None:
    raise ExceptionGroup(message, [ValueError(message), KeyError(message)])


def test_keeps_frames_and_types_but_no_message() -> None:
    stack = _scrubbed(_chained)

    assert 'File "' in stack
    assert "raise KeyError(message)" in stack
    assert "\nKeyError\n" in stack
    assert "direct cause" in stack
    assert stack.endswith("RuntimeError")
    assert _CANARY not in stack


def test_drops_a_multiline_message() -> None:
    stack = _scrubbed(_multiline)

    assert stack.endswith("ValueError")
    assert _CANARY not in stack


def test_keeps_no_member_message_of_an_exception_group() -> None:
    stack = _scrubbed(_group)

    assert "ExceptionGroup" in stack
    assert "ValueError" in stack
    assert "KeyError" in stack
    assert _CANARY not in stack
