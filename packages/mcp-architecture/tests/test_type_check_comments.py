from pathlib import Path

import pytest

from mcp_architecture import files_changing_their_type_check


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
