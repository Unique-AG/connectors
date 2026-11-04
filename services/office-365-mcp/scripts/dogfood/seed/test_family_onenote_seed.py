import datetime as dt
import hashlib
import json
import re
import sys
import zlib
from pathlib import Path
from typing import Any, override

import httpx
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import seed
from families import onenote
from model import ConfigError, Context, Step
from test_seed import UPNS, FakeGraph, run

CTX = Context(seed.load_corpus(seed.CORPUS_DIR), UPNS, dt.date(2026, 10, 23), "extprops")
PHASES = {"onenote"}


def plan() -> list[Step]:
    return onenote.steps(CTX, "mia", PHASES)


class Pages:
    def __init__(self, titles: list[str]) -> None:
        self.titles = titles

    def request(self, method: str, path: str, **_: object) -> httpx.Response:
        assert method == "GET"
        if path == "/me/joinedTeams":
            return httpx.Response(200, json={"value": []})
        assert path == "/me/onenote/pages"
        rows = [{"id": f"p{n}", "title": title} for n, title in enumerate(self.titles)]
        return httpx.Response(200, json={"value": rows})


def test_only_mia_gets_notebooks_and_only_in_its_phase() -> None:
    assert onenote.steps(CTX, "anna", PHASES) == []
    assert onenote.steps(CTX, "tom", PHASES) == []
    assert onenote.steps(CTX, "mia", {"mail"}) == []
    assert "onenote" in seed.PHASES
    assert plan()[0].kind == "lookup"


def test_a_parent_is_created_before_its_children_and_every_name_is_tagged() -> None:
    created = [step for step in plan() if step.kind == "create"]
    made: set[str] = set()
    for step in plan():
        for ref in re.findall(r"\{([^}]+)\}", step.path):
            assert ref in made, f"{step.path} comes before {ref}"
        if step.kind == "create":
            made.add(str(step.key))
    assert len(made) == len(created)
    assert all(str(step.key).startswith("onenote:seed-v1 ") for step in created)
    assert all(step.method == "POST" for step in plan() if step.kind == "create")


def test_the_notebooks_hold_two_sections_a_group_and_pages() -> None:
    paths = [step.path for step in plan() if step.kind == "create"]
    notes = "{onenote:seed-v1 Dogfood Notes}"
    assert paths.count(f"/me/onenote/notebooks/{notes}/sections") == 2
    assert paths.count(f"/me/onenote/notebooks/{notes}/sectionGroups") == 1
    assert sum(path.endswith("/pages") for path in paths) == 4


def test_a_page_is_html_and_the_gallery_page_adds_a_png() -> None:
    pages = {step.key: step for step in plan() if step.path.endswith("/pages") and step.body}
    launch = pages["onenote:seed-v1 Launch plan"]
    gallery = pages["onenote:seed-v1 Gallery"]
    assert launch.content_type == "text/html"
    assert b'<p data-id="intro">' in launch.body
    assert b"<title>seed-v1 Launch plan</title>" in launch.body
    assert str(gallery.content_type).startswith("multipart/form-data; boundary=")
    png = gallery.body.split(b"image/png\r\n\r\n")[1].split(b"\r\n--")[0]
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert b"\x00" * 4 + b"IEND" in png
    assert zlib.crc32(b"IEND") == int.from_bytes(png[-4:], "big")


def test_no_step_names_an_address() -> None:
    seed.check_recipients(plan(), UPNS)


def test_the_manifest_keeps_the_container_names() -> None:
    manifest = seed.corpus_manifest(CTX)
    assert {"seed-v1 Dogfood Notes", "seed-v1 Scratch", "seed-v1 Pad"} <= set(manifest["strings"])


def test_the_sweep_names_pages_with_a_case_title_only() -> None:
    graph = Pages(["seed-v1 Launch plan", "seed-v1 case-onenote_create_page-seed", "Mia Plan", ""])
    found = list(onenote.sweep(graph, "mia"))  # pyright: ignore[reportArgumentType]
    assert found == [("DELETE", "/me/onenote/pages/p1")]
    assert list(onenote.sweep(graph, "anna")) == []  # pyright: ignore[reportArgumentType]


