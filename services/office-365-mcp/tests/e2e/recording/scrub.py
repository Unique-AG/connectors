# pyright: reportPrivateUsage=false
"""Turns a recording into the runner's fixture, its bodies and a metadata file (plan v3 R2,
allowlist by construction). A response key that `SCHEMA` does not name is dropped. Free text that
is not seed corpus text becomes `synthetic text NN`. An address that is not a persona becomes
`user-NN@example.test`. An id keeps its length, punctuation and known prefix, and its letters and
digits come from a keyed hash, so a re-record gives the same ids. A binary body must be a file
that the seed generator made."""

import base64
import functools
import hashlib
import hmac
import html
import json
import os
import re
import subprocess
import sys
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from html.parser import HTMLParser
from importlib.metadata import version
from pathlib import Path
from string import ascii_lowercase, ascii_uppercase, digits
from typing import Literal, cast, override
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

import httpx
import yaml

from tests.e2e.recording.families import load
from tests.e2e.recording.guard import GRAPH_HOST, Refused
from tests.e2e.test_scenarios import _DATETIME, Json, day_named
from tests.graph_fixtures import generate

SCRUB_VERSION = "1.0.0"
SEED = Path(__file__).resolve().parents[3] / "scripts" / "dogfood" / "seed"
SYNTHETIC_DOMAIN = "example.test"
RESPONSE_HEADERS = frozenset({"content-type", "location", "retry-after", "preference-applied"})
SDKS = ("msgraph-sdk", "msgraph-core", "microsoft-kiota-http", "httpx", "fastmcp")

LARGE_BODY = 256 * 1024
_NO_TOKENS: frozenset[str] = frozenset()

type Kind = Literal[
    "text", "id", "address", "date", "time", "enum", "number", "url", "path", "object"
]

_CORE_SCHEMA: Mapping[str, Kind] = {
    **dict.fromkeys(
        ("subject", "bodyPreview", "content", "name", "displayName", "summary", "categories")
        + ("searchTerms", "message", "title", "description"),
        "text",
    ),
    **dict.fromkeys(
        ("id", "parentFolderId", "conversationId", "driveId", "hitId", "changeKey", "siteId")
        + ("@odata.etag", "eTag", "cTag", "iCalUId", "seriesMasterId"),
        "id",
    ),
    **dict.fromkeys(("address", "email"), "address"),
    **dict.fromkeys(
        ("receivedDateTime", "sentDateTime", "createdDateTime", "lastModifiedDateTime")
        + ("dateTime",),
        "date",
    ),
    **dict.fromkeys(
        ("importance", "flagStatus", "contentType", "mimeType", "@odata.type", "driveType")
        + ("code", "timeZone", "showAs", "sensitivity"),
        "enum",
    ),
    **dict.fromkeys(
        ("size", "totalItemCount", "unreadItemCount", "childFolderCount", "childCount", "rank")
        + ("total", "isRead", "hasAttachments", "isDraft", "moreResultsAvailable", "isAllDay"),
        "number",
    ),
    **dict.fromkeys(("webLink", "webUrl", "@odata.nextLink"), "url"),
    "path": "path",
    **dict.fromkeys(
        ("value", "from", "sender", "toRecipients", "ccRecipients", "bccRecipients", "replyTo")
        + ("emailAddress", "flag", "body", "file", "folder", "parentReference", "createdBy")
        + ("lastModifiedBy", "user", "resource", "hitsContainers", "hits", "error", "start")
        + ("end", "dueDateTime", "startDateTime", "completedDateTime", "location"),
        "object",
    ),
}
if clash := sorted(k for k, kind in load().schema.items() if _CORE_SCHEMA.get(k, kind) != kind):
    raise ValueError(f"a family changes the Kind of the core SCHEMA keys {clash}")
SCHEMA: Mapping[str, Kind] = {**_CORE_SCHEMA, **cast("Mapping[str, Kind]", load().schema)}
WELL_KNOWN_TEXT = frozenset(
    {"Inbox", "Archive", "Drafts", "Sent Items", "Deleted Items", "Junk Email", "Outbox"}
)

