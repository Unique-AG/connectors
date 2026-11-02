"""Offline tests for the sharepoint seed family."""

import datetime as dt
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, override
from urllib.parse import unquote

import httpx
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import seed
from families import onenote, sharepoint
from model import ConfigError, Context
from test_seed import UPNS, FakeGraph, run

TARGET = "seed-v1 Move Target"
FOLDER = "seed-v1 Seed Files"
TEAM_FOLDER = "seed-v1 Team Files"
CHANNEL = "seed-v1 Long channel"
CORE = "files,sharepoint"
TREE = "files-tree"
TEAM_PHASES = "team-files"
ANCHOR = dt.date(2026, 10, 23)


class DriveFake(FakeGraph):
    """A tiny Graph with a OneDrive, a team library, a channel and upload sessions."""

    def __init__(self, upn: str = UPNS[0], *, library: bool = True) -> None:
        super().__init__(upn)
        self.library = library
        self.invites: list[dict[str, Any]] = []
        self.channels: dict[str, str] = {}
        self.items: dict[str, dict[str, dict[str, Any]]] = {"me": {}, "b!team": {}}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.uploaded: list[int] = []
        self.counter = 0

    def new(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}{self.counter}"

    def named(self, drive: str, name: str) -> dict[str, Any]:
        return next(i for i in self.items[drive].values() if i["name"] == name)

    def below(self, drive: str, name: str) -> list[str]:
        parent = self.named(drive, name)["id"]
        return sorted(i["name"] for i in self.items[drive].values() if i["parent"] == parent)

    def add(
        self, drive: str, parent: str, name: str, folder: bool, size: int = 0
    ) -> dict[str, Any]:
        item = {"id": self.new("it"), "name": name, "parent": parent, "folder": folder}
        item |= {"size": size, "modified": None}
        self.items[drive][item["id"]] = item
        return item

    def shown(self, item: dict[str, Any]) -> dict[str, Any]:
        shown = {"id": item["id"], "name": item["name"], "size": item["size"]}
        return shown | ({"folder": {"childCount": 0}} if item["folder"] else {})

    @override
    def handle(self, request: httpx.Request) -> httpx.Response:
        path = unquote(request.url.path).removeprefix("/v1.0")
        self.calls.append((request.method, path))
        if request.url.host == "upload.example":
            return self.upload(request, path)
        body = (
            json.loads(request.content)
            if request.headers.get("content-type") == "application/json"
            else None
        )
        if path == "/me":
            return httpx.Response(200, json={"id": "user-1", "userPrincipalName": self.upn})
        if path == "/me/joinedTeams":
            return httpx.Response(
                200, json={"value": [{"id": "team-1", "displayName": "seed-v1 team"}]}
            )
        if found := re.fullmatch(r"/me/drive/root:/(.+)", path):
            item = next(
                (
                    i
                    for i in self.items["me"].values()
                    if i["parent"] == "root" and i["name"] == found[1]
                ),
                None,
            )
            return httpx.Response(200, json=self.shown(item)) if item else self.missing()
        if path == "/groups/team-1/drive":
            return httpx.Response(200, json={"id": "b!team"}) if self.library else self.missing()
        if found := re.fullmatch(r"/teams/team-1/channels(?:/([^/]+)/filesFolder)?", path):
            return self.channel(found[1], body, request.method)
        found = re.fullmatch(r"/(?:me/drive|drives/([^/]+))/(?:root|items/([^/:]+))(.*)", path)
        if found is None:
            return httpx.Response(
                400, json={"error": {"code": "fakeUnknownRoute", "message": path}}
            )
        drive, parent, tail = found[1] or "me", found[2] or "root", found[3]
        return self.item(request, drive, parent, tail, body)

    def missing(self) -> httpx.Response:
        return httpx.Response(404, json={"error": {"code": "itemNotFound", "message": "no"}})

    def channel(self, channel: str | None, body: Any, method: str) -> httpx.Response:
        if channel is not None and not self.library:
            return self.missing()
        if channel is not None:
            name = self.channels[channel]
            folder = next((i for i in self.items["b!team"].values() if i["name"] == name), None)
            folder = folder or self.add("b!team", "root", name, True)
            return httpx.Response(200, json=self.shown(folder))
        if method == "POST":
            self.channels[self.new("ch")] = body["displayName"]
            return httpx.Response(
                201, json={"id": f"ch{self.counter}", "displayName": body["displayName"]}
            )
        return httpx.Response(
            200, json={"value": [{"id": i, "displayName": n} for i, n in self.channels.items()]}
        )

    def item(
        self, request: httpx.Request, drive: str, parent: str, tail: str, body: Any
    ) -> httpx.Response:
        method = request.method
        if tail == "/children" and method == "GET":
            value = [self.shown(i) for i in self.items[drive].values() if i["parent"] == parent]
            return httpx.Response(200, json={"value": value})
        if tail == "/children":
            return self.create(drive, parent, body["name"], True, 0)
        if tail == "/invite":
            self.invites.append(body)
            return httpx.Response(200, json={"value": []})
        if method == "DELETE":
            self.drop(drive, parent)
            return httpx.Response(204)
        found = re.fullmatch(r":/(.+):/(content|createUploadSession)", tail)
        if found is None:
            return httpx.Response(
                400, json={"error": {"code": "fakeUnknownRoute", "message": tail}}
            )
        if found[2] == "content":
            return self.create(drive, parent, found[1], False, len(request.content))
        url = f"https://upload.example/{self.new('s')}"
        self.sessions[url] = {
            "drive": drive,
            "parent": parent,
            "name": found[1],
            "item": body["item"],
            "got": 0,
        }
        return httpx.Response(200, json={"uploadUrl": url})

    def create(self, drive: str, parent: str, name: str, folder: bool, size: int) -> httpx.Response:
        if any(i["parent"] == parent and i["name"] == name for i in self.items[drive].values()):
            return httpx.Response(
                409, json={"error": {"code": "nameAlreadyExists", "message": name}}
            )
        return httpx.Response(201, json=self.shown(self.add(drive, parent, name, folder, size)))

    def drop(self, drive: str, identifier: str) -> None:
        for child in [i["id"] for i in self.items[drive].values() if i["parent"] == identifier]:
            self.drop(drive, child)
        self.items[drive].pop(identifier, None)

    def upload(self, request: httpx.Request, path: str) -> httpx.Response:
        session = self.sessions[f"https://upload.example{path}"]
        span = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", request.headers["content-range"])
        assert span is not None
        session["got"] += len(request.content)
        self.uploaded.append(len(request.content))
        if session["got"] < int(span[3]):
            return httpx.Response(202, json={})
        item = self.add(session["drive"], session["parent"], session["name"], False, session["got"])
        item["modified"] = session["item"].get("fileSystemInfo", {}).get("lastModifiedDateTime")
        return httpx.Response(201, json=self.shown(item))


