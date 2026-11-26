import pathlib
import re

import pytest

from office_365_mcp.tools import TOOL_NAMES

_README = (pathlib.Path(__file__).resolve().parents[1] / "docs" / "README.md").read_text(
    encoding="utf-8"
)


@pytest.mark.parametrize(
    "sentence",
    [r"\*\*Size:\*\* (\d+) tools in total\.", r"This reference lists all (\d+) tools\."],
)
def test_the_readme_states_the_number_of_registered_tools(sentence: str) -> None:
    match = re.search(sentence, _README)
    assert match is not None, f"the README no longer holds {sentence!r}"
    assert int(match.group(1)) == len(TOOL_NAMES)


def test_the_tool_reference_has_one_row_for_each_registered_tool() -> None:
    reference = _README.split("This reference lists all")[1]
    rows = re.findall(r"^\| `([a-z0-9_]+)` \|", reference, re.M)
    assert sorted(rows) == sorted(TOOL_NAMES)
