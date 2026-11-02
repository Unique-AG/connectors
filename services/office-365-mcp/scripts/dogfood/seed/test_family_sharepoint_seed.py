"""Offline tests for the sharepoint seed family."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pytest
import seed
from families import sharepoint
from test_seed import UPNS, FakeGraph, run

TARGET = "seed-v1 Move Target"


@pytest.fixture(autouse=True)
def only_this_family(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seed, "FAMILIES", (sharepoint,))


def names(fake: FakeGraph) -> list[str]:
    return sorted(item["name"] for item in fake.drive.values())


def test_the_phase_creates_the_move_target_once() -> None:
    fake = FakeGraph()
    assert "sharepoint" in seed.PHASES
    assert run(["apply", "--as", "1", "--phase", "sharepoint"], fake) == 0
    assert names(fake).count(TARGET) == 1
    assert run(["apply", "--as", "1", "--phase", "sharepoint"], fake) == 0
    assert names(fake).count(TARGET) == 1


def test_the_phase_adds_nothing_for_the_other_personas() -> None:
    fake = FakeGraph(UPNS[1])
    assert run(["apply", "--as", "2", "--phase", "sharepoint"], fake) == 0
    assert TARGET not in names(fake)


def test_the_sweep_deletes_only_case_items_and_case_folders_in_the_seed_folder_and_the_target() -> (
    None
):
    fake = FakeGraph()
    assert run(["apply", "--as", "1", "--phase", "files", "--phase", "sharepoint"], fake) == 0
    folder = next(i["id"] for i in fake.drive.values() if i["name"] == "seed-v1 Seed Files")
    target = next(i["id"] for i in fake.drive.values() if i["name"] == TARGET)
    for did, parent, name in (
        ("case-a", folder, "seed-v1 case-sharepoint_rename_item-notes.txt"),
        ("case-b", target, "seed-v1 case-sharepoint_move_item-budget.xlsx"),
        ("case-c", folder, "seed-v1 case-sharepoint_move_item-budget"),
        ("keep-a", target, "seed-v1 Budget Overview.xlsx"),
        ("keep-b", "root", "case-elsewhere"),
    ):
        fake.drive[did] = {"id": did, "name": name, "parent": parent, "folder": False}
    fake.calls.clear()
    assert run(["cleanup", "--cases", "--as", "1"], fake) == 0
    deletes = sorted(path for method, path in fake.calls if method == "DELETE")
    assert deletes == [f"/me/drive/items/case-{one}" for one in "abc"]
    assert {"keep-a", "keep-b", folder, target} <= set(fake.drive)


def test_the_sweep_does_nothing_in_an_empty_drive() -> None:
    fake = FakeGraph()
    assert run(["cleanup", "--cases", "--as", "1"], fake) == 0
    assert not [call for call in fake.calls if call[0] == "DELETE"]