def apply(phases: str, index: int, fake: FakeGraph) -> int:
    return run(["apply", "--as", str(index), "--phases", phases], fake)


def context() -> Context:
    return Context(seed.load_corpus(seed.CORPUS_DIR), UPNS, ANCHOR, "extprops")


def planned(owner: str, phases: set[str]) -> list[Any]:
    return sharepoint.steps(context(), owner, phases)


@pytest.fixture(autouse=True)
def only_this_family(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seed, "FAMILIES", (sharepoint,))


def names(fake: FakeGraph) -> list[str]:
    return sorted(item["name"] for item in fake.drive.values())


def test_the_phase_creates_the_move_target_once() -> None:
    fake = FakeGraph()
    assert "sharepoint" in seed.PHASES
    assert run(["apply", "--as", "1", "--phases", "sharepoint"], fake) == 0
    assert names(fake).count(TARGET) == 1
    assert run(["apply", "--as", "1", "--phases", "sharepoint"], fake) == 0
    assert names(fake).count(TARGET) == 1


def test_the_phase_adds_nothing_for_the_other_personas() -> None:
    fake = FakeGraph(UPNS[1])
    assert run(["apply", "--as", "2", "--phases", "sharepoint"], fake) == 0
    assert TARGET not in names(fake)


def test_the_sweep_deletes_only_case_items_and_case_folders_in_the_seed_folder_and_the_target() -> (
    None
):
    fake = FakeGraph()
    fake.teams = []
    assert run(["apply", "--as", "1", "--phases", "files,sharepoint"], fake) == 0
    folder = next(i["id"] for i in fake.drive.values() if i["name"] == FOLDER)
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
    fake.teams = []
    assert run(["cleanup", "--cases", "--as", "1"], fake) == 0
    assert not [call for call in fake.calls if call[0] == "DELETE"]


