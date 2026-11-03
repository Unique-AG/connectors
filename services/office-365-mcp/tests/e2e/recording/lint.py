"""The scrub lint (plan v3 R3), the second line behind the scrub. It looks for what must never reach
a fixture or a body: plain, URL-, HTML-, JSON- and MIME-encoded, base64 and base32 at every
alignment, gzip, and inside zip members, also nested. A recorded fixture also gets the corpus
check: every kept key is in the projection, every text is corpus text, every address is
synthetic, every id was made by the mapper, every binary is a seed file. A finding in a JSON file
names the path of the leaf and the class of the match. It never prints a value.

A short form of an identity, such as the tenant short name, is not a leak when the match lies
inside text that the seed corpus holds. The text must contain the seed tag and must not run on
into other words. A short form is also no leak inside a key that `SCHEMA` names, such as
`uniqueBody` for the domain `unique.ch`, or inside a `$select` or `$orderby` of such keys. The full
identity always counts.

  python -m tests.e2e.recording.lint [ROOT] [--require-identities]

The identities (tenant id, user ids, UPNs, domains, tenant names) come from
RECORD_LINT_IDENTITIES, comma-separated. With --require-identities the lint fails closed when
that variable is missing, which is what a push to main runs."""

import argparse
import binascii
import contextlib
import gzip
import hashlib
import html
import io
import json
import os
import re
import sys
import unicodedata
import uuid
import zipfile
from base64 import b32decode, b64decode, urlsafe_b64decode
from collections.abc import Collection, Iterator, Mapping
from pathlib import Path
from typing import cast
from urllib.parse import unquote, urlsplit

import yaml

from tests.e2e.recording.families import Scrubber, load
from tests.e2e.recording.guard import GRAPH_HOST
from tests.e2e.recording.scrub import (
    FILLER_STUB,
    KEPT_HOSTS,
    LARGE_BODY,
    PAGE_EMBEDS,
    RESPONSE_HEADERS,
    SCHEMA,
    SYNTHETIC_DOMAIN,
    Corpus,
    holds_bytes,
    load_corpus,
    made_by_the_mapper,
    normalized,
    page_attribute_kind,
    rewritten_page,
)
from tests.e2e.test_scenarios import HERE, Json

IDENTITIES_VARIABLE = "RECORD_LINT_IDENTITIES"
_SHORT_FORM = ", a short form"
REQUEST_HEADERS = frozenset({"prefer", "consistencylevel"})
_RESERVED = r"(?:example\.(?:com|net|org|test)|[a-z0-9\-.]+\.(?:example|test|invalid|localhost))"
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "an address outside the reserved domains",
        re.compile(
            r"(?<![A-Za-z0-9._%+\-])(?!user@odata\.bind(?![\w.\-]))[A-Za-z0-9._%+\-]+@(?!"
            + _RESERVED
            + r"(?![A-Za-z0-9\-])|(?:thread\.(?:v2|skype|tacv2)|(?:[a-z]{2,4}\.){2,3}spaces)"
            + r"(?![\w.\-]))"
            + r"[A-Za-z0-9\-]+\.[A-Za-z]",
            re.I,
        ),
    ),
    ("a tenant domain", re.compile(r"[a-z0-9\-]+\.(?:mail\.)?onmicrosoft\.com", re.I)),
    ("a token-like string", re.compile(r"eyJ[A-Za-z0-9_\-]{8,}")),
    (
        "a credential parameter",
        re.compile(
            r"tempauth|[?&#](?:sig|se|sv|skoid|sktid|access_token|code|x-amz-signature"
            + r"|x-amz-credential)=",
            re.I,
        ),
    ),
    (
        "a SharePoint host",
        re.compile(
            r"(?<![a-z0-9\-.])(?!contoso(?:-my)?\.sharepoint\.)[a-z0-9\-]+\.sharepoint\.[a-z]{2,}",
            re.I,
        ),
    ),
    (
        "a OneDrive path",
        re.compile(
            r"/personal/(?!(?:[a-z]+|user_\d+)_example_test(?![A-Za-z0-9_]))[A-Za-z0-9_\-]+"
        ),
    ),
    (
        "a GUID the mapper did not make",
        re.compile(
            r"(?<![0-9a-fA-F])(?!00000000-)[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}"
        ),
    ),
    ("a GUID without dashes", re.compile(r"(?<![0-9A-Za-z])[0-9a-fA-F]{32}(?![0-9A-Za-z])")),
)
_SCHEMA_KEYS = re.compile(
    r"(?<![a-z0-9])(?:"
    + "|".join(
        re.escape(key) for key in sorted({k.casefold() for k in SCHEMA}, key=len, reverse=True)
    )
    + r")(?![a-z0-9])"
)
_ID_TOKEN = re.compile(
    r"(?:AAMk|AQMk|AAQk)[A-Za-z0-9_\-+=]{12,}|b![A-Za-z0-9_\-]{12,}"
    + r"|(?<![A-Za-z0-9])01[A-Z0-9]{32}(?![A-Za-z0-9])"
)
_BASE64 = re.compile(r"[A-Za-z0-9+/_\-]{12,}={0,2}")
_BASE32 = re.compile(r"[A-Z2-7]{16,}={0,6}")
_ENCODED_WORD = re.compile(r"=\?[^?\s]+\?([bBqQ])\?([^?\s]*)\?=")
_ESCAPE = re.compile(r"\\+u([0-9a-fA-F]{4})")
_FOLD = re.compile(r"\r?\n[ \t]+")
_LEAF = re.compile(r"<generated:([0-9a-f]{64})>")
_ZONE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9 .()+\-:/_]{0,99}")
_STUB_KEYS = frozenset({"generator", "label", "size", "sha256"})


