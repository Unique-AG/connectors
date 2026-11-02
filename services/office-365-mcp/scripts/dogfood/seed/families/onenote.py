import html
import struct
import zlib
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import yaml
from model import Context, Step

if TYPE_CHECKING:
    from seed import Graph

TAG = "seed-v1"
CASE = f"{TAG} case-"
OWNER = "mia"
PHASES: tuple[str, ...] = ("onenote",)
CORPUS = Path(__file__).resolve().parents[1] / "corpus" / "onenote.yaml"
BOUNDARY = "seed-v1-onenote"
PICTURE = "imageBlock1"
PICTURE_SIDE = 64

type Spec = Mapping[str, Any]


def _named(name: str) -> str:
    return f"{TAG} {name}"


def _key(name: str) -> str:
    return f"onenote:{_named(name)}"


def _ref(name: str) -> str:
    return "{" + _key(name) + "}"


def _lookup(path: str, fields: str) -> Step:
    params = (("$select", fields), ("$top", "100"))
    return Step("onenote", "lookup", "GET", path, params, lookup="named")


def _create(path: str, name: str, field: str = "displayName") -> Step:
    return Step("onenote", "create", "POST", path, body={field: _named(name)}, key=_key(name))


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


def _page(section: str, page: Spec) -> Step:
    title = _named(page["title"])
    markup = _page_html(title, page)
    image = bool(page.get("image"))
    return Step(
        "onenote",
        "create",
        "POST",
        f"{section}/pages",
        body=_multipart(markup) if image else markup.encode(),
        content_type=f"multipart/form-data; boundary={BOUNDARY}" if image else "text/html",
        key=_key(page["title"]),
    )


def _section(parent: str, section: Spec) -> list[Step]:
    path = f"/me/onenote/sections/{_ref(section['name'])}"
    return [
        _create(f"{parent}/sections", section["name"]),
        _lookup(f"{path}/pages", "id,title"),
        *(_page(path, page) for page in section.get("pages", [])),
    ]


def _notebook(notebook: Spec) -> list[Step]:
    path = f"/me/onenote/notebooks/{_ref(notebook['name'])}"
    found = [
        _create("/me/onenote/notebooks", notebook["name"]),
        _lookup(f"{path}/sections", "id,displayName"),
        _lookup(f"{path}/sectionGroups", "id,displayName"),
    ]
    for section in notebook.get("sections", []):
        found += _section(path, section)
    for group in notebook.get("groups", []):
        group_path = f"/me/onenote/sectionGroups/{_ref(group['name'])}"
        found += [
            _create(f"{path}/sectionGroups", group["name"]),
            _lookup(f"{group_path}/sections", "id,displayName"),
        ]
        for section in group.get("sections", []):
            found += _section(group_path, section)
    return found


def steps(ctx: Context, owner: str, phases: set[str]) -> list[Step]:
    if "onenote" not in phases or owner != OWNER:
        return []
    corpus = cast("Spec", yaml.safe_load(CORPUS.read_text(encoding="utf-8")))
    found = [_lookup("/me/onenote/notebooks", "id,displayName")]
    for notebook in corpus["notebooks"]:
        found += _notebook(notebook)
    return found


def sweep(graph: Graph, owner: str) -> Iterator[tuple[str, str]]:
    if owner != OWNER:
        return
    pages = list(graph.get_all("/me/onenote/pages", {"$select": "id,title", "$top": "100"}))
    for page in pages:
        if CASE in (page.get("title") or ""):
            yield "DELETE", f"/me/onenote/pages/{page['id']}"