class TestTree:
    def test_the_phase_adds_folders_in_folders_and_files_in_both_and_a_second_run_adds_nothing(
        self,
    ) -> None:
        fake = DriveFake()
        assert apply(f"files,{TREE}", 1, fake) == 0
        assert fake.below("me", "seed-v1 Contracts") == [
            "seed-v1 2026",
            "seed-v1 Archive",
            "seed-v1 Contracts overview.txt",
        ]
        assert fake.below("me", "seed-v1 2026") == ["seed-v1 Contract 2026.txt"]
        assert fake.below("me", "seed-v1 Reports") == [
            "seed-v1 Report A.txt",
            "seed-v1 Report B.txt",
            "seed-v1 Report C.docx",
        ]
        before = len(fake.items["me"])
        fake.calls.clear()
        assert apply(f"files,{TREE}", 1, fake) == 0
        assert len(fake.items["me"]) == before
        writes = [c for c in fake.calls if c[0] in ("POST", "PUT") and "/invite" not in c[1]]
        assert writes == []

    def test_the_seed_folder_holds_a_text_of_2000_characters_and_a_picture(self) -> None:
        fake = DriveFake()
        assert apply(TREE, 1, fake) == 0
        assert fake.named("me", "seed-v1 Text 2000.txt")["size"] == 2000
        assert fake.named("me", "seed-v1 Gallery.png")["size"] == len(
            onenote.ASSETS["seed-v1 Gallery picture.png"]
        )
        assert "seed-v1 Read me first.txt" in fake.below("me", FOLDER)

    def test_the_order_files_carry_their_edit_times_through_the_upload_session(self) -> None:
        fake = DriveFake()
        assert apply(TREE, 1, fake) == 0
        found = {n: fake.named("me", f"seed-v1 Order {n}.txt")["modified"] for n in "ABC"}
        assert found == {
            "A": "2026-10-20T00:00:00Z",
            "B": "2026-10-21T00:00:00Z",
            "C": "2026-10-22T00:00:00Z",
        }
        assert fake.below("me", "seed-v1 Ordered") == [f"seed-v1 Order {n}.txt" for n in "ABC"]

    def test_anna_adds_the_newest_order_file_and_shares_it_with_mia_for_reading(self) -> None:
        fake = DriveFake(UPNS[1])
        assert apply(TREE, 2, fake) == 0
        assert fake.named("me", "seed-v1 Order D.txt")["modified"] == "2026-10-22T23:00:00Z"
        assert [i["name"] for i in fake.items["me"].values() if not i["folder"]] == [
            "seed-v1 Order D.txt"
        ]
        assert fake.invites == [
            {
                "recipients": [{"email": UPNS[0]}],
                "roles": ["read"],
                "requireSignIn": True,
                "sendInvitation": False,
            }
        ]

    def test_tom_gets_nothing_and_a_phase_that_is_off_gets_nothing(self) -> None:
        assert planned("tom", {TREE, "files-big", "team-files"}) == []
        assert planned("anna", {"files-big", "team-files", "sharepoint"}) == []
        assert planned("mia", {"mail"}) == []

    def test_every_step_passes_the_address_check_and_names_no_address_but_a_test_user(self) -> None:
        for owner in ("mia", "anna"):
            steps = planned(owner, set(sharepoint.PHASES))
            seed.check_recipients(steps, UPNS)
        assert all("@" not in step.path for step in planned("mia", set(sharepoint.PHASES)))

    def test_an_unknown_file_kind_stops_the_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        corpus = sharepoint._corpus()  # pyright: ignore[reportPrivateUsage]
        broken = {**corpus, "files": [{"name": "x", "kind": "zip"}]}
        monkeypatch.setattr(sharepoint, "_corpus", lambda: broken)
        with pytest.raises(ConfigError, match="unknown file kind zip"):
            planned("mia", {TREE})

    def test_cleanup_deletes_the_items_of_the_phase_and_keeps_the_rest(self) -> None:
        fake = DriveFake()
        assert apply(f"files,{TREE},files-big", 1, fake) == 0
        folder = fake.named("me", FOLDER)["id"]
        fake.add("me", folder, "seed-v1 Somebody else.txt", False)
        assert run(["cleanup", "--as", "1", "--phases", TREE], fake) == 0
        left = fake.below("me", FOLDER)
        assert "seed-v1 Somebody else.txt" in left
        assert "seed-v1 Scan 10MiB.bin" in left
        assert "seed-v1 Project Plan.docx" in left
        assert not {
            "seed-v1 Contracts",
            "seed-v1 Reports",
            "seed-v1 Ordered",
            "seed-v1 Text 2000.txt",
        } & set(left)
        assert "seed-v1 Report A.txt" not in {i["name"] for i in fake.items["me"].values()}


class TestBig:
    def test_two_files_of_10_mib_and_one_byte_more_go_up_in_chunks_of_the_session(self) -> None:
        fake = DriveFake()
        assert apply("files-big", 1, fake) == 0
        assert fake.named("me", "seed-v1 Scan 10MiB.bin")["size"] == 10 * 1024 * 1024
        assert fake.named("me", "seed-v1 Scan over.bin")["size"] == 10 * 1024 * 1024 + 1
        assert len(fake.uploaded) == 2 * math.ceil(10 * 1024 * 1024 / seed.CHUNK)
        assert max(fake.uploaded) == seed.CHUNK
        fake.calls.clear()
        assert apply("files-big", 1, fake) == 0
        assert [c for c in fake.calls if c[0] in ("POST", "PUT")] == []

    def test_the_manifest_lists_both_files_with_their_generator_and_size(self) -> None:
        manifest = seed.corpus_manifest(context())
        big = {b["name"]: b for b in manifest["binaries"] if b["name"].startswith("seed-v1 Scan")}
        assert {n: (b["generator"], b["size"]) for n, b in big.items()} == {
            "seed-v1 Scan 10MiB.bin": ("filler", 10485760),
            "seed-v1 Scan over.bin": ("filler", 10485761),
        }
        raw = seed.docgen.generate("filler", 10485760, "scan-10mib")
        assert big["seed-v1 Scan 10MiB.bin"]["sha256"] == hashlib.sha256(raw).hexdigest()


