"""Seed the three dogfood test mailboxes and OneDrives from the corpus, idempotently.

  seed.py plan     [--as N] [--phases P,Q]    print every Graph call; makes no call (default)
  seed.py apply    --as N   [--phases P,Q]    create what is missing
  seed.py cleanup  --as N   [--phases P,Q] [--dry-run]   delete only what the seed can prove it created
  seed.py cleanup  --as N   --cases           delete the items that hold "seed-v1 case-" in their name
  seed.py corpus   [--out FILE]               write every string and binary hash the seed creates

Environment: SEED_UPNS (Mia, Anna, Tom, comma-separated) and, for apply and cleanup, GRAPH_TOKEN.
Optional: SEED_DIRECTORY_UPN, SEED_GUEST_UPN, SEED_ROOM_UPN and SEED_SHARED_UPN name the one
address of each kind that a family may use (`env:<NAME>` in the corpus). The cap of requests is
for each phase (--phase-cap).
"""

import argparse
import base64
import datetime as dt
import hashlib
import json
import logging
import os
import re
import sys
import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urlsplit

import docgen
import families
import httpx
import yaml
from model import ConfigError, Context, SeedError, Step

TAG = "seed-v1"
BASE = "https://graph.microsoft.com/v1.0"
MAX_REQUESTS = 600
INLINE_MAX = 3 * 1024 * 1024
CHUNK = 12 * 320 * 1024
SEND_PHASE = "mail-people"
MAX_SENDS = 12
EXTRA_ENV = ("SEED_DIRECTORY_UPN", "SEED_GUEST_UPN", "SEED_ROOM_UPN", "SEED_SHARED_UPN")
SHARED_ENV = "SEED_SHARED_UPN"
MEMBER_PATHS = (
    ("team", re.compile(r"/v1\.0/teams/([^/]+)/channels(?:/.*)?")),
    (
        "team",
        re.compile(r"/v1\.0/groups/([^/]+)/(?:events|calendar\w*|drive|onenote|members)(?:/.*)?"),
    ),
    ("drive", re.compile(r"/v1\.0/drives/([^/]+)(?:/.*)?")),
    ("chat", re.compile(r"/v1\.0/chats/([^/]+)/messages")),
)
MAX_RETRY_WAIT = 120.0
OPERATION_POLLS = 24
OPERATION_WAIT = 5.0
TEAMS_PATH = "/v1.0/teams"
CHATS_PATH = "/v1.0/chats"
SENDING = re.compile(
    r"/v1\.0/me/(?:mailfolders/[^/]+/)?(?:messages|events)/[^/]+/(?:send|forward|reply|replyall)"
)
TEAM_OPERATION = re.compile(r"/v1\.0/teams\('[0-9a-f\-]{36}'\)/operations\('[0-9a-f\-]{36}'\)")
TEAM_LOCATION = re.compile(r"teams\('([0-9a-f\-]{36})'\)")
SEED_GUID = "8c0e3b2a-6f1d-4d6e-9a57-2f3c5b7e9d10"
KEY_PROP = f"String {{{SEED_GUID}}} Name SeedKey"
FLAGS_PROP = "Integer 0x0E07"
DELIVERY_PROP = "SystemTime 0x0E06"
SUBMIT_PROP = "SystemTime 0x0039"
CONV_INDEX_PROP = "Binary 0x0071"
CONV_TOPIC_PROP = "String 0x0070"
MSGFLAG_READ = 0x1
TAG_FILTER = f"categories/any(c:c eq '{TAG}')"
KEY_EXPAND = f"singleValueExtendedProperties($filter=id eq '{KEY_PROP}')"
WELL_KNOWN_FOLDERS = {"inbox", "sentitems", "drafts", "junkemail", "deleteditems"}
FAMILIES = families.load()
PHASES = ("folders", "mail", "events", "files", *(p for family in FAMILIES for p in family.PHASES))
OPT_IN = frozenset(p for family in FAMILIES for p in getattr(family, "OPT_IN", ()))
MAIL_MODES = ("extprops", "draft")
ADDRESS_TOKEN = re.compile(r"[^\s<>\"',;()\[\]]*(?:@|＠|%40)[^\s<>\"',;()\[\]]*", re.IGNORECASE)
UPLOAD_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
    "txt": "text/plain",
    "filler": "application/octet-stream",
    "filler-text": "text/plain",
}
CORPUS_DIR = Path(__file__).resolve().parent / "corpus"

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class Refused(SeedError):
    code = 3


class GraphError(SeedError):
    code = 4


class CapReached(SeedError):
    code = 5


# ---------------------------------------------------------------- corpus


def load_corpus(directory: Path) -> dict[str, Any]:
    corpus = {}
    for name in ("personas", "folders", "mail", "events", "files"):
        path = directory / f"{name}.yaml"
        if not path.is_file():
            raise ConfigError(f"corpus file missing: {path}")
        corpus[name] = yaml.safe_load(path.read_text(encoding="utf-8"))
    validate_corpus(corpus)
    return corpus


def _owner(item: Mapping[str, Any]) -> str:
    return item.get("owner", "mia")


def validate_corpus(corpus: dict[str, Any]) -> None:
    personas = corpus["personas"]["personas"]
    if sorted(p["index"] for p in personas.values()) != [1, 2, 3]:
        raise ConfigError("personas.yaml needs exactly the indexes 1, 2 and 3")
    folder_keys = {f["key"] for f in corpus["folders"]["folders"]}
    attachment_ids = {a["id"] for a in corpus["files"]["attachments"]}
    threads = corpus["mail"]["threads"]
    items = (
        corpus["mail"]["messages"]
        + corpus["events"]["events"]
        + corpus["files"]["files"]
        + corpus["folders"]["folders"]
    )
    ids = [item.get("id", item.get("key")) for item in items]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ConfigError(f"duplicate corpus ids: {sorted(duplicates)}")
    for item in items:
        if _owner(item) not in personas:
            raise ConfigError(f"{item.get('id', item.get('key'))}: unknown owner {_owner(item)}")
    for folder in corpus["folders"]["folders"]:
        if folder.get("parent") and folder["parent"] not in folder_keys:
            raise ConfigError(f"folder {folder['key']}: unknown parent {folder['parent']}")
    for message in corpus["mail"]["messages"]:
        mid = message["id"]
        if message["folder"] not in WELL_KNOWN_FOLDERS | folder_keys:
            raise ConfigError(f"{mid}: unknown folder {message['folder']}")
        if message.get("thread") and message["thread"] not in threads:
            raise ConfigError(f"{mid}: unknown thread {message['thread']}")
        for ref in message.get("attachments", []):
            if ref not in attachment_ids:
                raise ConfigError(f"{mid}: unknown attachment {ref}")
        if not message.get("draft") and "received" not in message:
            raise ConfigError(f"{mid}: a non-draft message needs `received`")
        if message.get("body", {}).get("type") not in ("text", "html"):
            raise ConfigError(f"{mid}: body.type must be text or html")


