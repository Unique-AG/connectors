import datetime as dt
import hashlib
import re
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import seed
from families import onenote
from model import Context, Step
from test_seed import UPNS

CTX = Context(seed.load_corpus(seed.CORPUS_DIR), UPNS, dt.date(2026, 10, 23), "extprops")
PHASES = {"onenote"}


def plan() -> list[Step]:
    return onenote.steps(CTX, "mia", PHASES)


class Pages:
    def __init__(self, titles: list[str]) -> None:
        self.titles = titles

    def get_all(self, path: str, params: dict[str, str]) -> list[dict[str, str | None]]:
        assert path == "/me/onenote/pages"
        return [{"id": f"p{n}", "title": title} for n, title in enumerate(self.titles)]


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