def _mime(found: re.Match[str]) -> str:
    if found[1] in "bB":
        try:
            return b64decode(found[2] + "=" * (-len(found[2]) % 4)).decode("latin-1")
        except binascii.Error, ValueError:
            return found[0]
    quoted = found[2].replace("_", " ")
    return re.sub(r"=([0-9A-Fa-f]{2})", lambda hexed: chr(int(hexed[1], 16)), quoted)


def _views(text: str) -> Iterator[tuple[str, str]]:
    yield "plain", text
    current = text
    for depth in range(1, 5):
        decoded = unquote(current)
        if decoded == current:
            break
        current = decoded
        yield f"URL-decoded x{depth}", current
    yield "HTML-unescaped", html.unescape(current)
    yield "\\u-unescaped", _ESCAPE.sub(lambda found: chr(int(found[1], 16)), current)
    yield "MIME-decoded", _ENCODED_WORD.sub(_mime, _FOLD.sub("", current))
    yield "unfolded", _FOLD.sub("", current)
    yield "NFKC", unicodedata.normalize("NFKC", html.unescape(current))


def _decoded(text: str, depth: int = 0) -> Iterator[bytes]:
    for token in cast("list[str]", _BASE64.findall(text)):
        for start in range(4):
            piece = token[start:]
            padded = piece + "=" * (-len(piece) % 4)
            for decode in (b64decode, urlsafe_b64decode):
                try:
                    raw = decode(padded)
                except binascii.Error, ValueError:
                    continue
                yield raw
                if depth == 0:
                    yield from _decoded(raw.decode("latin-1"), 1)
    for token in cast("list[str]", _BASE32.findall(text)):
        try:
            yield b32decode(token + "=" * (-len(token) % 8))
        except binascii.Error, ValueError:
            continue


def _texts(name: str, body: bytes, depth: int = 0) -> Iterator[tuple[str, str]]:
    if body.startswith(b"\x1f\x8b") and depth < 3:
        try:
            yield from _texts(f"{name}!gunzip", gzip.decompress(body), depth + 1)
            return
        except OSError, EOFError:
            pass
    if body.startswith(b"PK\x03\x04") and depth < 3:
        try:
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                for member in archive.namelist():
                    yield f"{name}!{member}", member
                    yield from _texts(f"{name}!{member}", archive.read(member), depth + 1)
            return
        except zipfile.BadZipFile:
            pass
    yield name, body.decode("latin-1")
    if b"\x00" in body:
        yield f"{name} (UTF-16)", body.decode("utf-16-le", errors="ignore")


def _forms(identity: str) -> Iterator[tuple[str, str]]:
    plain = unicodedata.normalize("NFKC", identity).casefold()
    yield "", plain
    if "@" in plain or "." in plain:
        yield ", underscored", re.sub(r"[^a-z0-9\-]", "_", plain)
    if re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", plain):
        yield ", without dashes", plain.replace("-", "")
    words = re.split(r"[^a-z0-9\-]+", plain.rpartition("@")[2])
    labels = [w for w in words if w not in {"onmicrosoft", "com", "ch", "de", "mail", "net"}]
    for label in {*labels, "".join(labels), *(label.replace("-", "") for label in labels)}:
        if len(label) >= 5 and label != plain:
            yield _SHORT_FORM, label