_KEY = b"office-365-mcp recorded cassettes, seed-v1"
_PREFIXES = ("AAMkAG", "AAMk", "AQMk", "AAQk", "b!", "01", 'W/"', "19:")
PREVIEW_CHARACTERS = 255
_TAG_LENGTH = 4
MIN_TAGGED = 12
_ALNUM = frozenset(ascii_lowercase + ascii_uppercase + digits)
_GUID = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}(?:T[\d:.]+(?:Z|[+-]\d{2}:\d{2})?)?")
_ENUM = re.compile(r"[A-Za-z#][A-Za-z0-9 .#()+\-:/_;=]{0,99}")
_TOKEN = re.compile(r"[A-Za-z#$][A-Za-z0-9._#$\-]{0,63}")
_TOKEN_LIST = re.compile(r"[a-z][A-Za-z]*(?:, ?[a-z][A-Za-z]*)+")
_TIME = re.compile(r"\d{2}:\d{2}:\d{2}(?:\.\d+)?")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_ADDRESS = re.compile(r"[^\s@<>()\[\],;:\"']+@[a-z0-9\-]+(?:\.[a-z0-9\-]+)+")
_ADDRESS_IN = re.compile(r"[^\s@<>()\[\],;:\"'=&?/]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
_LONG_ID = re.compile(r"(?=.*\d)[A-Za-z0-9!_\-=+]{20,}")
_ARGUMENT = r"(?:[A-Za-z]+=)?(?:'[^'/]*'|true|false)"
_CALL = re.compile(rf"([A-Za-z_]+)\(({_ARGUMENT}(?:,{_ARGUMENT})*)?\)")
_QUOTED = re.compile(r"'([^'/]*)'")
_URL_IN_TEXT = re.compile(r"https://[^'\s]+")
_API_WORD = re.compile(r"[A-Za-z_$][A-Za-z0-9_.$:]{0,40}|v1\.0|\d{1,4}")
_URL_WORDS = frozenset(
    {"personal", "sites", "teams", "_layouts", "15", "download.aspx", "Documents", "Forms"}
    | {"Shared Documents", "owa", "mail", "Doc.aspx", "WopiFrame.aspx", "AllItems.aspx"}
)
KEPT_HOSTS = frozenset(
    {GRAPH_HOST, "outlook.office365.com", "outlook.office.com", "teams.microsoft.com"}
    | {"contoso.sharepoint.com", "contoso-my.sharepoint.com"}
)
_ID_PARAMETERS = frozenset({"$skiptoken", "$deltatoken", "itemid", "uniqueid"})
_PLAIN_PARAMETERS = frozenset(
    {"$select", "$filter", "$top", "$skip", "$orderby", "$expand", "$count", "$search"}
    | {"$format", "format", "translate", "apiversion", "exvsurl", "viewmodel", "search"}
    | {"startdatetime", "enddatetime", "@microsoft.graph.conflictbehavior"}
)
_PAGE = re.compile(
    r'(<!DOCTYPE html><html><head><title>)(.*?)(</title><meta name="created" content="[^"<>@]*"'
    + r" /></head><body>)(.*)(</body></html>)",
    re.S,
)
_PLACEHOLDER = re.compile(r"synthetic text \d+")
_ADDRESS_KEYS = ("address", "email")
_NAME_KEYS = ("name", "displayName")
_COMMENT = re.compile(r"<!--[^<>@]*?-->", re.S)
_STYLE = re.compile(r"<style[^<>@]*>[^<>@]*</style>", re.S | re.I)
_INLINE = re.compile(r"</?c0>", re.I)
_SAFE_TAG = re.compile(
    r"</?(?:html|head|body|meta|p|b|i|u|ul|ol|li|h[1-6]|br|div|span|strong|em|table|tr|td)"
    + r'(?:\s+(?:http-equiv|content|charset|style|dir|class|type|lang)="[^"<>@]*"'
    + r'|\s+data-id="[A-Za-z][\w\-]{0,30}")*\s*/?>',
    re.I,
)
_ANY_TAG = re.compile(r"<[^>]*>")
_ATTACHMENT = re.compile(rf'<attachment id="({_GUID.pattern})"></attachment>')
_ELLIPSIS = re.compile(r"<ddd/>|…|\.\.\.", re.I)
_EMOJI_JOINERS = frozenset({"\u200d", "\ufe0f"})
MAX_EMOJI_CODE_POINTS = 8
_SYMBOLS = {-1: "~yesterday", 0: "~today", 1: "~tomorrow"}
_SUFFIXES = {"wordprocessingml": ".docx", "spreadsheetml": ".xlsx", "pdf": ".pdf", "text/": ".txt"}


@dataclass(frozen=True, repr=False)
class Hop:
    asked: Json
    url: str
    authorized: bool
    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes

    @override
    def __repr__(self) -> str:
        return f"Hop({self.asked['method']} -> {self.status})"


@dataclass(frozen=True, repr=False)
class Identities:
    values: frozenset[str]
    token: str

    def everything(self) -> frozenset[str]:
        return self.values | {self.token}

    @override
    def __repr__(self) -> str:
        return f"Identities({len(self.values)} values)"


type Target = Literal["stand-in", "graph"]


@dataclass(frozen=True, repr=False)
class Recording:
    scenario: str
    fixture: str
    target: Target
    recorded_at: datetime
    hops: tuple[Hop, ...]
    identities: Identities
    personas: Mapping[str, str]
    literals: frozenset[str]
    tokens: frozenset[str] = frozenset()

    @override
    def __repr__(self) -> str:
        return f"Recording({self.scenario}, {self.target}, {len(self.hops)} hops)"


@dataclass(frozen=True)
class Persona:
    key: str
    index: int
    display_name: str


@dataclass(frozen=True)
class Corpus:
    tag: str
    strings: frozenset[str]
    binaries: frozenset[str]
    personas: tuple[Persona, ...]
    blob: str = field(repr=False)
    generated: Mapping[str, Json] = field(default_factory=dict[str, Json])

    def accepts(self, value: str, extra: str = "") -> bool:
        if _PLACEHOLDER.fullmatch(value) or value in WELL_KNOWN_TEXT:
            return True
        for part in _ELLIPSIS.split(_STYLE.sub(" ", _COMMENT.sub(" ", value))):
            plain = _SAFE_TAG.sub(" ", _INLINE.sub("", part))
            if _ANY_TAG.search(plain):
                return False
            normal = normalized(plain)
            cut = len(value) >= PREVIEW_CHARACTERS
            if normal and not (_within(normal, self.blob, cut) or _within(normal, extra, cut)):
                return False
        return True


def attachment_hash(corpus: Corpus, encoded: str) -> str | None:
    try:
        found = hashlib.sha256(base64.b64decode(encoded, validate=True)).hexdigest()
    except ValueError:
        return None
    return found if found in corpus.binaries else None


def holds_bytes(corpus: Corpus, encoded: str) -> bool:
    return attachment_hash(corpus, encoded) is not None


def stub_of(corpus: Corpus, sha: str) -> bytes:
    made = {k: corpus.generated[sha][k] for k in ("generator", "size", "label")} | {"sha256": sha}
    return (json.dumps(made, indent=2, sort_keys=True) + "\n").encode()


FILLER_STUB = re.compile(r"<generated:filler-text:(\d+):(.+)>")


def filler_stub(corpus: Corpus, raw: str) -> str | None:
    if len(raw) <= LARGE_BODY:
        return None
    for entry in corpus.generated.values():
        label = str(entry["label"])
        if (
            entry["generator"] == "onenote-html"
            and generate("filler-text", len(raw), label) == raw.encode()
        ):
            return f"<generated:filler-text:{len(raw)}:{label}>"
    return None


def _within(normal: str, blob: str, cut: bool) -> bool:
    end = "" if cut else r"(?![\w])"
    return re.search(r"(?<![\w])" + re.escape(normal) + end, blob) is not None


def normalized(text: str) -> str:
    return " ".join(html.unescape(_ANY_TAG.sub(" ", _INLINE.sub("", text))).split()).casefold()


@functools.cache
def load_corpus() -> Corpus:
    command = [sys.executable, str(SEED / "seed.py"), "corpus"]
    environment = {"PATH": os.environ.get("PATH", "")}
    finished = subprocess.run(
        command, capture_output=True, text=True, check=False, env=environment, timeout=120
    )
    if finished.returncode != 0:
        raise Refused(f"seed.py corpus failed: {finished.stderr.strip()[-300:]}")
    manifest = cast("Json", json.loads(finished.stdout))
    loaded = cast("Json", yaml.safe_load((SEED / "corpus" / "personas.yaml").read_text()))
    personas = tuple(
        Persona(key, int(cast("int", one["index"])), str(one["display_name"]))
        for key, one in cast("Mapping[str, Json]", loaded["personas"]).items()
    )
    strings = frozenset(cast("list[str]", manifest["strings"]))
    listed = cast("list[Json]", manifest["binaries"])
    binaries = frozenset(str(one["sha256"]) for one in listed)
    generated = {str(one["sha256"]): one for one in listed if "generator" in one}
    blob = "\x00".join(normalized(one) for one in sorted(strings))
    return Corpus(str(manifest["tag"]), strings, binaries, personas, blob, generated)


_PAGE_CONTENT = re.compile(r"/v1\.0/(?:me|groups/[^/]+)/onenote/pages/[^/]+/content")
_PAGE_IDS = frozenset({"id", "data-id"})
_PAGE_URLS = frozenset({"src", "data-fullres-src", "data", "href"})
PAGE_EMBEDS = frozenset({"src", "data-fullres-src", "data"})
_PAGE_LAYOUT = re.compile(r"[A-Za-z0-9 :;.,%#()\-]*")
_PAGE_LAYOUT_NAMES = frozenset(
    {"style", "class", "lang", "dir", "charset", "type", "width", "height", "name", "content"}
    | {"data-src-type", "data-fullres-src-type", "data-absolute-enabled"}
)
_PAGE_MEDIA = re.compile(r"[a-z]+/[a-z0-9.+\-]+")
_PAGE_NAME = re.compile(r"[a-z][a-z0-9\-]*")
_PAGE_FONT = re.compile(r"(font-family:[A-Za-z ]+)(?=;|$)")
type PageText = Callable[[str], str]
type PageAttribute = Callable[[str, str], str]


def media_type(hop: Hop) -> str:
    return dict((k.lower(), v) for k, v in hop.headers).get("content-type", "").partition(";")[0]


def is_page_content(hop: Hop) -> bool:
    media = dict((k.lower(), v) for k, v in hop.headers).get("content-type", "")
    path = str(hop.asked["path"])
    return (
        hop.asked["method"] == "GET"
        and hop.status == 200
        and media.startswith("text/html")
        and _PAGE_CONTENT.fullmatch(path) is not None
    )


def page_attribute_kind(name: str, value: str) -> Literal["id", "url", "plain", "text"]:
    if name in _PAGE_IDS:
        return "id"
    if name in _PAGE_URLS:
        return "url"
    layout = name in _PAGE_LAYOUT_NAMES and _PAGE_LAYOUT.fullmatch(value) is not None
    media = name.endswith("-type") and _PAGE_MEDIA.fullmatch(value) is not None
    return "plain" if layout or media or _DATE.fullmatch(value) else "text"


def _generic_font(name: str, value: str) -> str:
    return _PAGE_FONT.sub(r"\1,sans-serif", value) if name == "style" else value


class _Page(HTMLParser):
    def __init__(self, text: PageText, attribute: PageAttribute) -> None:
        super().__init__(convert_charrefs=True)
        self.text: PageText = text
        self.attribute: PageAttribute = attribute
        self.out: list[str] = []

    def _value(self, name: str, value: str) -> str:
        return _generic_font(name, self.attribute(name, value))

    def _tag(self, tag: str, attrs: list[tuple[str, str | None]], end: str) -> None:
        safe = _PAGE_NAME.fullmatch(tag) is not None
        shown = "".join(
            f' {name}="{html.escape(self._value(name, value or ""), quote=True)}"'
            for name, value in attrs
            if _PAGE_NAME.fullmatch(name) is not None
        )
        self.out.append(f"<{tag}{shown}{end}>" if safe else "")

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._tag(tag, attrs, "")

    @override
    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._tag(tag, attrs, " /")

    @override
    def handle_endtag(self, tag: str) -> None:
        self.out.append(f"</{tag}>" if _PAGE_NAME.fullmatch(tag) else "")

    @override
    def handle_data(self, data: str) -> None:
        self.out.append(html.escape(data if not data.strip() else self.text(data), quote=False))

    @override
    def handle_decl(self, decl: str) -> None:
        self.out.append("<!DOCTYPE html>" if decl.casefold() == "doctype html" else "")


def rewritten_page(raw: str, text: PageText, attribute: PageAttribute) -> str:
    page = _Page(text, attribute)
    page.feed(raw)
    page.close()
    return "".join(page.out)


def _stream(seed: bytes) -> Iterator[int]:
    counter = 0
    while True:
        yield from hmac.new(_KEY, seed + counter.to_bytes(4, "big"), "sha256").digest()
        counter += 1


def _like(char: str, byte: int) -> str:
    if char in digits:
        return digits[byte % 10]
    return (ascii_uppercase if char in ascii_uppercase else ascii_lowercase)[byte % 26]


def mapped_guid(raw: str) -> str:
    found = hmac.new(_KEY, b"guid:" + raw.casefold().encode(), "sha256").hexdigest()
    made = f"00000000-{found[:4]}-4{found[4:7]}-8{found[7:10]}-{found[10:22]}"
    return made.upper() if raw.isupper() else made


def is_emoji(raw: str) -> bool:
    categories = [unicodedata.category(char) for char in raw if char not in _EMOJI_JOINERS]
    return (
        len(raw) <= MAX_EMOJI_CODE_POINTS
        and "So" in categories
        and all(category in {"So", "Sk"} for category in categories)
    )


def _split(value: str) -> tuple[str, str]:
    prefix = next((p for p in _PREFIXES if value.startswith(p)), "")
    return prefix, value[len(prefix) :]


def _mappable(body: str) -> list[int]:
    inside = {at for found in _GUID.finditer(body) for at in range(*found.span())}
    return [at for at, char in enumerate(body) if char in _ALNUM and at not in inside]


def _tag(body: str, positions: Sequence[int]) -> list[str]:
    kept = "".join(body[at] for at in positions[:-_TAG_LENGTH])
    tag = hmac.new(_KEY, b"tag:" + kept.encode(), "sha256").digest()
    return [_like(body[at], tag[n]) for n, at in enumerate(positions[-_TAG_LENGTH:])]


def _thread_suffix(body: str) -> tuple[str, str]:
    head, at, tail = body.rpartition("@")
    return (
        (head, at + tail) if at and any(p.fullmatch(body) for p in load().thread_id) else (body, "")
    )


def map_id(raw: str) -> str:
    prefix, whole = _split(raw)
    body, suffix = _thread_suffix(whole)
    chars = list(_GUID.sub(lambda found: mapped_guid(found[0]), body))
    positions = _mappable("".join(chars))
    stream = _stream(b"id:" + raw.encode())
    for at in positions:
        chars[at] = _like(chars[at], next(stream))
    if len(positions) >= MIN_TAGGED:
        for at, char in zip(positions[-_TAG_LENGTH:], _tag("".join(chars), positions), strict=True):
            chars[at] = char
    return prefix + "".join(chars) + suffix


def made_by_the_mapper(value: str) -> bool:
    body, _ = _thread_suffix(_split(value)[1])
    positions = _mappable(body)
    if len(positions) < MIN_TAGGED:
        return True
    return [body[at] for at in positions[-_TAG_LENGTH:]] == _tag(body, positions)


def _shared_link(token: str) -> str | None:
    try:
        link = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
    except ValueError:
        return None
    return link if link.startswith("https://") else None


@dataclass
class Mapper:
    corpus: Corpus
    personas: Mapping[str, str]
    ids: frozenset[str]
    extra: str
    texts: dict[str, str] = field(default_factory=dict[str, str])
    addresses: dict[str, str] = field(default_factory=dict[str, str])
    homes: dict[str, str] = field(default_factory=dict[str, str])
    speakers: dict[str, str] = field(default_factory=dict[str, str])
    hosts: dict[str, str] = field(default_factory=dict[str, str])
    counts: Counter[str] = field(default_factory=Counter[str])
    dropped: Counter[str] = field(default_factory=Counter[str])
    stubs: dict[str, bytes] = field(default_factory=dict[str, bytes])
    sizes: list[int] = field(default_factory=list[int])

    def text(self, raw: str, exact: bool = False) -> str:
        kept = raw in self.corpus.strings if exact else self.corpus.accepts(raw, self.extra)
        if kept:
            self.counts["text kept"] += 1
            return raw
        self.counts["text replaced"] += 1
        return self.texts.setdefault(raw, f"synthetic text {len(self.texts) + 1:02d}")

    def voice(self, raw: str) -> str:
        return self.speakers.get(raw.strip().casefold()) or self.text(raw)

    def id(self, raw: str) -> str:
        if not raw:
            return raw
        self.counts["ids mapped"] += 1
        return map_id(raw)

    def address(self, raw: str) -> str:
        lowered = raw.strip().casefold()
        if not _ADDRESS.fullmatch(lowered):
            return self.text(raw)
        if lowered.endswith(f"@{SYNTHETIC_DOMAIN}"):
            return raw
        if lowered in self.personas:
            self.counts["persona addresses"] += 1
            return f"{self.personas[lowered]}@{SYNTHETIC_DOMAIN}"
        self.counts["other addresses replaced"] += 1
        made = f"user-{len(self.addresses) + 1:02d}@{SYNTHETIC_DOMAIN}"
        return self.addresses.setdefault(lowered, made)

    def persona_name(self, found: Json) -> str | None:
        raw = next((found[k] for k in _ADDRESS_KEYS if isinstance(found.get(k), str)), None)
        persona = self.personas.get(str(raw).strip().casefold()) if raw else None
        return next((p.display_name for p in self.corpus.personas if p.key == persona), None)

    def home(self, raw: str) -> str:
        for upn, persona in self.personas.items():
            if raw.casefold() == re.sub(r"[@.]", "_", upn):
                return f"{persona}_example_test"
        self.counts["other addresses replaced"] += 1
        return self.homes.setdefault(raw, f"user_{len(self.homes) + 1:02d}_example_test")

    def host(self, raw: str) -> str:
        lowered = raw.casefold()
        if lowered in KEPT_HOSTS or lowered.endswith(f".{SYNTHETIC_DOMAIN}"):
            return lowered
        if lowered.endswith(".sharepoint.com"):
            mine = lowered.endswith("-my.sharepoint.com")
            return "contoso-my.sharepoint.com" if mine else "contoso.sharepoint.com"
        self.counts["hosts replaced"] += 1
        return self.hosts.setdefault(lowered, f"host-{len(self.hosts) + 1:02d}.{SYNTHETIC_DOMAIN}")

    def plain(self, raw: str) -> str:
        raw = _URL_IN_TEXT.sub(lambda found: self.url(found[0]), raw)
        for known in sorted(self.ids, key=len, reverse=True):
            if known and known in raw:
                raw = raw.replace(known, self.id(known))
        raw = _GUID.sub(lambda found: mapped_guid(found[0]), raw)
        return _ADDRESS_IN.sub(self._address_or_thread, raw)

    def _address_or_thread(self, found: re.Match[str]) -> str:
        mapped = _thread_suffix(found[0])[1] and made_by_the_mapper(found[0])
        return found[0] if mapped else self.address(found[0])

    def query(self, raw: Mapping[str, str]) -> dict[str, str]:
        kept: dict[str, str] = {}
        for key, value in raw.items():
            if key.casefold() in _ID_PARAMETERS:
                kept[key] = "/".join(self.id(part) for part in value.split("/"))
            elif key.casefold() in _PLAIN_PARAMETERS:
                kept[key] = self.plain(value)
            else:
                self.counts["query parameters dropped"] += 1
        return kept

    def segment(self, raw: str, api: bool, previous: str) -> str:
        if not raw:
            return raw
        if api and raw.endswith(":"):
            return self.segment(raw[:-1], api, previous) + ":"
        if previous.casefold() == "personal" and not api:
            return self.home(raw)
        if api and raw.startswith("u!") and (link := _shared_link(raw[2:])) is not None:
            return "u!" + base64.urlsafe_b64encode(self.url(link).encode()).decode().rstrip("=")
        if raw in self.ids or _LONG_ID.fullmatch(raw):
            return self.id(raw)
        if (call := _CALL.fullmatch(raw)) is not None:
            quoted = _QUOTED.sub(lambda one: f"'{self._inner(one[1])}'", call[2] or "")
            return f"{call[1]}({quoted})"
        if "@" in raw:
            return self.address(raw)
        if _GUID.fullmatch(raw):
            return mapped_guid(raw)
        if (api and _API_WORD.fullmatch(raw)) or (not api and raw in _URL_WORDS):
            return raw
        return self.text(raw, exact=not api)

    def _inner(self, raw: str) -> str:
        if _DATE.fullmatch(raw):
            return raw
        if "@" in raw:
            return self.address(raw)
        if _GUID.fullmatch(raw):
            return mapped_guid(raw)
        return raw if raw not in self.ids and _API_WORD.fullmatch(raw) else self.id(raw)

    def path(self, raw: str, api: bool) -> str:
        parts = raw.split("/")
        return "/".join(
            self.segment(one, api, parts[n - 1] if n else "") for n, one in enumerate(parts)
        )

    def url(self, raw: str) -> str:
        parts = urlsplit(raw)
        if not parts.scheme or not parts.hostname:
            return self.text(raw)
        api = parts.hostname.casefold() == GRAPH_HOST
        path = "/".join(
            quote(one, safe="!$'(),:=@*~;")
            for one in self.path(unquote(parts.path), api).split("/")
        )
        query = self.query(dict(parse_qsl(parts.query, keep_blank_values=True)))
        if parts.fragment:
            self.counts["url fragments dropped"] += 1
        encoded = urlencode(query, quote_via=quote, safe="!$'(),:*")
        return urlunsplit((parts.scheme, self.host(parts.hostname), path, encoded, ""))

    def page_attribute(self, name: str, value: str) -> str:
        match page_attribute_kind(name, value):
            case "id":
                return self.plain(value)
            case "url":
                parts = urlsplit(value)
                graph = parts.scheme == "https" and (parts.hostname or "").casefold() == GRAPH_HOST
                return (
                    self.url(value)
                    if graph or (name not in PAGE_EMBEDS and parts.hostname)
                    else self.text(value)
                )
            case "plain":
                return value
            case "text":
                return self.text(value)

    def request_value(self, raw: str) -> str:
        if len(raw) > LARGE_BODY:
            self.sizes.append(len(raw))
            return f"<generated:{len(raw)}>"
        if raw in self.ids:
            return self.id(raw)
        if _GUID.fullmatch(raw):
            return mapped_guid(raw)
        if _DATE.fullmatch(raw) or _TOKEN.fullmatch(raw) or _TOKEN_LIST.fullmatch(raw):
            return raw
        if is_emoji(raw):
            return raw
        if (page := _PAGE.fullmatch(raw)) is not None:
            text = (page[1], self.text(page[2]), page[3], self.text(page[4]), page[5])
            return "".join(text)
        if _ATTACHMENT.search(raw) and self.corpus.accepts(_ATTACHMENT.sub(" ", raw), self.extra):
            return _ATTACHMENT.sub(
                lambda found: f'<attachment id="{mapped_guid(found[1])}"></attachment>', raw
            )
        if _ADDRESS.fullmatch(raw.strip().casefold()):
            return self.address(raw)
        return self.url(raw) if raw.startswith("https://") else self.text(raw)

    def response(self, value: object, kind: Kind = "object") -> object:
        if value is None or isinstance(value, bool | int | float):
            return value
        if isinstance(value, list):
            return [self.response(one, kind) for one in cast("list[object]", value)]
        if isinstance(value, Mapping):
            kept: dict[str, object] = {}
            found = cast("Json", value)
            owner = self.persona_name(found)
            for key, one in sorted(found.items()):
                nested = isinstance(one, Mapping)
                if key == "timeZone" and nested:
                    zone = cast("Json", one).get("name")
                    kept[key] = {"name": self._string(str(zone), "enum")} if zone else {}
                    continue
                if key not in SCHEMA or (nested and SCHEMA[key] != "object" and key != "status"):
                    self.counts["keys dropped"] += 1
                    self.dropped[key] += 1
                    continue
                if owner and key in _NAME_KEYS and isinstance(one, str):
                    self.counts["persona names"] += 1
                    self.speakers[one.strip().casefold()] = owner
                    kept[key] = owner
                    continue
                if key == "contentBytes" and isinstance(one, str):
                    sha = attachment_hash(self.corpus, one)
                    if sha is not None:
                        self.counts["attachments kept by hash"] += 1
                        if len(one) > LARGE_BODY and sha in self.corpus.generated:
                            self.stubs[f"{sha}.gen"] = stub_of(self.corpus, sha)
                            one = f"<generated:{sha}>"
                        kept[key] = one
                        continue
                kept[key] = self.response(one, SCHEMA[key])
            return kept
        return self._string(str(value), kind)

    def _string(self, raw: str, kind: Kind) -> str:
        match kind:
            case "id":
                return self.id(raw)
            case "address":
                return self.address(raw)
            case "url":
                return self.url(raw)
            case "path":
                return self.path(raw, api=True)
            case "date" | "object" if _DATE.fullmatch(raw):
                return raw
            case "time" if _TIME.fullmatch(raw):
                return raw
            case "enum" if _ENUM.fullmatch(raw) and "@" not in raw:
                return raw
            case "number" if _NUMBER.fullmatch(raw):
                return raw
            case _:
                return self.text(raw)

    def request(self, value: object, symbolize: Callable[[str], str]) -> object:
        if isinstance(value, str):
            return symbolize(self.request_value(value))
        if isinstance(value, list):
            return [self.request(one, symbolize) for one in cast("list[object]", value)]
        if isinstance(value, Mapping):
            found = cast("Json", value)
            return {key: self.request(one, symbolize) for key, one in found.items()}
        return value


@dataclass(frozen=True)
class Fixture:
    name: str
    interactions: list[dict[str, object]]
    bodies: dict[str, bytes]
    metadata: dict[str, object]
    counts: dict[str, int]
    dropped: dict[str, int] = field(default_factory=dict[str, int])


def _parsed(hop: Hop) -> object:
    media = dict((k.lower(), v) for k, v in hop.headers).get("content-type", "")
    if not hop.body or "json" not in media:
        return None
    try:
        return cast("object", json.loads(hop.body))
    except ValueError:
        return None


def _raw_ids(value: object, kind: Kind = "object") -> Iterator[str]:
    if isinstance(value, list):
        for one in cast("list[object]", value):
            yield from _raw_ids(one, kind)
    elif isinstance(value, Mapping):
        for key, one in cast("Json", value).items():
            yield from _raw_ids(one, SCHEMA.get(key, "text"))
    elif isinstance(value, str) and kind == "id":
        yield value


def _target(url: str) -> tuple[str, list[tuple[str, str]]]:
    parsed = httpx.URL(url)
    return parsed.path, sorted(parse_qsl(parsed.query.decode(), keep_blank_values=True))


def _unchanged(text: str) -> str:
    return text


def _symbols(day: date, where: str, tokens: frozenset[str] = _NO_TOKENS) -> Callable[[str], str]:
    named = {day_named(word.removeprefix("~"), day): word for word in sorted(tokens)}

    def symbol(found: re.Match[str]) -> str:
        wanted = date.fromisoformat(found[0][:10])
        if wanted in named:
            return named[wanted]
        offset = (wanted - day).days
        if offset not in _SYMBOLS:
            raise Refused(
                f"{where}: a request date is {offset} days from the record day, and the runner "
                + "has a symbol only for -1, 0 and +1 and for the day tokens of the case"
            )
        return _SYMBOLS[offset]

    return lambda text: re.sub(_DATETIME, symbol, text)


def scrub(recording: Recording, corpus: Corpus | None = None) -> Fixture:
    corpus = corpus or load_corpus()
    parsed = [_parsed(hop) for hop in recording.hops]
    extra = "\x00".join(normalized(one) for one in sorted(recording.literals))
    ids = frozenset(raw for body in parsed for raw in _raw_ids(body))
    mapper = Mapper(corpus, recording.personas, ids, extra)
    day = recording.recorded_at.date()
    interactions: list[dict[str, object]] = []
    bodies: dict[str, bytes] = {}
    followed: list[tuple[str, list[tuple[str, str]]]] = []
    request_sizes: dict[int, list[int]] = {}
    for n, (hop, body) in enumerate(zip(recording.hops, parsed, strict=True), 1):
        where = f"{recording.scenario} hop {n}"
        symbolize = (
            _unchanged if _target(hop.url) in followed else _symbols(day, where, recording.tokens)
        )
        asked = hop.asked
        api = asked["host"] == GRAPH_HOST
        interaction: dict[str, object] = {"method": asked["method"]}
        if not api:
            interaction["host"] = mapper.host(str(asked["host"]))
        interaction["path"] = symbolize(mapper.path(str(asked["path"]), api))
        if asked["headers"]:
            interaction["headers"] = dict(cast("Json", asked["headers"]))
        query = mapper.query(cast("Mapping[str, str]", asked["query"]))
        if query:
            interaction["query"] = {key: symbolize(value) for key, value in query.items()}
        if asked["json"] is not None:
            before = len(mapper.sizes)
            interaction["json"] = mapper.request(asked["json"], symbolize)
            if sizes := mapper.sizes[before:]:
                request_sizes[n] = sizes
        interaction["status"] = hop.status
        headers = {k.lower(): v for k, v in hop.headers if k.lower() in RESPONSE_HEADERS}
        mapper.counts["response headers dropped"] += len(hop.headers) - len(headers)
        if "location" in headers:
            headers["location"] = mapper.url(headers["location"])
        if headers:
            interaction["response_headers"] = dict(sorted(headers.items()))
        if body is not None:
            if isinstance(body, Mapping) and "@odata.nextLink" in body:
                followed.append(_target(str(cast("Json", body)["@odata.nextLink"])))
            name = f"{recording.fixture}.{n:02d}.json"
            scrubbed = mapper.response(cast("object", body))
            text = json.dumps(scrubbed, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
            bodies[name] = text.encode()
            interaction["body"] = name
        elif is_page_content(hop):
            name = f"{recording.fixture}.{n:02d}.html"
            page = rewritten_page(
                hop.body.decode(errors="replace"),
                lambda raw: filler_stub(corpus, raw) or mapper.text(raw),
                mapper.page_attribute,
            )
            mapper.counts["page htmls scrubbed"] += 1
            bodies[name] = page.encode()
            interaction["body"] = name
        elif hop.body and (scrubber := load().bodies.get(media_type(hop))) is not None:
            name = f"{recording.fixture}.{n:02d}.{media_type(hop).rpartition('/')[2]}"
            mapper.counts["scrubbed bodies"] += 1
            bodies[name] = scrubber(mapper.voice, hop.body.decode(errors="replace")).encode()
            interaction["body"] = name
        elif hop.body:
            sha = hashlib.sha256(hop.body).hexdigest()
            if sha not in corpus.binaries:
                raise Refused(
                    f"{where}: a binary body of {len(hop.body)} bytes is not a file that the seed "
                    + "generator made (plan v3 R2c); nothing was written"
                )
            mapper.counts["binaries kept by hash"] += 1
            media = headers.get("content-type", "")
            suffix = next((s for k, s in _SUFFIXES.items() if k in media), ".bin")
            name = f"{recording.fixture}.{n:02d}{suffix}"
            if len(hop.body) > LARGE_BODY and sha in corpus.generated:
                name = f"{sha}.gen"
                mapper.stubs[name] = stub_of(corpus, sha)
            else:
                bodies[name] = hop.body
            interaction["body"] = name
        interactions.append(interaction)
    counts = dict(sorted(mapper.counts.items()))
    bodies |= mapper.stubs
    metadata: dict[str, object] = {
        "scenario": recording.scenario,
        "fixture": recording.fixture,
        "source": "recorded",
        "target": recording.target,
        "recorded_at": recording.recorded_at.isoformat(timespec="seconds"),
        "scrub_version": SCRUB_VERSION,
        "replacements": counts,
        "literals": sorted(recording.literals),
        **(
            {"request_size": {str(n): sizes for n, sizes in request_sizes.items()}}
            if request_sizes
            else {}
        ),
        "sdk_versions": {name: version(name) for name in SDKS},
    }
    return Fixture(
        recording.fixture,
        interactions,
        bodies,
        metadata,
        counts,
        dict(sorted(mapper.dropped.items())),
    )


def files_of(fixture: Fixture) -> dict[str, bytes]:
    text = json.dumps(fixture.interactions, indent=2, ensure_ascii=False) + "\n"
    meta = yaml.safe_dump(fixture.metadata, sort_keys=False)
    return {
        f"fixtures/{fixture.name}.json": text.encode(),
        f"fixtures/{fixture.name}.meta.yaml": meta.encode(),
        **{f"bodies/{name}": body for name, body in sorted(fixture.bodies.items())},
    }
