import importlib
import sys
from pathlib import Path

import pytest

from mcp_architecture import settings_showing_input_in_errors

SETTINGS = (
    "from typing import ClassVar\n\n"
    "from pydantic import SecretStr\n"
    "from pydantic_settings import BaseSettings, SettingsConfigDict\n\n\n"
    "class HiddenSettings(BaseSettings):\n"
    "    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(\n"
    "        hide_input_in_errors=True\n"
    "    )\n"
    "    api_key: SecretStr\n\n\n"
    "class ShownSettings(BaseSettings):\n"
    "    api_key: SecretStr\n"
)


def test_settings_that_would_print_their_input_are_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "vault"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "settings.py").write_text(SETTINGS)
    (package / "main.py").write_text("from vault.settings import HiddenSettings, ShownSettings\n")
    monkeypatch.setattr(sys, "path", [str(tmp_path), *sys.path])
    importlib.invalidate_caches()

    assert settings_showing_input_in_errors("vault") == ["vault.settings.ShownSettings"]