def _grown(plain: str, start: int, end: int, corpus: Corpus) -> tuple[int, int]:
    while True:
        if start and _in_blob(plain[start - 1 : end], corpus):
            start -= 1
        elif end < len(plain) and _in_blob(plain[start : end + 1], corpus):
            end += 1
        else:
            return start, end


def _in_blob(piece: str, corpus: Corpus) -> bool:
    return "\x00" not in piece and piece in corpus.blob


def _only_corpus_text(folded: str, needle: str, corpus: Corpus) -> bool:
    plain = folded
    while (decoded := unquote(plain)) != plain:
        plain = decoded
    for found in re.finditer(re.escape(needle), plain):
        start, end = _grown(plain, *found.span(), corpus)
        around = plain[max(start - 1, 0) : start] + plain[end : end + 1]
        if corpus.tag.casefold() not in plain[start:end] or any(c.isalnum() for c in around):
            return False
    return True


def _binary_forms(identity: str) -> list[bytes]:
    forms = [identity.casefold().encode(), identity.encode("utf-16-le").lower()]
    if re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", identity):
        forms += [uuid.UUID(identity).bytes, uuid.UUID(identity).bytes_le]
    return forms


def _scan(
    where: str, text: str, identities: Collection[str], strict: bool, corpus: Corpus | None
) -> list[str]:
    rules = _RULES if strict else _RULES[:-2]
    found: list[str] = []
    for view, shown in _views(text):
        found += [f"{where}: {rule} ({view})" for rule, p in rules if p.search(shown)]
        folded = unicodedata.normalize("NFKC", shown).casefold()
        unkeyed = _SCHEMA_KEYS.sub(" ", folded)
        found += [
            f"{where}: identity #{n} ({view}{form})"
            for n, identity in enumerate(sorted(identities), 1)
            for form, needle in _forms(identity)
            if needle in (unkeyed if form == _SHORT_FORM else folded)
            and not (
                form == _SHORT_FORM and _only_corpus_text(folded, needle, corpus or load_corpus())
            )
        ]
        for raw in _decoded(shown):
            lowered = raw.lower()
            decoded = raw.decode("latin-1")
            found += [
                f"{where}: {rule} (base64 in {view})" for rule, p in _RULES[:2] if p.search(decoded)
            ]
            found += [
                f"{where}: identity #{n} (encoded in {view})"
                for n, identity in enumerate(sorted(identities), 1)
                if any(needle in lowered or needle in raw for needle in _binary_forms(identity))
            ]
    return found


def _strings(value: object, key: str = "", path: str = "") -> Iterator[tuple[str, str, str]]:
    if isinstance(value, str):
        yield path, key, value
    elif isinstance(value, list):
        for n, one in enumerate(cast("list[object]", value)):
            yield from _strings(one, key, f"{path}[{n}]")
    elif isinstance(value, Mapping):
        for name, one in cast("Json", value).items():
            yield from _strings(one, name, f"{path}.{name}" if path else name)