def test_the_manifest_holds_the_page_texts_and_the_hash_of_the_picture_alone() -> None:
    manifest = seed.corpus_manifest(CTX)
    assert {"seed-v1 Gallery", "This page holds one picture.", "A blue square"} <= set(
        manifest["strings"]
    )
    picture = next(b for b in manifest["binaries"] if b["name"].endswith("Gallery picture.png"))
    assert picture["sha256"] == hashlib.sha256(onenote._png()).hexdigest()  # pyright: ignore[reportPrivateUsage]
    page = next(s for s in plan() if s.key == "onenote:seed-v1 Gallery")
    assert hashlib.sha256(page.body).hexdigest() != picture["sha256"]


GROUP = "/groups/team-1/onenote"
NOT_FOUND = {"error": {"code": "itemNotFound", "message": "no"}}


class NoteFake(FakeGraph):
    """Answers the OneNote calls of the seed: a list for each collection path, and delete."""

    def __init__(self, *, group: bool = True) -> None:
        super().__init__()
        self.rows: dict[str, list[dict[str, Any]]] = {}
        self.group, self.posts = group, 0

    def everywhere(self, root: str) -> list[dict[str, Any]]:
        found = list(self.rows.get(f"{root}/pages", []))
        for key, rows in self.rows.items():
            if key.startswith(f"{root}/sections/") and key.endswith("/pages"):
                found += rows
        return found

    def titles(self, root: str) -> list[str]:
        return sorted(str(row["title"]) for row in self.everywhere(root))

    @override
    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v1.0")
        if "/onenote/" not in path:
            return super().handle(request)
        self.calls.append((request.method, path))
        if path.startswith("/groups/") and not self.group:
            return httpx.Response(404, json=NOT_FOUND)
        if request.method == "DELETE":
            for rows in self.rows.values():
                rows[:] = [row for row in rows if row["id"] != path.rsplit("/", 1)[1]]
            return httpx.Response(204)
        root = path.partition("/onenote/")[0] + "/onenote"
        if request.method == "GET" and path == f"{root}/pages":
            return httpx.Response(200, json={"value": self.everywhere(root)})
        rows = self.rows.setdefault(path, [])
        if request.method == "GET":
            return httpx.Response(200, json={"value": rows})
        self.posts += 1
        text = request.content.decode(errors="replace")
        row: dict[str, Any] = {"id": f"n{self.posts}", "size": len(request.content)}
        if title := re.search(r"<title>(.*?)</title>", text):
            row["title"] = title[1]
        else:
            row["displayName"] = json.loads(text)["displayName"]
        rows.append(row)
        return httpx.Response(201, json=row)


def seeded(fake: NoteFake, phases: str) -> int:
    return run(["apply", "--as", "1", "--phases", phases], fake)


@pytest.fixture
def only_onenote(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seed, "FAMILIES", (onenote,))


def test_the_new_phases_are_part_of_the_phase_list_and_only_mia_runs_them() -> None:
    assert {"onenote-group", "onenote-big"} <= set(seed.PHASES)
    for phase in ("onenote-group", "onenote-big"):
        assert onenote.steps(CTX, "anna", {phase}) == []
        assert onenote.steps(CTX, "tom", {phase}) == []
        assert onenote.steps(CTX, "mia", {"mail"}) == []


def test_the_group_plan_looks_for_the_team_first_and_then_builds_below_its_notebook_root() -> None:
    group = onenote.steps(CTX, "mia", {"onenote-group"})
    team = group[0]
    assert (team.method, team.path, team.lookup, team.learns) == (
        "GET",
        "/me/joinedTeams",
        "named",
        "team",
    )
    made = {"onenote-group:seed-v1 team"}
    for step in group[1:]:
        assert step.path.startswith("/groups/{onenote-group:seed-v1 team}/onenote/")
        for ref in re.findall(r"\{([^}]+)\}", step.path):
            assert ref in made, f"{step.path} comes before {ref}"
        if step.kind == "create":
            made.add(str(step.key))
    assert [s.key for s in group if s.kind == "create"] == [
        "onenote-group:seed-v1 Shared Notes",
        "onenote-group:seed-v1 Team notes",
        "onenote-group:seed-v1 Team plan",
    ]


