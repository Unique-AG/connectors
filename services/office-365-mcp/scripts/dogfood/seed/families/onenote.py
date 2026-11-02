import html
import struct
import zlib
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import docgen
import yaml
from model import Context, Step

from families.teams import TEAM_NAME

if TYPE_CHECKING:
    from seed import Graph

TAG = "seed-v1"
CASE = f"{TAG} case-"
OWNER = "mia"
ME = "/me/onenote"
ABSENT = (400, 403, 404)
PHASES: tuple[str, ...] = ("onenote", "onenote-group", "onenote-big")
CORPUS = Path(__file__).resolve().parents[1] / "corpus" / "onenote.yaml"
BOUNDARY = "seed-v1-onenote"
PICTURE = "imageBlock1"
PICTURE_SIDE = 64

type Spec = Mapping[str, Any]


def _named(name: str) -> str:
    return f"{TAG} {name}"


def _key(name: str, phase: str = "onenote") -> str:
    return f"{phase}:{_named(name)}"


def _ref(name: str, phase: str = "onenote") -> str:
    return "{" + _key(name, phase) + "}"


def _lookup(path: str, fields: str, phase: str = "onenote") -> Step:
    params = (("$select", fields), ("$top", "100"))
    return Step(phase, "lookup", "GET", path, params, lookup="named")


def _create(path: str, name: str, phase: str = "onenote") -> Step:
    body = {"displayName": _named(name)}
    return Step(phase, "create", "POST", path, body=body, key=_key(name, phase))


def _png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    header = struct.pack(">IIBBBBB", PICTURE_SIDE, PICTURE_SIDE, 8, 2, 0, 0, 0)
    rows = (b"\x00" + b"\x40\x80\xc0" * PICTURE_SIDE) * PICTURE_SIDE
    png = b"\x89PNG\r\n\x1a\n"
    return png + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


ASSETS: Mapping[str, bytes] = {f"{TAG} Gallery picture.png": _png()}
PICTURE_ALT = "A blue square"


def _texts(node: object) -> Iterator[str]:
    if isinstance(node, Mapping):
        for key, one in cast("Mapping[str, object]", node).items():
            if key in ("name", "title") and isinstance(one, str):
                yield _named(one)
            elif key == "text" and isinstance(one, str):
                yield one
            yield from _texts(one)
    elif isinstance(node, list):
        for one in cast("list[object]", node):
            yield from _texts(one)


STRINGS: tuple[str, ...] = (
    *_texts(yaml.safe_load(CORPUS.read_text(encoding="utf-8"))),
    PICTURE_ALT,
)


def _page_html(title: str, page: Spec) -> str:
    paragraphs = "".join(
        f'<p data-id="{one["id"]}">{html.escape(one["text"])}</p>'
        if "id" in one
        else f"<p>{html.escape(one['text'])}</p>"
        for one in page["paragraphs"]
    )
    picture = f'<img src="name:{PICTURE}" alt="{PICTURE_ALT}"/>' if page.get("image") else ""
    return (
        f"<!DOCTYPE html><html><head><title>{html.escape(title)}</title></head>"
        + f"<body>{paragraphs}{picture}</body></html>"
    )


def _multipart(page_html: str) -> bytes:
    form = f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="%s"\r\nContent-Type: %s\r\n\r\n'
    return (
        (form % ("Presentation", "text/html")).encode()
        + f"{page_html}\r\n".encode()
        + (form % (PICTURE, "image/png")).encode()
        + _png()
        + f"\r\n--{BOUNDARY}--\r\n".encode()
    )


def _page(section: str, page: Spec, phase: str) -> Step:
    title = _named(page["title"])
    markup = _page_html(title, page)
    image = bool(page.get("image"))
    return Step(
        phase,
        "create",
        "POST",
        f"{section}/pages",
        body=_multipart(markup) if image else markup.encode(),
        content_type=f"multipart/form-data; boundary={BOUNDARY}" if image else "text/html",
        key=_key(page["title"], phase),
    )


def _section(root: str, parent: str, section: Spec, phase: str) -> list[Step]:
    path = f"{root}/sections/{_ref(section['name'], phase)}"
    return [
        _create(f"{parent}/sections", section["name"], phase),
        _lookup(f"{path}/pages", "id,title", phase),
        *(_page(path, page, phase) for page in section.get("pages", [])),
    ]


