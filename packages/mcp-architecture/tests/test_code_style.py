import json
import subprocess
from pathlib import Path
from typing import cast

import pytest
from ruff.__main__ import find_ruff_bin

import mcp_architecture

CODE_STYLE = Path(mcp_architecture.__file__).parent / "code_style.toml"


@pytest.fixture
def service(tmp_path: Path) -> Path:
    """A service whose [tool.ruff] is the one the scaffold writes."""
    (tmp_path / "pyproject.toml").write_text(f'[tool.ruff]\nextend = "{CODE_STYLE}"\n')
    return tmp_path


def findings(service: Path, relative: str, text: str) -> list[str]:
    """The codes ruff finds in `relative`, a module of `shop` in its own package."""
    path = service / "src" / "shop" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    (path.parent / "__init__.py").write_text("")
    path.write_text(text)
    result = subprocess.run(
        [find_ruff_bin(), "check", "--no-cache", "--output-format=json", str(path)],
        cwd=service,
        capture_output=True,
        text=True,
        check=False,
    )
    return [
        str(finding["code"]) for finding in cast(list[dict[str, object]], json.loads(result.stdout))
    ]


@pytest.mark.parametrize(
    "source",
    [
        "from dataclasses import dataclass\n",
        "from urllib.parse import urljoin\n",
        "from ssl import create_default_context\n",
        "from html import escape\n",
        "from cryptography.hazmat.primitives.ciphers.aead import AESGCM\n",
    ],
)
def test_an_api_a_past_fix_replaced_is_banned(service: Path, source: str) -> None:
    assert "TID251" in findings(service, "upstream/client.py", source)


def test_a_function_takes_at_most_three_positional_arguments(service: Path) -> None:
    three = "def total(a: int, b: int, c: int, *, d: int) -> int:\n    return a + b + c + d\n"
    four = "def total(a: int, b: int, c: int, d: int) -> int:\n    return a + b + c + d\n"

    assert findings(service, "contexts/orders/total.py", three) == []
    assert findings(service, "mcp/tools/total.py", four) == ["PLR0917"]


def test_self_is_not_counted_as_a_positional_argument(service: Path) -> None:
    source = (
        "class Cart:\n"
        "    def total(self, a: int, b: int, c: int) -> int:\n"
        "        return a + b + c\n"
    )

    assert findings(service, "contexts/orders/cart.py", source) == []


def test_a_string_split_with_a_plus_breaks_the_style(service: Path) -> None:
    source = 'NOTE = (\n    "first half, "\n    + "second half"\n)\n'

    assert findings(service, "telemetry/notes.py", source) == ["ISC003"]


def test_a_docstring_summary_may_run_onto_a_second_line(service: Path) -> None:
    source = (
        "def total() -> int:\n"
        '    """Adds up every order the shop took today, including the ones it refunded\n'
        "    later.\n"
        '    """\n'
        "    return 0\n"
    )

    assert findings(service, "telemetry/totals.py", source) == []
