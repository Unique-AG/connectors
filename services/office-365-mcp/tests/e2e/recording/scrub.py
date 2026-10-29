# pyright: reportPrivateUsage=false
"""Turns a recording into the runner's fixture, its bodies and a metadata file (plan v3 R2,
allowlist by construction). A response key that `SCHEMA` does not name is dropped. Free text that
is not seed corpus text becomes `synthetic text NN`. An address that is not a persona becomes
`user-NN@example.test`. An id keeps its length, punctuation and known prefix, and its letters and
digits come from a keyed hash, so a re-record gives the same ids. A binary body must be a file
that the seed generator made."""

import functools
import hashlib
import hmac
import html
import json
import os
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from importlib.metadata import version
from pathlib import Path
from string import ascii_lowercase, ascii_uppercase, digits
from typing import Literal, cast, override
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

import httpx
import yaml

from tests.e2e.recording.guard import GRAPH_HOST, Refused
from tests.e2e.test_scenarios import _DATETIME, Json

SCRUB_VERSION = "1.0.0"
SEED = Path(__file__).resolve().parents[3] / "scripts" / "dogfood" / "seed"
SYNTHETIC_DOMAIN = "example.test"
RESPONSE_HEADERS = frozenset({"content-type", "location", "retry-after", "preference-applied"})
SDKS = ("msgraph-sdk", "msgraph-core", "microsoft-kiota-http", "httpx", "fastmcp")

type Kind = Literal["text", "id", "address", "date", "enum", "number", "url", "path", "object"]

