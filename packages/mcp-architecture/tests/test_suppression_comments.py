from pathlib import Path

import pytest

from mcp_architecture import files_changing_their_type_check, files_turning_rules_off


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.mark.parametrize(
    "comment",
    ["# pyright: basic", "#pyright: reportAny=false", "# pyright: ignore"],
    ids=["a mode", "a report turned down", "an ignore without a rule"],
)
def test_a_comment_that_changes_the_type_check_is_listed(tmp_path: Path, comment: str) -> None:
    write(tmp_path, "src/kiosk/orders.py", f"{comment}\nx = 1\n")

    assert files_changing_their_type_check(tmp_path) == ["src/kiosk/orders.py:1"]


def test_an_ignore_that_names_its_rule_is_not_listed(tmp_path: Path) -> None:
    write(tmp_path, "tests/test_orders.py", "x: int = f()  # pyright: ignore[reportCallIssue]\n")

    assert files_changing_their_type_check(tmp_path) == []


def test_the_text_of_a_string_is_not_a_comment(tmp_path: Path) -> None:
    write(tmp_path, "src/kiosk/docs.py", 'EXAMPLE = "# pyright: basic"\n')

    assert files_changing_their_type_check(tmp_path) == []


def test_only_src_and_tests_are_read(tmp_path: Path) -> None:
    write(tmp_path, "scripts/release.py", "# pyright: basic\n")
    write(tmp_path, "tests/conftest.py", "# pyright: strict\n")

    assert files_changing_their_type_check(tmp_path) == ["tests/conftest.py:1"]


@pytest.mark.parametrize(
    "comment",
    ["# ruff: noqa: T201", "# ruff: noqa", "#ruff:disable[T201]", "# flake8: noqa: E501"],
    ids=["named rules", "every rule", "a range without its end", "flake8's spelling"],
)
def test_a_comment_that_turns_a_rule_off_for_the_file_is_listed(
    tmp_path: Path, comment: str
) -> None:
    write(tmp_path, "src/kiosk/orders.py", f'"""Orders."""\n\n{comment}\nx = 1\n')

    assert files_turning_rules_off(tmp_path, "kiosk") == ["src/kiosk/orders.py:3"]


def test_a_noqa_on_its_line_is_not_listed(tmp_path: Path) -> None:
    write(tmp_path, "tests/test_orders.py", "x = 1  # noqa: E501\n")

    assert files_turning_rules_off(tmp_path, "kiosk") == []


def test_the_generated_upstream_code_may_turn_a_rule_off(tmp_path: Path) -> None:
    write(tmp_path, "src/kiosk/upstream/generated/vendor_responses.py", "# ruff: noqa: E501\n")
    write(tmp_path, "src/kiosk/upstream/client.py", "# ruff: noqa: E501\n")

    assert files_turning_rules_off(tmp_path, "kiosk") == ["src/kiosk/upstream/client.py:1"]
