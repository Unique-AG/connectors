import json
import logging
from collections.abc import Iterator

import pytest

from mcp_observability import PinoJsonFormatter
from mcp_observability import configure_logging


@pytest.fixture(autouse=True)
def root_handlers() -> Iterator[None]:
    """Each test starts and ends with the root logger it found."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    root.handlers = []
    yield
    root.handlers, root.level = handlers, level
    logging.getLogger("uvicorn.access").filters.clear()


def logged(capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    return [json.loads(line) for line in capsys.readouterr().err.splitlines()]


def test_a_record_is_one_pino_json_line_with_its_extra_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO")

    logging.getLogger("kiosk").info("sold %s", "tea", extra={"till": 3})

    (line,) = logged(capsys)
    assert line["level"] == 30
    assert line["msg"] == "sold tea"
    assert line["context"] == "kiosk"
    assert line["till"] == 3
    assert isinstance(line["time"], int)


def test_an_exception_is_logged_as_err(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")

    try:
        raise ValueError("bad till")
    except ValueError:
        logging.getLogger("kiosk").exception("failed")

    (line,) = logged(capsys)
    assert line["level"] == 50
    err = line["err"]
    assert isinstance(err, dict)
    assert err["name"] == "ValueError"
    assert err["message"] == "bad till"


def test_records_below_the_level_are_dropped(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("WARNING")

    logging.getLogger("kiosk").info("quiet")

    assert logged(capsys) == []


def test_configuring_twice_adds_one_handler() -> None:
    configure_logging("INFO")
    configure_logging("DEBUG")

    handlers = [
        h for h in logging.getLogger().handlers if isinstance(h.formatter, PinoJsonFormatter)
    ]
    assert len(handlers) == 1
    assert handlers[0].level == logging.DEBUG


@pytest.mark.parametrize(("path", "kept"), [("/probe", False), ("/metrics", False), ("/mcp", True)])
def test_access_lines_of_the_ops_routes_are_dropped(
    capsys: pytest.CaptureFixture[str], path: str, kept: bool
) -> None:
    configure_logging("INFO")

    logging.getLogger("uvicorn.access").info('127.0.0.1 - "GET %s HTTP/1.1" 200', path)

    assert (len(logged(capsys)) == 1) is kept