class TestTeam:
    def test_mia_adds_the_channel_its_folder_and_the_library_files_and_a_second_run_adds_nothing(
        self,
    ) -> None:
        fake = DriveFake()
        assert apply(TEAM_PHASES, 1, fake) == 0
        assert list(fake.channels.values()) == [CHANNEL]
        assert fake.below("b!team", CHANNEL) == ["seed-v1 Channel Notes.txt"]
        assert fake.below("b!team", TEAM_FOLDER) == [
            "seed-v1 Team Charter.docx",
            "seed-v1 Team Contracts",
            "seed-v1 Team Drafts",
        ]
        assert fake.below("b!team", "seed-v1 Team Contracts") == ["seed-v1 Team Notes.txt"]
        assert fake.below("b!team", "seed-v1 Team Drafts") == ["seed-v1 Team Budget.xlsx"]
        before = len(fake.items["b!team"])
        fake.calls.clear()
        assert apply(TEAM_PHASES, 1, fake) == 0
        assert len(fake.items["b!team"]) == before and len(fake.channels) == 1
        assert [c for c in fake.calls if c[0] in ("POST", "PUT")] == []

    def test_a_library_that_is_not_ready_stops_the_run_and_the_next_run_continues(self) -> None:
        fake = DriveFake(library=False)
        assert apply(TEAM_PHASES, 1, fake) == ConfigError.code
        assert fake.items["b!team"] == {}
        fake.library = True
        assert apply(TEAM_PHASES, 1, fake) == 0
        assert len(fake.channels) == 1
        assert "seed-v1 Team Charter.docx" in fake.below("b!team", TEAM_FOLDER)

    def test_the_guard_of_the_client_lets_the_run_touch_the_team_only_through_learned_ids(
        self,
    ) -> None:
        fake = DriveFake()
        assert apply(TEAM_PHASES, 1, fake) == 0
        paths = {path for _, path in fake.calls}
        assert any(p.startswith("/drives/b!team/") for p in paths)
        assert {p for p in paths if p.startswith("/teams/")} == {
            "/teams/team-1/channels",
            "/teams/team-1/channels/ch1/filesFolder",
        }

    def test_cleanup_deletes_the_library_folder_and_the_channel_note_and_keeps_the_channel(
        self,
    ) -> None:
        fake = DriveFake()
        assert apply(TEAM_PHASES, 1, fake) == 0
        assert run(["cleanup", "--as", "1", "--phases", TEAM_PHASES], fake) == 0
        left = {i["name"] for i in fake.items["b!team"].values()}
        assert left == {CHANNEL}
        assert list(fake.channels.values()) == [CHANNEL]

    def test_the_sweep_reaches_case_items_below_seed_folders_in_both_drives(self) -> None:
        fake = DriveFake()
        assert apply(f"files,{TREE},{TEAM_PHASES}", 1, fake) == 0
        contracts = fake.named("me", "seed-v1 Contracts")["id"]
        team = fake.named("b!team", TEAM_FOLDER)["id"]
        fake.add("me", contracts, "seed-v1 case-inside", False)
        fake.add("b!team", team, "seed-v1 case-copy", True)
        outside = fake.add("me", "root", "Other", True)
        fake.add("me", outside["id"], "seed-v1 case-hidden", False)
        assert run(["cleanup", "--cases", "--as", "1"], fake) == 0
        assert "seed-v1 case-inside" not in {i["name"] for i in fake.items["me"].values()}
        assert "seed-v1 case-copy" not in {i["name"] for i in fake.items["b!team"].values()}
        assert "seed-v1 case-hidden" in {i["name"] for i in fake.items["me"].values()}

    def test_the_manifest_holds_the_names_that_the_cases_read(self) -> None:
        strings = set(seed.corpus_manifest(context())["strings"])
        assert {
            CHANNEL,
            TEAM_FOLDER,
            "seed-v1 Channel Notes.txt",
            "seed-v1 Team Charter.docx",
        } <= strings
        assert {"seed-v1 Order D.txt", "seed-v1 Gallery.png", "seed-v1 Ordered"} <= strings