SCHEMA: Mapping[str, Kind] = {
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
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_ADDRESS = re.compile(r"[^\s@<>()\[\],;:\"']+@[a-z0-9\-]+(?:\.[a-z0-9\-]+)+")
_ADDRESS_IN = re.compile(r"[^\s@<>()\[\],;:\"'=&?/]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
_LONG_ID = re.compile(r"(?=.*\d)[A-Za-z0-9!_\-=+]{20,}")
_CALL = re.compile(r"([A-Za-z_]+)\('([^'/]*)'\)")
_API_WORD = re.compile(r"[A-Za-z_$][A-Za-z0-9_.$:]{0,40}|v1\.0|\d{1,4}")
_URL_WORDS = frozenset(
    {"personal", "sites", "teams", "_layouts", "15", "download.aspx", "Documents", "Forms"}
    | {"Shared Documents", "owa", "mail", "Doc.aspx", "WopiFrame.aspx", "AllItems.aspx"}
)
_KEPT_HOSTS = frozenset(
    {GRAPH_HOST, "outlook.office365.com", "outlook.office.com", "teams.microsoft.com"}
    | {"contoso.sharepoint.com", "contoso-my.sharepoint.com"}
)
_ID_PARAMETERS = frozenset({"$skiptoken", "$deltatoken", "itemid", "uniqueid"})
_PLAIN_PARAMETERS = frozenset(
    {"$select", "$filter", "$top", "$skip", "$orderby", "$expand", "$count", "$search"}
    | {"$format", "format", "translate", "apiversion", "exvsurl", "viewmodel"}
)
_PLACEHOLDER = re.compile(r"synthetic text \d+")
_ADDRESS_KEYS = ("address", "email")
_NAME_KEYS = ("name", "displayName")
_COMMENT = re.compile(r"<!--[^<>@]*?-->", re.S)
_STYLE = re.compile(r"<style[^<>@]*>[^<>@]*</style>", re.S | re.I)
_INLINE = re.compile(r"</?c0>", re.I)
_SAFE_TAG = re.compile(
    r"</?(?:html|head|body|meta|p|b|i|u|ul|ol|li|h[1-6]|br|div|span|strong|em|table|tr|td)"
    + r'(?:\s+(?:http-equiv|content|charset|style|dir|class|type|lang)="[^"<>@]*")*\s*/?>',
    re.I,
)
_ANY_TAG = re.compile(r"<[^>]*>")
_ELLIPSIS = re.compile(r"<ddd/>|…|\.\.\.", re.I)
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
    binaries = frozenset(str(one["sha256"]) for one in cast("list[Json]", manifest["binaries"]))
    blob = "\x00".join(normalized(one) for one in sorted(strings))
    return Corpus(str(manifest["tag"]), strings, binaries, personas, blob)


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


def map_id(raw: str) -> str:
    prefix, body = _split(raw)
    chars = list(_GUID.sub(lambda found: mapped_guid(found[0]), body))
    positions = _mappable("".join(chars))
    stream = _stream(b"id:" + raw.encode())
    for at in positions:
        chars[at] = _like(chars[at], next(stream))
    if len(positions) >= MIN_TAGGED:
        for at, char in zip(positions[-_TAG_LENGTH:], _tag("".join(chars), positions), strict=True):
            chars[at] = char
    return prefix + "".join(chars)


def made_by_the_mapper(value: str) -> bool:
    _, body = _split(value)
    positions = _mappable(body)
    if len(positions) < MIN_TAGGED:
        return True
    return [body[at] for at in positions[-_TAG_LENGTH:]] == _tag(body, positions)


@dataclass
class Mapper:
    corpus: Corpus
    personas: Mapping[str, str]
    ids: frozenset[str]
    extra: str
    texts: dict[str, str] = field(default_factory=dict[str, str])
    addresses: dict[str, str] = field(default_factory=dict[str, str])
    homes: dict[str, str] = field(default_factory=dict[str, str])
    hosts: dict[str, str] = field(default_factory=dict[str, str])
    counts: Counter[str] = field(default_factory=Counter[str])

    def text(self, raw: str, exact: bool = False) -> str:
        kept = raw in self.corpus.strings if exact else self.corpus.accepts(raw, self.extra)
        if kept:
            self.counts["text kept"] += 1
            return raw
        self.counts["text replaced"] += 1
        return self.texts.setdefault(raw, f"synthetic text {len(self.texts) + 1:02d}")

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
        if lowered in _KEPT_HOSTS or lowered.endswith(f".{SYNTHETIC_DOMAIN}"):
            return lowered
        if lowered.endswith(".sharepoint.com"):
            mine = lowered.endswith("-my.sharepoint.com")
            return "contoso-my.sharepoint.com" if mine else "contoso.sharepoint.com"
        self.counts["hosts replaced"] += 1
        return self.hosts.setdefault(lowered, f"host-{len(self.hosts) + 1:02d}.{SYNTHETIC_DOMAIN}")

    def plain(self, raw: str) -> str:
        for known in sorted(self.ids, key=len, reverse=True):
            if known and known in raw:
                raw = raw.replace(known, self.id(known))
        raw = _GUID.sub(lambda found: mapped_guid(found[0]), raw)
        return _ADDRESS_IN.sub(lambda found: self.address(found[0]), raw)

    def query(self, raw: Mapping[str, str]) -> dict[str, str]:
        kept: dict[str, str] = {}
        for key, value in raw.items():
            if key.casefold() in _ID_PARAMETERS:
                kept[key] = self.id(value)
            elif key.casefold() in _PLAIN_PARAMETERS:
                kept[key] = self.plain(value)
            else:
                self.counts["query parameters dropped"] += 1
        return kept

    def segment(self, raw: str, api: bool, previous: str) -> str:
        if not raw:
            return raw
        if previous.casefold() == "personal" and not api:
            return self.home(raw)
        if raw in self.ids or _LONG_ID.fullmatch(raw):
            return self.id(raw)
        if (call := _CALL.fullmatch(raw)) is not None:
            return f"{call[1]}('{self._inner(call[2])}')"
        if "@" in raw:
            return self.address(raw)
        if _GUID.fullmatch(raw):
            return mapped_guid(raw)
        if (api and _API_WORD.fullmatch(raw)) or (not api and raw in _URL_WORDS):
            return raw
        return self.text(raw, exact=not api)

    def _inner(self, raw: str) -> str:
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

    def request_value(self, raw: str) -> str:
        if raw in self.ids:
            return self.id(raw)
        if _GUID.fullmatch(raw):
            return mapped_guid(raw)
        if _DATE.fullmatch(raw) or _TOKEN.fullmatch(raw):
            return raw
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
                if key not in SCHEMA or (nested and SCHEMA[key] != "object"):
                    self.counts["keys dropped"] += 1
                    continue
                if owner and key in _NAME_KEYS and isinstance(one, str):
                    self.counts["persona names"] += 1
                    kept[key] = owner
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
            case "date" if _DATE.fullmatch(raw):
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


def _symbols(day: date, where: str) -> Callable[[str], str]:
    def symbol(found: re.Match[str]) -> str:
        offset = (date.fromisoformat(found[0][:10]) - day).days
        if offset not in _SYMBOLS:
            raise Refused(
                f"{where}: a request date is {offset} days from the record day, and the runner "
                + "has a symbol only for -1, 0 and +1"
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
    for n, (hop, body) in enumerate(zip(recording.hops, parsed, strict=True), 1):
        where = f"{recording.scenario} hop {n}"
        symbolize = _unchanged if _target(hop.url) in followed else _symbols(day, where)
        asked = hop.asked
        api = asked["host"] == GRAPH_HOST
        interaction: dict[str, object] = {"method": asked["method"]}
        if not api:
            interaction["host"] = mapper.host(str(asked["host"]))
        interaction["path"] = mapper.path(str(asked["path"]), api)
        if asked["headers"]:
            interaction["headers"] = dict(cast("Json", asked["headers"]))
        query = mapper.query(cast("Mapping[str, str]", asked["query"]))
        if query:
            interaction["query"] = {key: symbolize(value) for key, value in query.items()}
        if asked["json"] is not None:
            interaction["json"] = mapper.request(asked["json"], symbolize)
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
        elif hop.body:
            if hashlib.sha256(hop.body).hexdigest() not in corpus.binaries:
                raise Refused(
                    f"{where}: a binary body of {len(hop.body)} bytes is not a file that the seed "
                    + "generator made (plan v3 R2c); nothing was written"
                )
            mapper.counts["binaries kept by hash"] += 1
            media = headers.get("content-type", "")
            suffix = next((s for k, s in _SUFFIXES.items() if k in media), ".bin")
            name = f"{recording.fixture}.{n:02d}{suffix}"
            bodies[name] = hop.body
            interaction["body"] = name
        interactions.append(interaction)
    counts = dict(sorted(mapper.counts.items()))
    metadata: dict[str, object] = {
        "scenario": recording.scenario,
        "fixture": recording.fixture,
        "source": "recorded",
        "target": recording.target,
        "recorded_at": recording.recorded_at.isoformat(timespec="seconds"),
        "scrub_version": SCRUB_VERSION,
        "replacements": counts,
        "literals": sorted(recording.literals),
        "sdk_versions": {name: version(name) for name in SDKS},
    }
    return Fixture(recording.fixture, interactions, bodies, metadata, counts)


def files_of(fixture: Fixture) -> dict[str, bytes]:
    text = json.dumps(fixture.interactions, indent=2, ensure_ascii=False) + "\n"
    meta = yaml.safe_dump(fixture.metadata, sort_keys=False)
    return {
        f"fixtures/{fixture.name}.json": text.encode(),
        f"fixtures/{fixture.name}.meta.yaml": meta.encode(),
        **{f"bodies/{name}": body for name, body in sorted(fixture.bodies.items())},
    }