# ---------------------------------------------------------------- time and ids


def received_at(spec: str, anchor: dt.date) -> dt.datetime:
    match = re.fullmatch(r"-(\d+)d (\d{2}):(\d{2})", spec)
    if not match:
        raise ConfigError(f"bad received value {spec!r}, expected '-<days>d HH:MM'")
    days, hour, minute = (int(g) for g in match.groups())
    day = anchor - dt.timedelta(days=days)
    return dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=dt.UTC)


def iso_z(moment: dt.datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _filetime(moment: dt.datetime) -> int:
    return int((moment - dt.datetime(1601, 1, 1, tzinfo=dt.UTC)).total_seconds() * 10_000_000)


def conversation_index(thread: str, root: dt.datetime, replies: list[dt.datetime]) -> str:
    """PidTagConversationIndex: a 22-byte header (thread time and GUID) plus 5 bytes per reply."""
    root_ft = _filetime(root)
    index = (
        b"\x01"
        + (root_ft >> 24).to_bytes(5, "big")
        + uuid.uuid5(uuid.UUID(SEED_GUID), thread).bytes
    )
    for sequence, reply in enumerate(replies):
        delta = ((_filetime(reply) - root_ft) >> 18) & 0x7FFFFFFF
        index += ((delta << 8) | (sequence & 0xF)).to_bytes(5, "big")
    return base64.b64encode(index).decode("ascii")


def key_prop(key: str) -> dict[str, str]:
    return {"id": KEY_PROP, "value": f"{TAG}:{key}"}


# ---------------------------------------------------------------- generated files


def file_bytes(spec: Mapping[str, Any], ctx: Context) -> bytes:
    props = {
        name: ctx.display_name(value) if name in ("creator", "last_modified_by") else value
        for name, value in spec.get("properties", {}).items()
    }
    kind = spec["kind"]
    if kind == "docx":
        return docgen.docx(spec["paragraphs"], props)
    if kind == "xlsx":
        return docgen.xlsx(spec["rows"], props)
    if kind == "pdf":
        return docgen.pdf(spec["lines"], props)
    if kind == "txt":
        return spec["text"].encode("utf-8")
    if kind in docgen.GENERATORS:
        return docgen.generate(kind, spec["size"], spec["label"])
    raise ConfigError(f"{spec['id']}: unknown file kind {kind}")


def is_large(spec: Mapping[str, Any]) -> bool:
    return spec["kind"] in docgen.GENERATORS and spec["size"] > INLINE_MAX


def generated_of(spec: Mapping[str, Any]) -> tuple[str, int, str] | None:
    return (
        (spec["kind"], spec["size"], spec["label"]) if spec["kind"] in docgen.GENERATORS else None
    )


def drive_folder_name(ctx: Context) -> str:
    return f"{TAG} {ctx.corpus['files']['drive_folder']}"


# ---------------------------------------------------------------- the plan


def _folder_order(folders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [f for f in folders if not f.get("parent")] + [f for f in folders if f.get("parent")]


def _lookup(phase: str, path: str, params: dict[str, str], lookup: str = "tagged") -> Step:
    return Step(
        phase=phase,
        kind="lookup",
        method="GET",
        path=path,
        params=tuple(params.items()),
        lookup=lookup,
    )


def folder_steps(ctx: Context, owner: str, phases: set[str]) -> list[Step]:
    folders = _folder_order([f for f in ctx.corpus["folders"]["folders"] if _owner(f) == owner])
    if not folders or not phases & {"folders", "mail"}:
        return []
    params = {"$top": "100", "$select": "id,displayName", "$expand": KEY_EXPAND}
    steps = [_lookup("folders", "/me/mailFolders", params)]
    for parent in dict.fromkeys(f["parent"] for f in folders if f.get("parent")):
        steps.append(
            _lookup("folders", f"/me/mailFolders/{{folder:{parent}}}/childFolders", params)
        )
    if "folders" not in phases:
        return steps
    for folder in folders:
        parent = folder.get("parent")
        path = f"/me/mailFolders/{{folder:{parent}}}/childFolders" if parent else "/me/mailFolders"
        body = {
            "displayName": f"{TAG} {folder['name']}",
            "singleValueExtendedProperties": [key_prop(f"folder:{folder['key']}")],
        }
        steps.append(
            Step("folders", "create", "POST", path, body=body, key=f"folder:{folder['key']}")
        )
    return steps


def message_body(message: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    draft = bool(message.get("draft")) or ctx.mail_mode == "draft"
    body: dict[str, Any] = {}
    if message.get("subject") is not None:
        body["subject"] = message["subject"]
    body["body"] = {"contentType": message["body"]["type"], "content": message["body"]["content"]}
    if not message.get("draft"):
        body["from"] = ctx.address(message["from"])
        body["sender"] = ctx.address(message["from"])
    body["toRecipients"] = [ctx.address(p) for p in message.get("to", [])]
    if message.get("cc"):
        body["ccRecipients"] = [ctx.address(p) for p in message["cc"]]
    body["categories"] = [TAG, *message.get("categories", [])]
    if message.get("importance"):
        body["importance"] = message["importance"]
    if message.get("flag"):
        body["flag"] = {"flagStatus": message["flag"]}
    if not message.get("draft"):
        body["isRead"] = bool(message.get("read"))
    props = [key_prop(f"mail:{message['id']}")]
    if message.get("thread"):
        topic = ctx.corpus["mail"]["threads"][message["thread"]]["topic"]
        times = sorted(
            {
                received_at(m["received"], ctx.anchor)
                for m in ctx.corpus["mail"]["messages"]
                if m.get("thread") == message["thread"] and "received" in m
            }
        )
        mine = received_at(message["received"], ctx.anchor)
        replies = [t for t in times[1:] if t <= mine]
        props.append({"id": CONV_TOPIC_PROP, "value": topic})
        props.append(
            {
                "id": CONV_INDEX_PROP,
                "value": conversation_index(message["thread"], times[0], replies),
            }
        )
    if not draft:
        moment = iso_z(received_at(message["received"], ctx.anchor))
        flags = MSGFLAG_READ if message.get("read") else 0
        props.append({"id": FLAGS_PROP, "value": str(flags)})
        props.append({"id": DELIVERY_PROP, "value": moment})
        props.append({"id": SUBMIT_PROP, "value": moment})
    body["singleValueExtendedProperties"] = props
    attachments = {a["id"]: a for a in ctx.corpus["files"]["attachments"]}
    inline = [ref for ref in message.get("attachments", []) if not is_large(attachments[ref])]
    if inline:
        body["attachments"] = [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": attachments[ref]["name"],
                "contentType": attachments[ref]["content_type"],
                "contentBytes": base64.b64encode(file_bytes(attachments[ref], ctx)).decode("ascii"),
            }
            for ref in inline
        ]
    return body


def attachment_steps(message: Mapping[str, Any], ctx: Context) -> list[Step]:
    attachments = {a["id"]: a for a in ctx.corpus["files"]["attachments"]}
    steps: list[Step] = []
    for spec in (attachments[ref] for ref in message.get("attachments", [])):
        if not is_large(spec):
            continue
        parent = f"/me/messages/{{mail:{message['id']}}}/attachments"
        item = {
            "attachmentType": "file",
            "name": spec["name"],
            "size": spec["size"],
            "contentType": spec["content_type"],
        }
        steps += [
            Step(
                "mail",
                "lookup",
                "GET",
                parent,
                (("$select", "id,name"),),
                key=message["id"],
                lookup="attachments",
            ),
            Step(
                "mail",
                "upload",
                "POST",
                f"{parent}/createUploadSession",
                body={"AttachmentItem": item},
                key=f"attachment:{message['id']}:{spec['name']}",
                payload=file_bytes(spec, ctx),
                generated=generated_of(spec),
            ),
        ]
    return steps


def mail_steps(ctx: Context, owner: str, phases: set[str]) -> list[Step]:
    messages = [m for m in ctx.corpus["mail"]["messages"] if _owner(m) == owner]
    if "mail" not in phases or not messages:
        return []
    params = {
        "$filter": TAG_FILTER,
        "$select": "id,categories,subject",
        "$expand": KEY_EXPAND,
        "$top": "100",
    }
    steps = [_lookup("mail", "/me/messages", params)]
    for message in messages:
        folder = message["folder"]
        target = folder if folder in WELL_KNOWN_FOLDERS else f"{{folder:{folder}}}"
        steps.append(
            Step(
                "mail",
                "create",
                "POST",
                f"/me/mailFolders/{target}/messages",
                body=message_body(message, ctx),
                key=f"mail:{message['id']}",
            )
        )
        steps += attachment_steps(message, ctx)
    return steps


def _event_day(event: Mapping[str, Any], anchor: dt.date) -> dt.date:
    day = anchor + dt.timedelta(days=int(event["day"]))
    recurrence = event.get("recurrence")
    if recurrence:
        names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        wanted = names.index(recurrence["days"][0])
        day += dt.timedelta(days=(wanted - day.weekday()) % 7)
    return day


def event_body(event: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    day = _event_day(event, ctx.anchor)
    zone = event["time_zone"]
    if event.get("all_day"):
        start = f"{day.isoformat()}T00:00:00"
        end = f"{(day + dt.timedelta(days=1)).isoformat()}T00:00:00"
    else:
        start = f"{day.isoformat()}T{event['start']}:00"
        end = f"{day.isoformat()}T{event['end']}:00"
    body: dict[str, Any] = {
        "subject": event["subject"],
        "body": {"contentType": "text", "content": event["body"]},
        "start": {"dateTime": start, "timeZone": zone},
        "end": {"dateTime": end, "timeZone": zone},
        "isAllDay": bool(event.get("all_day")),
        "isReminderOn": False,
        "showAs": "free" if event.get("all_day") else "busy",
        "categories": [TAG],
        "singleValueExtendedProperties": [key_prop(f"event:{event['id']}")],
    }
    if event.get("location"):
        body["location"] = {"displayName": event["location"]}
    recurrence = event.get("recurrence")
    if recurrence:
        body["recurrence"] = {
            "pattern": {
                "type": "weekly",
                "interval": 1,
                "daysOfWeek": recurrence["days"],
                "firstDayOfWeek": "monday",
            },
            "range": {
                "type": "numbered",
                "startDate": day.isoformat(),
                "numberOfOccurrences": recurrence["count"],
                "recurrenceTimeZone": zone,
            },
        }
    return body


def event_steps(ctx: Context, owner: str, phases: set[str]) -> list[Step]:
    events = [e for e in ctx.corpus["events"]["events"] if _owner(e) == owner]
    if "events" not in phases or not events:
        return []
    params = {
        "$filter": TAG_FILTER,
        "$select": "id,categories,subject",
        "$expand": KEY_EXPAND,
        "$top": "100",
    }
    steps = [_lookup("events", "/me/events", params)]
    for event in events:
        steps.append(
            Step(
                "events",
                "create",
                "POST",
                "/me/events",
                body=event_body(event, ctx),
                key=f"event:{event['id']}",
            )
        )
    return steps


def file_steps(ctx: Context, owner: str, phases: set[str]) -> list[Step]:
    files = [f for f in ctx.corpus["files"]["files"] if _owner(f) == owner]
    if "files" not in phases or not files:
        return []
    folder = drive_folder_name(ctx)
    steps = [
        _lookup(
            "files", f"/me/drive/root:/{folder}", {"$select": "id,name,folder"}, "drive-folder"
        ),
        _lookup(
            "files",
            "/me/drive/items/{drive:folder}/children",
            {"$select": "id,name,size", "$top": "200"},
            "drive-children",
        ),
        Step(
            "files",
            "create",
            "POST",
            "/me/drive/root/children",
            body={"name": folder, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"},
            key="drive:folder",
        ),
    ]
    for spec in files:
        name = f"{TAG} {spec['name']}"
        data, large = file_bytes(spec, ctx), is_large(spec)
        at = f"/me/drive/items/{{drive:folder}}:/{name}:"
        session = {"item": {"@microsoft.graph.conflictBehavior": "fail"}}
        steps.append(
            Step(
                "files",
                "upload" if large else "create",
                "POST" if large else "PUT",
                f"{at}/{'createUploadSession' if large else 'content'}",
                body=session if large else data,
                content_type=UPLOAD_TYPES[spec["kind"]],
                key=f"file:{name}",
                payload=data if large else None,
                generated=generated_of(spec),
            )
        )
    return steps


def build_steps(ctx: Context, index: int, phases: set[str]) -> list[Step]:
    owner = ctx.persona(index)
    return [
        *folder_steps(ctx, owner, phases),
        *mail_steps(ctx, owner, phases),
        *event_steps(ctx, owner, phases),
        *file_steps(ctx, owner, phases),
        *(step for family in FAMILIES for step in family.steps(ctx, owner, phases)),
    ]


def known_keys(ctx: Context, owner: str) -> set[str]:
    corpus = ctx.corpus
    keys = {f"folder:{f['key']}" for f in corpus["folders"]["folders"] if _owner(f) == owner}
    keys |= {f"mail:{m['id']}" for m in corpus["mail"]["messages"] if _owner(m) == owner}
    keys |= {f"event:{e['id']}" for e in corpus["events"]["events"] if _owner(e) == owner}
    return keys


# ---------------------------------------------------------------- safety checks


def read_upns(env: Mapping[str, str], required: bool) -> tuple[str, str, str]:
    raw = env.get("SEED_UPNS", "")
    if not raw:
        if required:
            raise ConfigError(
                "set SEED_UPNS to the three test UPNs (Mia, Anna, Tom), comma-separated"
            )
        return ("mia@seed.invalid", "anna@seed.invalid", "tom@seed.invalid")
    upns = [u.strip().lower() for u in raw.split(",") if u.strip()]
    if len(upns) != 3 or len(set(upns)) != 3:
        raise ConfigError("SEED_UPNS must hold exactly three different UPNs")
    domains = {u.rpartition("@")[2] for u in upns}
    if (
        any(u.count("@") != 1 or not u.partition("@")[0] for u in upns)
        or len(domains) != 1
        or "" in domains
    ):
        raise ConfigError("SEED_UPNS must hold three addresses in one domain")
    return (upns[0], upns[1], upns[2])


def read_extras(env: Mapping[str, str], upns: tuple[str, ...], required: bool) -> dict[str, str]:
    found: dict[str, str] = {}
    for name in EXTRA_ENV:
        raw = env.get(name, "").strip().lower()
        local, _, domain = raw.partition("@")
        if raw and (raw.count("@") != 1 or not local or "." not in domain or "," in raw):
            raise ConfigError(f"{name} must hold one address")
        if raw:
            found[name] = raw
        elif not required:
            found[name] = f"{name.lower()}@seed.invalid"
    if set(found.values()) & set(upns) or len(set(found.values())) != len(found):
        raise ConfigError("SEED_UPNS and the SEED_*_UPN addresses must all differ")
    return found


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def check_recipients(
    steps: list[Step], upns: tuple[str, ...], extras: Mapping[str, str] | None = None
) -> None:
    """Refuse any address-like token in any request that is not one of SEED_UPNS. The extra
    addresses pass everywhere except in a sendMail request."""
    personas = {u.lower() for u in upns}
    elsewhere = personas | {e.lower() for e in (extras or {}).values()}
    for step in steps:
        allowed = personas if step.path.lower().endswith("/sendmail") else elsewhere
        texts = [step.path, *(v for _, v in step.params)]
        if isinstance(step.body, Mapping):
            texts += list(_strings(step.body))
        for text in texts:
            for token in ADDRESS_TOKEN.findall(text.replace("/", " ")):
                if token.lower() not in allowed:
                    raise Refused(
                        f"{step.key or step.path}: address {token!r} is not in SEED_UPNS; nothing was sent"
                    )


def redact(text: str, secret: str | None) -> str:
    if secret:
        text = text.replace(secret, "<redacted>")
    return re.sub(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*", "<redacted>", text)


# ---------------------------------------------------------------- Graph client


class Graph:
    def __init__(
        self,
        token: str,
        *,
        transport: httpx.BaseTransport | None = None,
        max_requests: int = MAX_REQUESTS,
        sleep: Callable[[float], None] = time.sleep,
        shared_upn: str | None = None,
    ) -> None:
        self._token = token
        self._client = httpx.Client(transport=transport, timeout=60.0, follow_redirects=False)
        self._sleep = sleep
        self._shared = f"/v1.0/users/{shared_upn.lower()}/mailfolders" if shared_upn else None
        self._upload_url: str | None = None
        self._known: dict[str, set[str]] = {"team": set(), "drive": set(), "chat": set()}
        self.max_requests = max_requests
        self.count = 0
        self.sends = 0
        self.phase = ""
        self.phase_counts: Counter[str] = Counter()
        self.me_id: str | None = None

    def __repr__(self) -> str:
        return f"Graph(requests={self.count})"

    def close(self) -> None:
        self._client.close()

    def learn(self, kind: str, identifier: str) -> None:
        self._known[kind].add(identifier)

    def _guard(self, method: str, url: str) -> None:
        parts = urlsplit(url)
        if method == "PUT" and url == self._upload_url:
            return
        path = unquote(parts.path)
        decoded = path
        for _ in range(3):
            decoded = unquote(decoded)
        if "\\" in decoded or any(part in ("", ".", "..") for part in decoded.split("/")[1:]):
            raise Refused(f"refused {parts.path}: it holds an empty segment or a dot segment")
        mine = [f"/v1.0/users/{self.me_id}", f"/v1.0/users('{self.me_id}')"] if self.me_id else []
        own = next(
            (
                "/v1.0/me" + path[len(prefix) :]
                for prefix in mine
                if path.lower().startswith(prefix.lower() + "/")
            ),
            path,
        ).lower()
        if SENDING.fullmatch(own):
            raise Refused(f"refused {parts.path}: only POST /me/sendMail sends mail")
        if method == "POST" and own == "/v1.0/me/sendmail":
            if (
                parts.scheme == "https"
                and parts.netloc == "graph.microsoft.com"
                and (self.phase != SEND_PHASE or self.sends >= MAX_SENDS)
            ):
                raise Refused(
                    f"refused a send: only the {SEND_PHASE} phase sends, {MAX_SENDS} at most"
                )
            self.sends += 1
        creates_team = method == "POST" and parts.path == TEAMS_PATH
        creates_chat = method == "POST" and parts.path == CHATS_PATH
        polls_team = method == "GET" and TEAM_OPERATION.fullmatch(parts.path) is not None
        if (
            parts.scheme == "https"
            and parts.netloc == "graph.microsoft.com"
            and (creates_team or creates_chat or polls_team)
        ):
            return
        prefixes = ["/v1.0/me"]
        if self.me_id:
            prefixes += [f"/v1.0/users/{self.me_id}", f"/v1.0/users('{self.me_id}')"]
        if parts.scheme != "https" or parts.netloc != "graph.microsoft.com":
            raise Refused(
                f"refused a request to {parts.scheme}://{parts.netloc}: only {BASE}/me is allowed"
            )
        if self._shared and (path.lower() + "/").startswith(self._shared + "/"):
            return
        if any(
            (found := rule.fullmatch(path)) is not None and found[1] in self._known[kind]
            for kind, rule in MEMBER_PATHS
        ):
            return
        if not any(parts.path == p or parts.path.startswith(p + "/") for p in prefixes):
            raise Refused(
                f"refused a request to {parts.path}: only the signed-in user's own data is allowed"
            )

    def request(
        self,
        method: str,
        path_or_url: str,
        *,
        params: Mapping[str, str] | None = None,
        body: Any = None,
        content_type: str | None = None,
        ok_statuses: tuple[int, ...] = (),
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        url = path_or_url if path_or_url.startswith("https://") else BASE + path_or_url
        self._guard(method, url)
        shown = urlsplit(url).path
        for attempt in range(5):
            if self.phase_counts[self.phase] >= self.max_requests:
                raise CapReached(
                    f"stopped at the cap of {self.max_requests} requests for phase {self.phase or '-'}; run apply again to continue"
                )
            self.count += 1
            self.phase_counts[self.phase] += 1
            sent = {"Authorization": f"Bearer {self._token}"} if url != self._upload_url else {}
            sent |= headers or {}
            kwargs: dict[str, Any] = {"params": params, "headers": sent}
            if isinstance(body, bytes):
                sent["Content-Type"] = content_type or "application/octet-stream"
                kwargs["content"] = body
            elif body is not None:
                kwargs["json"] = body
            try:
                response = self._client.request(method, url, **kwargs)
            except httpx.HTTPError as error:
                raise GraphError(f"{method} {shown}: {type(error).__name__}") from None
            retryable = response.status_code == 429 or (
                method == "GET" and response.status_code in (503, 504)
            )
            if retryable and attempt < 4:
                self._sleep(_retry_after(response))
                continue
            break
        if response.status_code >= 400 and response.status_code not in ok_statuses:
            raise GraphError(f"{method} {shown} -> {response.status_code} {_graph_error(response)}")
        return response

    def upload(self, session: Mapping[str, Any], payload: bytes) -> httpx.Response:
        url = str(session.get("uploadUrl", ""))
        if not url.startswith("https://"):
            raise GraphError("Graph answered no https uploadUrl")
        self._upload_url = url
        try:
            response = None
            for start in range(0, len(payload), CHUNK):
                chunk = payload[start : start + CHUNK]
                span = f"bytes {start}-{start + len(chunk) - 1}/{len(payload)}"
                response = self.request("PUT", url, body=chunk, headers={"Content-Range": span})
            if response is None:
                raise GraphError("nothing to upload")
            return response
        finally:
            self._upload_url = None

    def created_by_operation(self, response: httpx.Response) -> dict[str, Any]:
        """The team of a 202 answer, once its operation reports `succeeded`."""
        location = response.headers.get("location", "")
        team = TEAM_LOCATION.search(response.headers.get("content-location", ""))
        if team is None or not location:
            raise GraphError("Graph answered 202 with no Location and Content-Location headers")
        for _ in range(OPERATION_POLLS):
            status = self.request("GET", location).json().get("status")
            if status == "succeeded":
                return {"id": team[1]}
            if status == "failed":
                raise GraphError(f"the Teams operation {location} failed")
            self._sleep(OPERATION_WAIT)
        raise GraphError(
            f"the Teams operation did not finish in {int(OPERATION_POLLS * OPERATION_WAIT)} seconds"
        )

    def get_all(self, path: str, params: Mapping[str, str]) -> Iterator[dict[str, Any]]:
        response = self.request("GET", path, params=params)
        while True:
            page = response.json()
            yield from page.get("value", [])
            next_link = page.get("@odata.nextLink")
            if not next_link:
                return
            response = self.request("GET", next_link)


def _retry_after(response: httpx.Response) -> float:
    try:
        return min(max(float(response.headers.get("Retry-After", "5")), 0.0), MAX_RETRY_WAIT)
    except ValueError:
        return 5.0


def _graph_error(response: httpx.Response) -> str:
    try:
        error = response.json().get("error", {})
        return f"{error.get('code', '')}: {str(error.get('message', ''))[:200]}"
    except ValueError:
        return ""


def verify_me(graph: Graph, upns: tuple[str, str, str], index: int) -> None:
    me = graph.request("GET", "/me", params={"$select": "id,userPrincipalName"}).json()
    upn = str(me.get("userPrincipalName", "")).lower()
    if upn not in upns:
        raise Refused("the signed-in user is not in SEED_UPNS; nothing was changed")
    if upns.index(upn) + 1 != index:
        raise Refused(
            f"the signed-in user is SEED_UPNS position {upns.index(upn) + 1}, not --as {index}; nothing was changed"
        )
    graph.me_id = str(me.get("id", "")) or None


# ---------------------------------------------------------------- apply and cleanup


def _key_of(item: Mapping[str, Any]) -> str | None:
    for prop in item.get("singleValueExtendedProperties", []) or []:
        value = str(prop.get("value", ""))
        if prop.get("id", "").lower() == KEY_PROP.lower() and value.startswith(f"{TAG}:"):
            return value[len(TAG) + 1 :]
    return None


def _resolve(path: str, refs: Mapping[str, str]) -> str | None:
    missing = [name for name in re.findall(r"\{([^}]+)\}", path) if name not in refs]
    if missing:
        return None
    return re.sub(r"\{([^}]+)\}", lambda m: refs[m.group(1)], path)


def run_lookup(
    graph: Graph, step: Step, path: str, found: dict[str, dict[str, Any]], ctx: Context
) -> None:
    params = dict(step.params)
    if step.lookup in ("drive-folder", "single"):
        response = graph.request("GET", path, params=params, ok_statuses=(404,))
        key = "drive:folder" if step.lookup == "drive-folder" else str(step.key)
        named = step.lookup == "single" or response.json().get("name") == drive_folder_name(ctx)
        if response.status_code == 200 and named:
            found[key] = response.json()
            _learn(graph, step, response.json())
        return
    for item in graph.get_all(path, params):
        if step.lookup == "named":
            name = str(item.get("displayName") or item.get("title") or item.get("topic") or "")
            key = f"{step.phase}:{name}" if name.startswith(f"{TAG} ") else None
        elif step.lookup == "subject":
            key = f"subject:{item.get('subject')}"
        elif step.lookup == "members":
            key = f"member:{str(item.get('userPrincipalName') or '').lower()}"
        elif step.lookup == "attachments":
            key = f"attachment:{step.key}:{item.get('name')}"
        elif step.lookup == "replies":
            key = f"reply:{step.key}:{item['body']['content']}"
        else:
            key = f"file:{item.get('name')}" if step.lookup == "drive-children" else _key_of(item)
        if key:
            found[key] = item
            _learn(graph, step, item)


def _learn(graph: Graph, step: Step, item: Mapping[str, Any]) -> None:
    if step.learns:
        graph.learn(step.learns, str(item["id"]))


def apply(
    graph: Graph, steps: list[Step], ctx: Context, out: Callable[[str], None]
) -> tuple[int, int]:
    found: dict[str, dict[str, Any]] = {}
    created = skipped = 0
    for step in steps:
        refs = {key: item["id"] for key, item in found.items()}
        path = _resolve(step.path, refs)
        graph.phase = step.phase
        if step.kind == "lookup":
            if path is None:
                continue
            run_lookup(graph, step, path, found, ctx)
            continue
        if step.key in found:
            skipped += 1
            continue
        if path is None:
            raise ConfigError(
                f"{step.key}: {step.path} needs an item that does not exist yet; run the earlier phase first"
            )
        response = graph.request(step.method, path, body=step.body, content_type=step.content_type)
        if step.kind == "upload":
            sent = graph.upload(response.json(), cast("bytes", step.payload))
            found[str(step.key)] = sent.json() if sent.content else {"id": str(step.key)}
        else:
            if step.poll:
                answer = graph.created_by_operation(response)
            else:
                body = response.json() if response.content else {}
                answer = {"id": str(step.key), **body}
            found[str(step.key)] = answer
        _learn(graph, step, found[str(step.key)])
        created += 1
        out(f"created {step.key}")
    return created, skipped


def cleanup(
    graph: Graph,
    ctx: Context,
    index: int,
    phases: set[str],
    dry_run: bool,
    out: Callable[[str], None],
) -> int:
    owner = ctx.persona(index)
    known = known_keys(ctx, owner)
    deleted = 0

    def delete(method: str, path: str, label: str, body: Any = None) -> None:
        nonlocal deleted
        out(f"{'would delete' if dry_run else 'delete'} {label}")
        if not dry_run:
            graph.request(method, path, body=body)
        deleted += 1

    for family in FAMILIES:
        hook = getattr(family, "cleanup", None)
        if hook and (own := phases & set(family.PHASES)):
            for method, path, *rest in hook(graph, ctx, owner, own):
                delete(method, path, f"{method} {path}", rest[0] if rest else None)

    params = {
        "$filter": TAG_FILTER,
        "$select": "id,categories,subject",
        "$expand": KEY_EXPAND,
        "$top": "100",
    }
    for phase, collection in (("mail", "messages"), ("events", "events")):
        if phase not in phases:
            continue
        for item in graph.get_all(f"/me/{collection}", params):
            key = _key_of(item)
            if key in known and TAG in (item.get("categories") or []):
                delete("POST", f"/me/{collection}/{item['id']}/permanentDelete", str(key))
            else:
                out(
                    f"orphan kept ({collection}): {item.get('subject')!r} has the tag but no known key"
                )

    if "folders" in phases:
        names = {
            f"folder:{f['key']}": f"{TAG} {f['name']}"
            for f in ctx.corpus["folders"]["folders"]
            if _owner(f) == owner
        }
        folder_params = {"$top": "100", "$select": "id,displayName", "$expand": KEY_EXPAND}
        tagged: list[tuple[int, str, dict[str, Any]]] = []
        queue = [("/me/mailFolders", 0), ("/me/mailFolders/deleteditems/childFolders", 1)]
        while queue:
            path, depth = queue.pop(0)
            for item in graph.get_all(path, folder_params):
                key = _key_of(item)
                if key in names and item.get("displayName") == names[key]:
                    tagged.append((depth, str(key), item))
                    queue.append((f"/me/mailFolders/{item['id']}/childFolders", depth + 1))
        for _, key, item in sorted(tagged, key=lambda t: -t[0]):
            counts = graph.request(
                "GET",
                f"/me/mailFolders/{item['id']}",
                params={"$select": "totalItemCount,childFolderCount"},
            ).json()
            if dry_run or (
                counts.get("totalItemCount") == 0 and counts.get("childFolderCount") == 0
            ):
                delete("POST", f"/me/mailFolders/{item['id']}/permanentDelete", key)
            else:
                out(f"kept {key}: it still holds items or folders the seed did not create")

    if "teams" in phases:
        for team in graph.get_all("/me/joinedTeams", {"$select": "id,displayName"}):
            if str(team.get("displayName", "")).startswith(f"{TAG} "):
                out(f"kept team {team['displayName']!r}: the seed never deletes a team")
        out(f"kept every chat with {TAG} case- in its topic: Graph cannot delete a chat")

    if "files" in phases:
        names = {f"{TAG} {f['name']}" for f in ctx.corpus["files"]["files"] if _owner(f) == owner}
        folder = graph.request(
            "GET",
            f"/me/drive/root:/{drive_folder_name(ctx)}",
            params={"$select": "id,name,folder"},
            ok_statuses=(404,),
        )
        if folder.status_code == 200:
            folder_id = folder.json()["id"]
            for child in graph.get_all(
                f"/me/drive/items/{folder_id}/children", {"$select": "id,name", "$top": "200"}
            ):
                if child.get("name") in names:
                    delete("DELETE", f"/me/drive/items/{child['id']}", f"file:{child['name']}")
                else:
                    out(f"kept drive item {child.get('name')!r}: not in the corpus")
            remaining = graph.request(
                "GET", f"/me/drive/items/{folder_id}", params={"$select": "id,folder"}
            ).json()
            if dry_run or remaining.get("folder", {}).get("childCount") == 0:
                delete("DELETE", f"/me/drive/items/{folder_id}", "drive:folder")
            else:
                out("kept drive:folder: it still holds items the seed did not create")
    return deleted


def cleanup_cases(
    graph: Graph, ctx: Context, index: int, dry_run: bool, out: Callable[[str], None]
) -> int:
    deleted = 0
    for family in FAMILIES:
        for method, path, *rest in family.sweep(graph, ctx.persona(index)):
            out(f"{'would delete' if dry_run else 'delete'} {method} {path}")
            if not dry_run:
                graph.request(method, path, body=rest[0] if rest else None)
            deleted += 1
    return deleted


# ---------------------------------------------------------------- output


def _shown_body(body: Any) -> str:
    if isinstance(body, bytes):
        return f"<{len(body)} bytes sha256={hashlib.sha256(body).hexdigest()}>"

    def short(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                k: (
                    f"<{len(base64.b64decode(v))} bytes sha256={hashlib.sha256(base64.b64decode(v)).hexdigest()}>"
                    if k == "contentBytes"
                    else short(v)
                )
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [short(v) for v in value]
        return value

    return json.dumps(short(body), ensure_ascii=False, sort_keys=True)


def render_plan(ctx: Context, index: int, steps: list[Step]) -> list[str]:
    owner = ctx.persona(index)
    lines = [
        f"== run --as {index} ({owner}, {ctx.upns[index - 1]}), mail mode {ctx.mail_mode}, anchor {ctx.anchor} ==",
        f"GET /me?$select=id,userPrincipalName   [check: signed-in UPN is SEED_UPNS position {index}]",
    ]
    for step in steps:
        query = "&".join(f"{k}={v}" for k, v in step.params)
        note = (
            f"   [lookup, +1 call per further page{'; skipped when the parent is new' if '{' in step.path else ''}]"
            if step.kind == "lookup"
            else f"   [create {step.key} unless found]"
        )
        lines.append(f"{step.method} {step.path}{'?' + query if query else ''}{note}")
        if step.body is not None:
            lines.append(f"    {_shown_body(step.body)}")
        if step.payload is not None:
            lines.append(f"    upload {_shown_body(step.payload)}")
    summary = {phase: [s for s in steps if s.phase == phase] for phase in PHASES}
    for phase, phase_steps in summary.items():
        if phase_steps:
            lookups = sum(1 for s in phase_steps if s.kind == "lookup")
            lines.append(
                f"-- phase {phase}: {len(phase_steps)} calls ({lookups} lookups, {len(phase_steps) - lookups} creates)"
            )
    lines.append(
        f"-- total for --as {index}: {len(steps) + 1} calls at most on an empty mailbox (cap {MAX_REQUESTS} for each phase)"
    )
    return lines


def corpus_manifest(ctx: Context) -> dict[str, Any]:
    strings: set[str] = set(_strings(ctx.corpus))
    binaries = []
    for index in (1, 2, 3):
        for step in build_steps(ctx, index, set(PHASES)):
            raw = step.payload if step.payload is not None else step.body
            if isinstance(raw, bytes):
                name = (
                    step.path.split(":/")[1].removesuffix(":/content")
                    if ":/" in step.path
                    else step.path
                )
                if step.payload is not None:
                    name = str(step.key).rpartition(":")[2]
                strings.add(name)
                generator, _, label = step.generated or ("", 0, "")
                binaries.append(
                    {
                        "name": name,
                        "owner": ctx.persona(index),
                        "size": len(raw),
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        **({"generator": generator, "label": label} if generator else {}),
                    }
                )
            if isinstance(step.body, Mapping):
                for attachment in step.body.get("attachments", []):
                    raw = base64.b64decode(attachment["contentBytes"])
                    binaries.append(
                        {
                            "name": attachment["name"],
                            "owner": ctx.persona(index),
                            "size": len(raw),
                            "sha256": hashlib.sha256(raw).hexdigest(),
                        }
                    )
                strings.update(
                    _strings(
                        {
                            k: v
                            for k, v in step.body.items()
                            if k not in ("attachments", "singleValueExtendedProperties")
                        }
                    )
                )
                strings.update(
                    str(p["value"])
                    for p in step.body.get("singleValueExtendedProperties", [])
                    if p["id"] != CONV_INDEX_PROP
                )
    for family in FAMILIES:
        strings.update(cast("tuple[str, ...]", getattr(family, "STRINGS", ())))
        for name, raw in cast("Mapping[str, bytes]", getattr(family, "ASSETS", {})).items():
            binaries.append(
                {
                    "name": name,
                    "owner": "mia",
                    "size": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
    strings = {
        s
        for s in strings
        if len(s) >= 4 and not ADDRESS_TOKEN.search(s) and not re.match(r"\d{4}-\d{2}-\d{2}", s)
    }
    unique = {(b["name"], b["sha256"]): b for b in binaries}
    return {
        "tag": TAG,
        "strings": sorted(strings),
        "binaries": sorted(unique.values(), key=lambda b: (b["owner"], b["name"])),
    }


def corpus_counts(ctx: Context) -> dict[str, int]:
    corpus = ctx.corpus
    messages = corpus["mail"]["messages"]
    return {
        "mails": len(messages),
        "mails_unread_inbox_mia": sum(
            1
            for m in messages
            if _owner(m) == "mia" and m["folder"] == "inbox" and not m.get("read")
        ),
        "threads": len(corpus["mail"]["threads"]),
        "longest_thread": max(
            sum(1 for m in messages if m.get("thread") == t and _owner(m) == "mia")
            for t in corpus["mail"]["threads"]
        ),
        "events": len(corpus["events"]["events"]),
        "files": len(corpus["files"]["files"]),
        "attachments": len(corpus["files"]["attachments"]),
        "folders": len(corpus["folders"]["folders"]),
    }


# ---------------------------------------------------------------- command line


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "command", nargs="?", default="plan", choices=("plan", "apply", "cleanup", "corpus")
    )
    parser.add_argument(
        "--as",
        dest="index",
        type=int,
        choices=(1, 2, 3),
        help="1 = Mia, 2 = Anna, 3 = Tom (position in SEED_UPNS)",
    )
    parser.add_argument(
        "--phases",
        type=lambda text: text.split(","),
        help="limit to these phases, comma-separated; default: every phase that is not opt-in",
    )
    parser.add_argument(
        "--anchor",
        type=dt.date.fromisoformat,
        help="date that relative mail and event dates count from (default: today, UTC)",
    )
    parser.add_argument(
        "--mail-mode",
        choices=MAIL_MODES,
        default="extprops",
        help="extprops: received, non-draft mail (default); draft: fallback, plain drafts",
    )
    parser.add_argument(
        "--cases",
        action="store_true",
        help="cleanup: delete only the items that hold 'seed-v1 case-' in their name",
    )
    parser.add_argument(
        "--phase-cap", type=int, default=MAX_REQUESTS, help="the cap of requests for each phase"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="cleanup: list what would be deleted, delete nothing"
    )
    parser.add_argument(
        "--out", type=Path, help="corpus: write the manifest to this file instead of stdout"
    )
    parser.add_argument("--corpus", type=Path, default=CORPUS_DIR, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
    env: Mapping[str, str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    environ = os.environ if env is None else env
    args = parse_args(argv)
    token: str | None = None
    try:
        if not 1 <= args.phase_cap <= MAX_REQUESTS:
            raise ConfigError(f"--phase-cap must be within 1..{MAX_REQUESTS}")
        if unknown := sorted(set(args.phases or ()) - set(PHASES)):
            raise ConfigError(f"unknown phases {unknown}; the phases are {list(PHASES)}")
        writes = args.command in ("apply", "cleanup")
        if args.cases and args.command != "cleanup":
            raise ConfigError("--cases applies to cleanup only")
        if writes and args.index is None:
            raise ConfigError(f"{args.command} needs --as 1|2|3")
        upns = read_upns(environ, required=writes)
        extras = read_extras(environ, upns, required=writes)
        ctx = Context(
            corpus=load_corpus(args.corpus),
            upns=upns,
            anchor=args.anchor or dt.datetime.now(dt.UTC).date(),
            mail_mode=args.mail_mode,
            extras=extras,
        )
        default = set(PHASES) if args.command == "cleanup" else set(PHASES) - OPT_IN
        phases = set(args.phases or default)
        if args.command == "corpus":
            text = json.dumps(corpus_manifest(ctx), indent=2, ensure_ascii=False) + "\n"
            if args.out:
                args.out.write_text(text, encoding="utf-8")
            else:
                sys.stdout.write(text)
            print(json.dumps(corpus_counts(ctx)), file=sys.stderr)
            return 0
        indexes = [args.index] if args.index else [1, 2, 3]
        plans = {i: build_steps(ctx, i, phases) for i in indexes}
        for steps in plans.values():
            check_recipients(steps, ctx.upns, extras)
        if args.command == "plan":
            for index, steps in plans.items():
                print("\n".join(render_plan(ctx, index, steps)))
            return 0
        token = environ.get("GRAPH_TOKEN", "").strip()
        if not token:
            raise ConfigError(
                "set GRAPH_TOKEN (see README: export GRAPH_TOKEN=$(... get_token.py))"
            )
        graph = Graph(
            token,
            transport=transport,
            max_requests=args.phase_cap,
            sleep=sleep,
            shared_upn=extras.get(SHARED_ENV),
        )
        try:
            verify_me(graph, ctx.upns, args.index)
            if args.command == "apply":
                created, skipped = apply(graph, plans[args.index], ctx, print)
                print(f"done: {created} created, {skipped} already there, {graph.count} requests")
            else:
                if args.cases:
                    deleted = cleanup_cases(graph, ctx, args.index, args.dry_run, print)
                else:
                    deleted = cleanup(graph, ctx, args.index, phases, args.dry_run, print)
                print(
                    f"done: {deleted} {'to delete' if args.dry_run else 'deleted'}, {graph.count} requests"
                )
        finally:
            graph.close()
        return 0
    except SeedError as error:
        print(f"seed: {redact(str(error), token)}", file=sys.stderr)
        return error.code
    except Exception as error:  # noqa: BLE001 - last line: never print a traceback that could carry request data
        print(
            f"seed: unexpected {type(error).__name__}: {redact(str(error), token)}", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
