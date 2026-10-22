import json
import subprocess
from pathlib import Path
from typing import cast

import pytest
from ruff.__main__ import find_ruff_bin

from mcp_architecture.lint import CODE_STYLE


def findings(tmp_path: Path, relative: str, text: str) -> list[str]:
    """The codes ruff finds in `relative`, a module of `shop` in its own package, with the code
    style passed as `mcp-architecture-lint` passes it."""
    path = tmp_path / "src" / "shop" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    (path.parent / "__init__.py").write_text("")
    path.write_text(text)
    result = subprocess.run(
        [
            find_ruff_bin(),
            "check",
            "--no-cache",
            "--output-format=json",
            "--config",
            CODE_STYLE,
            str(path),
        ],
        cwd=tmp_path,
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
def test_an_api_a_past_fix_replaced_is_banned(tmp_path: Path, source: str) -> None:
    assert "TID251" in findings(tmp_path, "upstream/client.py", source)


def test_a_context_function_takes_keyword_arguments_only(tmp_path: Path) -> None:
    source = "def get_product(product_id: str) -> str:\n    return product_id\n"

    assert findings(tmp_path, "contexts/products/get_product.py", source) == ["PLR0917"]
    assert findings(tmp_path, "mcp/tools/get_product.py", source) == []


def test_a_string_split_with_a_plus_breaks_the_style(tmp_path: Path) -> None:
    source = 'NOTE = (\n    "first half, "\n    + "second half"\n)\n'

    assert findings(tmp_path, "telemetry/notes.py", source) == ["ISC003"]


def test_a_docstring_summary_may_run_onto_a_second_line(tmp_path: Path) -> None:
    source = (
        "def total() -> int:\n"
        '    """Adds up every order the shop took today, including the ones it refunded\n'
        "    later.\n"
        '    """\n'
        "    return 0\n"
    )

    assert findings(tmp_path, "telemetry/totals.py", source) == []
