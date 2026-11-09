"""The "Start from what you want to do" table of `docs/README.md`.

Each row names a use case of `docs/use-cases.md` and the presets that a deployment turns on for it.
These tests check the table against the sidecars of `features/` and against `PRESETS`, so a preset
that lacks a tool of the use case fails here.
"""

import pathlib
import re
from collections.abc import Mapping, Sequence
from typing import cast

import pytest
import yaml

from office_365_mcp.tools import PRESETS

_SERVICE_ROOT = pathlib.Path(__file__).resolve().parents[1]
_README = (_SERVICE_ROOT / "docs" / "README.md").read_text(encoding="utf-8")
_FEATURES = sorted((_SERVICE_ROOT / "features").glob("*.feature"))
_ROW = re.compile(
    r"^\| \[[^\]]+\]\(use-cases\.md#(?P<anchor>[^)]+)\) \| [^|]+ \| (?P<presets>[^|]+) \| "
    + r"(?P<consent>[^|]+) \|$",
    re.M,
)
_PRESET_ROW = re.compile(
    r"^\| \[`(?P<name>[a-z-]+)`\]\(#[a-z-]+\) \| [^|]+ \| \d+ \| (?P<consent>[^|]+) \|$", re.M
)
_ADMIN_CONSENT = "⚠️ Yes"


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9 -]", "", title.lower()).replace(" ", "-")


def _title(feature: pathlib.Path) -> str:
    match = re.search(r"^Feature: (.+)$", feature.read_text(encoding="utf-8"), re.M)
    assert match, f"{feature.name} has no Feature line"
    return match.group(1)


def _tools_of(feature: pathlib.Path) -> set[str]:
    sidecar = cast(
        "Mapping[str, Mapping[str, Sequence[Mapping[str, str]]]]",
        yaml.safe_load(feature.with_suffix(".calls.yaml").read_text(encoding="utf-8")),
    )
    return {
        step["tool"]
        for entry in sidecar.values()
        for step in entry.get("chain", [])
        if "tool" in step
    } - {"get_me"}


def _rows() -> dict[str, tuple[list[str], str]]:
    return {
        row["anchor"]: (re.findall(r"`([a-z-]+)`", row["presets"]), row["consent"].strip())
        for row in (match.groupdict() for match in _ROW.finditer(_README))
    }


def _needs_consent() -> dict[str, bool]:
    return {
        row["name"]: _ADMIN_CONSENT in row["consent"]
        for row in (match.groupdict() for match in _PRESET_ROW.finditer(_README))
    }


_STEMS = [feature.stem for feature in _FEATURES]


class TestTheUseCaseTable:
    def test_it_has_one_row_for_each_use_case(self) -> None:
        assert sorted(_rows()) == sorted(_slug(_title(feature)) for feature in _FEATURES)

    @pytest.mark.parametrize("feature", _FEATURES, ids=_STEMS)
    def test_its_presets_hold_every_tool_of_the_use_case(self, feature: pathlib.Path) -> None:
        presets, _ = _rows()[_slug(_title(feature))]
        held = {tool for preset in presets for tool in PRESETS[preset]}

        assert _tools_of(feature) - held == set()

    @pytest.mark.parametrize("feature", _FEATURES, ids=_STEMS)
    def test_its_consent_column_follows_its_presets(self, feature: pathlib.Path) -> None:
        presets, consent = _rows()[_slug(_title(feature))]
        consenting = _needs_consent()

        assert consent == (_ADMIN_CONSENT if any(consenting[p] for p in presets) else "No")
