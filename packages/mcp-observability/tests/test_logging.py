import json
import logging
import warnings
from collections.abc import Iterator
from typing import cast
from typing import override

import pydantic
import pytest
from mcp_configs import ErrorDetailsPolicy
from mcp_configs import LoggingSettings
from mcp_configs import LogLevel

from mcp_observability import PinoJsonFormatter
from mcp_observability import configure_logging

_CANARY = "zq-canary-value"
# Under `tests`, the package passed as our own, so a model below counts as one of ours.
_OWN = ("tests",)
_log = logging.getLogger("tests.kiosk")
_TOUCHED = ("tests", "mcp_observability", "httpx", "httpcore", "sse_starlette", "fastmcp", "lib")


class Till(pydantic.BaseModel):
    label: str


class _Collected(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    @override
    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture(autouse=True)
def root_handlers() -> Iterator[None]:
    """Each test starts and ends with the loggers it found."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    levels = {name: logging.getLogger(name).level for name in _TOUCHED}
    root.handlers = []
    yield
    root.handlers, root.level = handlers, level
    for name, kept in levels.items():
        logging.getLogger(name).setLevel(kept)
    logging.getLogger("uvicorn.access").filters.clear()
    logging.getLogger("fastmcp.server.mixins.mcp_operations").filters.clear()
    logging.captureWarnings(False)


def _configure(
    level: LogLevel = LogLevel.INFO,
    *,
    library_log_levels: dict[str, LogLevel] | None = None,
    error_details_policy: ErrorDetailsPolicy = ErrorDetailsPolicy.REDACT,
) -> None:
    settings = LoggingSettings(
        log_level=level,
        library_log_levels=library_log_levels or {},
        error_details_policy=error_details_policy,
    )
    configure_logging(settings, own_loggers=_OWN)


def logged(capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    return [json.loads(line) for line in capsys.readouterr().err.splitlines()]


def _logged_with(
    capsys: pytest.CaptureFixture[str], level: int, error: BaseException
) -> dict[str, object]:
    _log.log(level, "Till failed", exc_info=error)
    (line,) = logged(capsys)
    return line


def _validation_error_raised_from_none() -> RuntimeError:
    try:
        try:
            Till.model_validate({"label": {_CANARY: _CANARY}})
        except pydantic.ValidationError:
            raise RuntimeError(_CANARY) from None
    except RuntimeError as error:
        return error
    raise AssertionError("unreachable")


def test_a_record_is_one_pino_json_line_with_its_extra_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure()

    logging.getLogger("kiosk").info("sold %s", "tea", extra={"till": 3})

    (line,) = logged(capsys)
    assert line["level"] == 30
    assert line["log_level"] == "info"
    assert line["msg"] == "sold tea"
    assert line["context"] == "kiosk"
    assert line["till"] == 3
    assert isinstance(line["time"], int)


def test_configuring_twice_adds_one_handler_and_one_error_filter() -> None:
    _configure()
    _configure(LogLevel.DEBUG)

    (handler,) = [
        h for h in logging.getLogger().handlers if isinstance(h.formatter, PinoJsonFormatter)
    ]
    assert handler.level == logging.NOTSET
    assert len(handler.filters) == 1


class TestLevels:
    def test_own_loggers_log_at_the_level_and_an_unnamed_library_at_info(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure(LogLevel.DEBUG)

        _log.debug("ours")
        logging.getLogger("lib").debug("theirs, hidden")
        logging.getLogger("lib").info("theirs")

        assert [line["msg"] for line in logged(capsys)] == ["ours", "theirs"]

    def test_own_loggers_above_info_hide_their_info_lines(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure(LogLevel.WARNING)

        _log.info("hidden")
        logging.getLogger("mcp_observability").info("hidden too")
        _log.warning("shown")

        assert [line["msg"] for line in logged(capsys)] == ["shown"]

    def test_libraries_that_log_urls_or_payloads_start_quieter(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure(LogLevel.DEBUG)

        logging.getLogger("httpx").info("GET https://upstream.test/?q=secret")
        logging.getLogger("httpcore").info("connect")
        logging.getLogger("sse_starlette").debug("event body")

        assert logged(capsys) == []

    def test_library_log_levels_win_over_the_defaults(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure(library_log_levels={"httpx": LogLevel.INFO, "lib": LogLevel.ERROR})

        logging.getLogger("httpx").info("request")
        logging.getLogger("lib").warning("hidden")

        assert [line["msg"] for line in logged(capsys)] == ["request"]


class TestOneStream:
    def test_fastmcp_lines_reach_the_pino_stream(self, capsys: pytest.CaptureFixture[str]) -> None:
        fastmcp = logging.getLogger("fastmcp")
        fastmcp.addHandler(logging.StreamHandler())
        fastmcp.propagate = False

        _configure()
        fastmcp.info("started")

        assert fastmcp.handlers == []
        assert [line["msg"] for line in logged(capsys)] == ["started"]

    def test_the_fastmcp_line_with_the_tool_arguments_is_dropped(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure(library_log_levels={"fastmcp": LogLevel.DEBUG})

        operations = logging.getLogger("fastmcp.server.mixins.mcp_operations")
        operations.debug("[x] Handler called: call_tool %s with %s", "sell", {"till": _CANARY})
        operations.debug("[x] Handler called: list_tools")

        assert [line["msg"] for line in logged(capsys)] == ["[x] Handler called: list_tools"]

    def test_a_python_warning_is_a_pino_line(self, capsys: pytest.CaptureFixture[str]) -> None:
        _configure()

        with warnings.catch_warnings():
            warnings.simplefilter("always")
            warnings.warn("deprecated", DeprecationWarning, stacklevel=1)

        (line,) = logged(capsys)
        assert line["context"] == "py.warnings"

    @pytest.mark.parametrize(
        ("path", "kept"),
        [("/probe", False), ("/ready", False), ("/metrics", False), ("/mcp", True)],
    )
    def test_access_lines_of_the_ops_routes_are_dropped(
        self, capsys: pytest.CaptureFixture[str], path: str, kept: bool
    ) -> None:
        _configure()

        logging.getLogger("uvicorn.access").info('127.0.0.1 - "GET %s HTTP/1.1" 200', path)

        assert (len(logged(capsys)) == 1) is kept


class TestErrorDetails:
    def test_below_error_the_error_is_named_without_a_stack(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure()

        line = _logged_with(capsys, logging.WARNING, KeyError(_CANARY))

        assert line["error_type"] == "KeyError"
        assert "err" not in line
        assert _CANARY not in json.dumps(line)

    def test_at_error_the_stack_keeps_frames_and_types_but_no_message(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure()
        try:
            try:
                raise KeyError(_CANARY)
            except KeyError as cause:
                raise RuntimeError(_CANARY) from cause
        except RuntimeError as error:
            line = _logged_with(capsys, logging.ERROR, error)

        err = cast("dict[str, str]", line["err"])
        assert line["error_type"] == "RuntimeError"
        assert err["name"] == "RuntimeError"
        assert "message" not in err
        assert 'File "' in err["stack"]
        assert "\nKeyError\n" in err["stack"]
        assert _CANARY not in json.dumps(line)

    def test_an_err_the_call_passed_is_kept(self, capsys: pytest.CaptureFixture[str]) -> None:
        _configure()

        _log.error("Till failed", exc_info=KeyError(_CANARY), extra={"err": {"name": "Ours"}})

        (line,) = logged(capsys)
        assert line["err"] == {"name": "Ours"}

    def test_disclose_keeps_the_message_and_stack_at_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure(error_details_policy=ErrorDetailsPolicy.DISCLOSE)

        line = _logged_with(capsys, logging.ERROR, KeyError(_CANARY))

        err = cast("dict[str, str]", line["err"])
        assert _CANARY in err["message"]
        assert _CANARY in err["stack"]
        assert line["error_type"] == "KeyError"

    def test_disclose_still_drops_the_stack_below_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure(error_details_policy=ErrorDetailsPolicy.DISCLOSE)

        line = _logged_with(capsys, logging.WARNING, KeyError(_CANARY))

        assert "err" not in line

    @pytest.mark.parametrize("policy", list(ErrorDetailsPolicy))
    @pytest.mark.parametrize("level", [logging.WARNING, logging.ERROR])
    def test_names_the_failed_fields_behind_raise_from_none(
        self, capsys: pytest.CaptureFixture[str], policy: ErrorDetailsPolicy, level: int
    ) -> None:
        _configure(error_details_policy=policy)

        line = _logged_with(capsys, level, _validation_error_raised_from_none())

        assert line["failed_fields"] == ["label (string_type, got dict[str, str])"]
        assert line["failed_field_count"] == 1

    def test_lists_ten_failed_fields_and_counts_them_all(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure()
        with pytest.raises(pydantic.ValidationError) as caught:
            pydantic.TypeAdapter(list[Till]).validate_python([{"label": 1}] * 12)

        line = _logged_with(capsys, logging.WARNING, caught.value)

        assert line["failed_fields"] == [f"{row}.label (string_type, got int)" for row in range(10)]
        assert line["failed_field_count"] == 12

    def test_failed_fields_the_call_passed_are_kept(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure()

        _log.warning(
            "Till failed",
            exc_info=_validation_error_raised_from_none(),
            extra={"failed_fields": ["label (list_type)"]},
        )

        (line,) = logged(capsys)
        assert line["failed_fields"] == ["label (list_type)"]

    def test_a_record_without_an_exception_is_unchanged(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure()

        _log.error("Till closed")

        (line,) = logged(capsys)
        assert "error_type" not in line
        assert "err" not in line

    def test_another_handler_still_sees_the_record_as_logged(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _configure()
        collected = _Collected()
        logging.getLogger().addHandler(collected)

        _log.warning("Till failed", exc_info=KeyError(_CANARY))

        (record,) = collected.records
        assert record.exc_info is not None
        assert not hasattr(record, "error_type")
        assert "err" not in logged(capsys)[0]
