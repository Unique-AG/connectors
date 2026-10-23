import importlib
import sys
from pathlib import Path

import pytest

from mcp_architecture.check import SNAPSHOT, check_service, main

KEPT = {
    "mask": "True",
    "tool": (
        "    @mcp.tool\n"
        "    def get_product(product_id: Annotated[str, Field(description='An id.')]) -> str:\n"
        '        """Read one product."""\n'
        "        return product_id\n"
    ),
}
OFFLINE_SERVER = (
    "from collections.abc import AsyncGenerator\n"
    "from contextlib import asynccontextmanager\n"
    "from typing import Annotated\n\n"
    "from fastmcp import FastMCP\n"
    "from pydantic import Field\n\n\n"
    "@asynccontextmanager\n"
    "async def offline_server() -> AsyncGenerator[FastMCP]:\n"
    "    mcp = FastMCP(name='Kiosk', mask_error_details={mask})\n\n"
    "{tool}\n"
    "    yield mcp\n"
)
HIDDEN_SETTINGS = (
    "from pydantic_settings import BaseSettings, SettingsConfigDict\n\n\n"
    "class KioskSettings(BaseSettings):\n"
    "    model_config = SettingsConfigDict(hide_input_in_errors=True)\n"
)


def write_service(
    root: Path,
    *,
    package: str = "kiosk",
    settings: str = HIDDEN_SETTINGS,
    server: dict[str, str] | None = None,
) -> Path:
    """An MCP named after `package`, whose `tests/offline_server.py` builds `server`."""
    (root / "pyproject.toml").write_text(f'[project]\nname = "{package.replace("_", "-")}"\n')
    source = root / "src" / package
    source.mkdir(parents=True)
    (source / "__init__.py").write_text("")
    (source / "settings.py").write_text(settings)
    (source / "main.py").write_text(f"from {package}.settings import KioskSettings\n")
    (root / "tests").mkdir()
    (root / "tests" / "offline_server.py").write_text(OFFLINE_SERVER.format(**(server or KEPT)))
    return root


@pytest.fixture(autouse=True)
def importable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "path", [str(tmp_path / "src"), *sys.path])
    importlib.invalidate_caches()


async def test_an_mcp_that_keeps_every_rule_passes(tmp_path: Path) -> None:
    service = write_service(tmp_path)
    await check_service(service, update=True)

    assert await check_service(service) == []


async def test_update_records_what_a_client_sees(tmp_path: Path) -> None:
    service = write_service(tmp_path)

    assert await check_service(service, update=True) == []
    assert '"name": "get_product"' in (service / SNAPSHOT).read_text()


async def test_a_missing_snapshot_is_a_finding(tmp_path: Path) -> None:
    assert await check_service(write_service(tmp_path)) == [
        f"{SNAPSHOT} is missing. Run `uv run poe surface`."
    ]


async def test_a_changed_tool_surface_is_a_finding_with_its_diff(tmp_path: Path) -> None:
    service = write_service(tmp_path)
    await check_service(service, update=True)
    (service / SNAPSHOT).write_text((service / SNAPSHOT).read_text().replace("Read", "Fetch"))

    (finding,) = await check_service(service)

    assert finding.startswith(f"What a client sees no longer matches {SNAPSHOT}.")
    assert '-    "description": "Fetch one product.",' in finding
    assert '+    "description": "Read one product.",' in finding


@pytest.mark.parametrize(
    ("server", "expected"),
    [
        (
            {
                **KEPT,
                "tool": "    @mcp.tool\n    def get_product(product_id: str) -> str:\n"
                "        return product_id\n",
            },
            "Give these a docstring or a Field(description=...): "
            "['get_product', 'get_product(product_id)']",
        ),
        ({**KEPT, "mask": "False"}, "Create the server with mask_error_details=True."),
    ],
    ids=["an undescribed tool", "unmasked error details"],
)
async def test_a_server_that_breaks_a_rule_is_a_finding(
    tmp_path: Path, server: dict[str, str], expected: str
) -> None:
    service = write_service(tmp_path, server=server)

    assert expected in await check_service(service, update=True)


async def test_a_tool_whose_input_combines_schemas_at_its_root_is_a_finding(
    tmp_path: Path,
) -> None:
    either_key = (
        "    from fastmcp.tools import Tool\n\n"
        "    def find_product(sku: str) -> str:\n"
        '        """Find a product."""\n'
        "        return sku\n\n"
        "    schema = {'type': 'object', 'anyOf': [{'required': ['sku']}],\n"
        "              'properties': {'sku': {'type': 'string', 'description': 'A SKU.'}}}\n"
        "    tool = Tool.from_function(find_product)\n"
        "    mcp.add_tool(tool.model_copy(update={'parameters': schema}))\n"
    )
    service = write_service(tmp_path, server={**KEPT, "tool": either_key})

    assert await check_service(service, update=True) == [
        "Some clients reject these tools, make their input a plain object: ['find_product: anyOf']"
    ]


async def test_settings_that_would_print_their_input_are_a_finding(tmp_path: Path) -> None:
    shown = (
        "from pydantic_settings import BaseSettings\n\n\nclass KioskSettings(BaseSettings): ...\n"
    )
    service = write_service(tmp_path, package="leaky_kiosk", settings=shown)

    assert await check_service(service, update=True) == [
        "Build the model_config of these with mcp_configs.shared_config: "
        "['leaky_kiosk.settings.KioskSettings']"
    ]


async def test_a_file_that_changes_its_type_check_is_a_finding(tmp_path: Path) -> None:
    service = write_service(tmp_path)
    (service / "src" / "kiosk" / "loose.py").write_text("# pyright: basic\n")

    assert await check_service(service, update=True) == [
        "Remove these `# pyright:` comments, so each file keeps the type check of the whole MCP: "
        "['src/kiosk/loose.py:1']"
    ]


async def test_a_file_that_turns_a_lint_rule_off_is_a_finding(tmp_path: Path) -> None:
    service = write_service(tmp_path)
    (service / "src" / "kiosk" / "loose.py").write_text("# ruff: noqa: T201\nprint('x')\n")

    assert await check_service(service, update=True) == [
        "Remove these `# ruff: noqa` and `# ruff: disable` comments, and name the rule in a "
        "`# noqa: <rule>` on the line that needs it: ['src/kiosk/loose.py:1']"
    ]


async def test_an_mcp_without_an_offline_server_is_a_finding(tmp_path: Path) -> None:
    service = write_service(tmp_path)
    (service / "tests" / "offline_server.py").unlink()

    assert await check_service(service, update=True) == [
        "tests/offline_server.py has no `offline_server()`: the checks list the tools of the "
        "server it builds."
    ]


@pytest.mark.parametrize(("snapshot", "status"), [(True, 0), (False, 1)])
def test_main_exits_with_1_on_a_finding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    snapshot: bool,
    status: int,
) -> None:
    write_service(tmp_path)
    monkeypatch.chdir(tmp_path)
    if snapshot:
        with pytest.raises(SystemExit):
            main(update=True)

    with pytest.raises(SystemExit) as exit_:
        main()

    assert exit_.value.code == status
    assert ("Every architecture check passed." in capsys.readouterr().out) is snapshot