def test_the_team_page_holds_three_paragraphs_with_ids_and_its_texts_are_corpus_text() -> None:
    page = onenote.steps(CTX, "mia", {"onenote-group"})[-1]
    for name in ("intro", "plan", "risk"):
        assert f'<p data-id="{name}">'.encode() in page.body
    strings = set(seed.corpus_manifest(CTX)["strings"])
    assert {
        "The team plan has three parts.",
        "seed-v1 Team plan",
        "seed-v1 Shared Notes",
    } <= strings


def test_the_big_page_is_900000_bytes_of_generated_html_and_the_manifest_names_its_generator() -> (
    None
):
    page = onenote.steps(CTX, "mia", {"onenote-big"})[-1]
    assert (page.content_type, len(page.body)) == ("text/html", 900_000)
    assert page.generated == ("onenote-html", 900_000, "seed-v1 Big page")
    assert page.body.startswith(b"<!DOCTYPE html><html><head><title>seed-v1 Big page</title>")
    found = [
        b for b in seed.corpus_manifest(CTX)["binaries"] if b.get("generator") == "onenote-html"
    ]
    assert [(b["size"], b["label"], b["sha256"]) for b in found] == [
        (900_000, "seed-v1 Big page", hashlib.sha256(page.body).hexdigest())
    ]


@pytest.mark.usefixtures("only_onenote")
def test_the_group_phase_makes_its_notebook_section_and_page_once() -> None:
    fake = NoteFake()
    assert seeded(fake, "onenote-group") == 0
    assert [r["displayName"] for r in fake.rows[f"{GROUP}/notebooks"]] == ["seed-v1 Shared Notes"]
    assert fake.titles(GROUP) == ["seed-v1 Team plan"]
    first = fake.posts
    assert seeded(fake, "onenote-group") == 0
    assert fake.posts == first == 3


@pytest.mark.usefixtures("only_onenote")
def test_the_big_phase_adds_one_page_to_an_existing_section_and_stops_without_the_section() -> None:
    fake = NoteFake()
    assert seeded(fake, "onenote-big") == ConfigError.code
    assert fake.titles("/me/onenote") == []
    assert seeded(fake, "onenote,onenote-big") == 0
    assert "seed-v1 Big page" in fake.titles("/me/onenote")
    first = fake.posts
    assert seeded(fake, "onenote,onenote-big") == 0
    assert fake.posts == first
    big = next(r for r in fake.everywhere("/me/onenote") if r["title"] == "seed-v1 Big page")
    assert big["size"] == 900_000


@pytest.mark.usefixtures("only_onenote")
def test_cleanup_deletes_the_pages_of_the_phase_only_and_keeps_notebooks_and_sections() -> None:
    fake = NoteFake()
    assert seeded(fake, "onenote,onenote-group,onenote-big") == 0
    assert run(["cleanup", "--as", "1", "--phases", "onenote-big"], fake) == 0
    assert "seed-v1 Big page" not in fake.titles("/me/onenote")
    assert "seed-v1 Launch plan" in fake.titles("/me/onenote")
    assert fake.titles(GROUP) == ["seed-v1 Team plan"]
    assert run(["cleanup", "--as", "1", "--phases", "onenote-group"], fake) == 0
    assert fake.titles(GROUP) == []
    assert [r["displayName"] for r in fake.rows[f"{GROUP}/notebooks"]] == ["seed-v1 Shared Notes"]


@pytest.mark.usefixtures("only_onenote")
@pytest.mark.parametrize("group", [True, False])
def test_the_sweep_deletes_case_pages_of_the_user_and_of_the_team_and_a_team_without_notes_is_skipped(
    group: bool,
) -> None:
    fake = NoteFake(group=group)
    fake.rows["/me/onenote/pages"] = [
        {"id": "p1", "title": "seed-v1 case-a"},
        {"id": "p2", "title": "seed-v1 Launch plan"},
    ]
    fake.rows[f"{GROUP}/pages"] = [
        {"id": "g1", "title": "seed-v1 case-team"},
        {"id": "g2", "title": "seed-v1 Team plan"},
    ]
    assert run(["cleanup", "--cases", "--as", "1"], fake) == 0
    deleted = sorted(path for method, path in fake.calls if method == "DELETE")
    assert deleted == (["/groups/team-1/onenote/pages/g1"] if group else []) + [
        "/me/onenote/pages/p1"
    ]