def _keys(value: object, path: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(value, list):
        for n, one in enumerate(cast("list[object]", value)):
            yield from _keys(one, f"{path}[{n}]")
    elif isinstance(value, Mapping):
        for name, one in cast("Json", value).items():
            here = f"{path}.{name}" if path else name
            yield here, name
            yield from _keys(one, here)


def _recorded(files: Mapping[str, bytes]) -> dict[str, frozenset[str]]:
    recorded: dict[str, frozenset[str]] = {}
    for name, body in files.items():
        if name.startswith("fixtures/") and name.endswith(".meta.yaml"):
            meta = cast("Json", yaml.safe_load(body))
            if meta.get("source") == "recorded":
                fixture = name.removesuffix(".meta.yaml") + ".json"
                recorded[fixture] = frozenset(cast("list[str]", meta.get("literals", [])))
    return recorded


def _ids(name: str, value: object) -> list[str]:
    found = [
        f"{name} at {path}: an id the mapper did not make"
        for path, key, text in _strings(value)
        if (SCHEMA.get(key) == "id" and not made_by_the_mapper(text))
        or any(
            not made_by_the_mapper(token)
            for token in cast("list[str]", _ID_TOKEN.findall(unquote(text)))
        )
    ]
    return found[:1]


def _filler(corpus: Corpus, value: str) -> bool:
    stub = FILLER_STUB.fullmatch(value)
    return stub is not None and any(
        entry["generator"] == "onenote-html"
        and entry["label"] == stub[2]
        and LARGE_BODY < int(stub[1]) <= cast("int", entry["size"])
        for entry in corpus.generated.values()
    )


def _page(name: str, body: bytes, corpus: Corpus, literals: frozenset[str]) -> list[str]:
    extra = "\x00".join(normalized(one) for one in sorted(literals))
    found: list[str] = []

    def text(value: str) -> str:
        if not corpus.accepts(value, extra) and not _filler(corpus, value):
            found.append(f"{name}: a text node that is not corpus text")
        return value

    def attribute(key: str, value: str) -> str:
        match page_attribute_kind(key, value):
            case "text":
                if not corpus.accepts(value, extra):
                    found.append(f"{name}: an attribute {key} that is not corpus text")
            case "url":
                host = (urlsplit(value).hostname or "").casefold()
                if not host:
                    _ = text(value)
                elif host not in ({GRAPH_HOST} if key in PAGE_EMBEDS else KEPT_HOSTS) and not (
                    host.endswith(f".{SYNTHETIC_DOMAIN}") and key not in PAGE_EMBEDS
                ):
                    found.append(
                        f"{name}: an attribute {key} that is not a Graph or synthetic address"
                    )
            case "id" | "plain":
                pass
        if any(
            not made_by_the_mapper(t) for t in cast("list[str]", _ID_TOKEN.findall(unquote(value)))
        ):
            found.append(f"{name}: an attribute {key} holds an id the mapper did not make")
        return value

    _ = rewritten_page(body.decode(errors="replace"), text, attribute)
    return list(dict.fromkeys(found))


def _scrubbed(
    name: str, body: bytes, corpus: Corpus, literals: frozenset[str], scrubber: Scrubber
) -> list[str]:
    extra = "\x00".join(normalized(one) for one in sorted(literals))
    personas = {one.display_name for one in corpus.personas}
    found: list[str] = []

    def text(value: str) -> str:
        if value not in personas and not corpus.accepts(value, extra):
            found.append(f"{name}: a spoken line or a speaker that is not corpus text")
        return value

    raw = body.decode(errors="replace")
    if scrubber(text, raw) != raw:
        found.append(f"{name}: a line that is not a cue identifier, a timing or a voice line")
    return list(dict.fromkeys(found))


def _stub(name: str, body: bytes, corpus: Corpus) -> list[str]:
    sha = name.rpartition("/")[2].removesuffix(".gen")
    stub: Json = {}
    with contextlib.suppress(ValueError):
        stub = cast("Json", json.loads(body))
    entry: Json = corpus.generated.get(sha) or {}
    held = bool(entry) and stub.keys() == _STUB_KEYS and stub["sha256"] == sha
    if not held or any(stub[key] != entry[key] for key in ("generator", "label", "size")):
        return [f"{name}: a stub whose generator, label, size or hash the corpus manifest lacks"]
    return []


def _corpus(name: str, body: bytes, corpus: Corpus, literals: frozenset[str]) -> list[str]:
    if name.endswith(".html"):
        return _page(name, body, corpus, literals)
    if name.endswith(".gen"):
        return _stub(name, body, corpus)
    for media, scrubber in load().bodies.items():
        if name.endswith(f".{media.rpartition('/')[2]}"):
            return _scrubbed(name, body, corpus, literals, scrubber)
    if not name.endswith(".json"):
        if hashlib.sha256(body).hexdigest() in corpus.binaries:
            return []
        return [f"{name}: a binary that the seed generator did not make"]
    parsed = cast("object", json.loads(body))
    extra = "\x00".join(normalized(one) for one in sorted(literals))
    found = [
        f"{name} at {path}: a key that is not in the projection"
        for path, key in _keys(parsed)
        if key not in SCHEMA
    ]
    for path, key, text in _strings(parsed):
        kind = SCHEMA.get(key)
        zone = path.endswith("timeZone.name") and _ZONE_NAME.fullmatch(text) is not None
        leaf = _LEAF.fullmatch(text)
        if (
            kind == "text"
            and not zone
            and not corpus.accepts(text, extra)
            and not (key == "contentBytes" and holds_bytes(corpus, text))
            and not (key == "contentBytes" and leaf is not None and leaf[1] in corpus.generated)
        ):
            found.append(f"{name} at {path}: a {key} that is not corpus text")
        if kind == "address" and not text.casefold().endswith(f"@{SYNTHETIC_DOMAIN}"):
            found.append(f"{name} at {path}: an {key} that is not synthetic")
    return found + _ids(name, parsed)


def _headers(name: str, interactions: list[Json]) -> list[str]:
    found: list[str] = []
    for n, interaction in enumerate(interactions, 1):
        answered = set(cast("Json", interaction.get("response_headers", {})))
        asked = set(cast("Json", interaction.get("headers", {})))
        found += [
            f"{name}: interaction {n} keeps the response header {h}"
            for h in sorted(answered - RESPONSE_HEADERS)
        ]
        found += [
            f"{name}: interaction {n} keeps the request header {h}"
            for h in sorted(asked - REQUEST_HEADERS)
        ]
    return found


def _rule(finding: str) -> str:
    return re.sub(r" \([^()]*\)$", "", finding).rpartition(": ")[2]


def _located(
    name: str, body: bytes, identities: Collection[str], strict: bool, corpus: Corpus | None
) -> list[str]:
    try:
        parsed = cast("object", json.loads(body))
    except ValueError:
        return []
    keys = ((f"{path.removesuffix(key)}(a key)", key) for path, key in _keys(parsed))
    return [
        found
        for path, text in (*((path, text) for path, _, text in _strings(parsed)), *keys)
        for found in _scan(f"{name} at {path}", text, identities, strict, corpus)
    ]


def lint_files(
    files: Mapping[str, bytes], identities: Collection[str] = (), corpus: Corpus | None = None
) -> list[str]:
    findings: list[str] = []
    recorded = _recorded(files)
    strict = set(recorded) | {
        f"bodies/{interaction['body']}"
        for name in recorded
        if name in files
        for interaction in cast("list[Json]", json.loads(files[name]))
        if "body" in interaction
    }
    for name, body in files.items():
        whole = [
            found
            for where, text in _texts(name, body)
            for found in _scan(where, text, identities, name in strict, corpus)
        ]
        if whole and name.endswith(".json"):
            located = _located(name, body, identities, name in strict, corpus)
            seen = {_rule(found) for found in located}
            findings += located
            whole = [found for found in whole if _rule(found) not in seen]
        findings += whole
        if not (name.startswith("fixtures/") and name.endswith(".json")):
            continue
        interactions = cast("list[Json]", json.loads(body))
        findings += _headers(name, interactions)
        if name in recorded:
            findings += _ids(name, interactions)
            for body_name in (str(i["body"]) for i in interactions if "body" in i):
                key = f"bodies/{body_name}"
                if key not in files:
                    findings.append(f"{name}: the body {body_name} is missing")
                    continue
                findings += _corpus(key, files[key], corpus or load_corpus(), recorded[name])
                findings += [
                    f"{name}: the stub bodies/{leaf[1]}.gen of {body_name} is missing"
                    for leaf in _LEAF.finditer(files[key].decode(errors="replace"))
                    if f"bodies/{leaf[1]}.gen" not in files
                ]
    first: dict[str, str] = {}
    for finding in findings:
        first.setdefault(re.sub(r" \([^()]*\)$", "", finding), finding)
    return list(first.values())


def lint_dir(
    root: Path, identities: Collection[str] = (), corpus: Corpus | None = None
) -> list[str]:
    paths = sorted(p for folder in ("fixtures", "bodies") for p in (root / folder).iterdir())
    return lint_files({str(p.relative_to(root)): p.read_bytes() for p in paths}, identities, corpus)


def identities_from_environment() -> list[str]:
    return [
        one.strip() for one in os.environ.get(IDENTITIES_VARIABLE, "").split(",") if one.strip()
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("root", nargs="?", type=Path, default=HERE)
    parser.add_argument("--require-identities", action="store_true")
    arguments = parser.parse_args(argv)
    identities = identities_from_environment()
    if cast("bool", arguments.require_identities) and not identities:
        print(f"refused: {IDENTITIES_VARIABLE} is not set; the lint fails closed", file=sys.stderr)
        return 2
    problems = lint_dir(cast("Path", arguments.root), identities)
    print("\n".join(problems) or f"scrub lint: clean ({len(identities)} identities)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