def _notebook(root: str, notebook: Spec, phase: str) -> list[Step]:
    path = f"{root}/notebooks/{_ref(notebook['name'], phase)}"
    found = [
        _create(f"{root}/notebooks", notebook["name"], phase),
        _lookup(f"{path}/sections", "id,displayName", phase),
        _lookup(f"{path}/sectionGroups", "id,displayName", phase),
    ]
    for section in notebook.get("sections", []):
        found += _section(root, path, section, phase)
    for group in notebook.get("groups", []):
        group_path = f"{root}/sectionGroups/{_ref(group['name'], phase)}"
        found += [
            _create(f"{path}/sectionGroups", group["name"], phase),
            _lookup(f"{group_path}/sections", "id,displayName", phase),
        ]
        for section in group.get("sections", []):
            found += _section(root, group_path, section, phase)
    return found


def _group(corpus: Spec) -> list[Step]:
    phase, params = "onenote-group", (("$select", "id,displayName"),)
    root = f"/groups/{{{phase}:{TEAM_NAME}}}/onenote"
    found = [
        Step(phase, "lookup", "GET", "/me/joinedTeams", params, lookup="named", learns="team"),
        _lookup(f"{root}/notebooks", "id,displayName", phase),
    ]
    for notebook in corpus["group_notebooks"]:
        found += _notebook(root, notebook, phase)
    return found


def _big(corpus: Spec) -> list[Step]:
    phase, big = "onenote-big", corpus["big_page"]
    notebook = f"/me/onenote/notebooks/{_ref(big['notebook'], phase)}"
    section = f"/me/onenote/sections/{_ref(big['section'], phase)}"
    title = _named(big["title"])
    size = big["size"]
    return [
        _lookup("/me/onenote/notebooks", "id,displayName", phase),
        _lookup(f"{notebook}/sections", "id,displayName", phase),
        _lookup(f"{section}/pages", "id,title", phase),
        Step(
            phase,
            "create",
            "POST",
            f"{section}/pages",
            body=docgen.onenote_html(size, title),
            content_type="text/html",
            key=_key(big["title"], phase),
            generated=("onenote-html", size, title),
        ),
    ]


def steps(ctx: Context, owner: str, phases: set[str]) -> list[Step]:
    if owner != OWNER:
        return []
    corpus = cast("Spec", yaml.safe_load(CORPUS.read_text(encoding="utf-8")))
    found: list[Step] = []
    if "onenote" in phases:
        found += [_lookup("/me/onenote/notebooks", "id,displayName")]
        for notebook in corpus["notebooks"]:
            found += _notebook("/me/onenote", notebook, "onenote")
    if "onenote-group" in phases:
        found += _group(corpus)
    if "onenote-big" in phases:
        found += _big(corpus)
    return found


def team_id(graph: Graph) -> str | None:
    teams = graph.request("GET", "/me/joinedTeams", params={"$select": "id,displayName"})
    for team in teams.json().get("value", []):
        if team.get("displayName") == TEAM_NAME:
            graph.learn("team", str(team["id"]))
            return str(team["id"])
    return None


def _pages(graph: Graph, root: str) -> list[dict[str, str | None]]:
    params = {"$select": "id,title", "$top": "100"}
    answer = graph.request("GET", f"{root}/pages", params=params, ok_statuses=ABSENT)
    found: list[dict[str, str | None]] = []
    while answer.status_code == 200:
        found += answer.json().get("value", [])
        link = answer.json().get("@odata.nextLink")
        if not link:
            break
        answer = graph.request("GET", link)
    return found


def sweep(graph: Graph, owner: str) -> Iterator[tuple[str, str]]:
    if owner != OWNER:
        return
    roots = [ME] + [f"/groups/{team}/onenote" for team in [team_id(graph)] if team]
    for root in roots:
        for page in _pages(graph, root):
            if CASE in (page.get("title") or ""):
                yield "DELETE", f"{root}/pages/{page['id']}"


def cleanup(
    graph: Graph, ctx: Context, owner: str, phases: set[str]
) -> Iterator[tuple[str, str, None]]:
    if owner != OWNER:
        return
    corpus = cast("Spec", yaml.safe_load(CORPUS.read_text(encoding="utf-8")))
    wanted: dict[str, set[str]] = {}
    if "onenote-big" in phases:
        wanted[ME] = {_named(corpus["big_page"]["title"])}
    if "onenote-group" in phases and (team := team_id(graph)):
        pages = {
            _named(page["title"])
            for notebook in corpus["group_notebooks"]
            for section in notebook["sections"]
            for page in section.get("pages", [])
        }
        wanted[f"/groups/{team}/onenote"] = pages
    for root, titles in wanted.items():
        for page in _pages(graph, root):
            if page.get("title") in titles:
                yield "DELETE", f"{root}/pages/{page['id']}", None
