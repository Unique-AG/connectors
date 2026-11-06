"""The recorder's guard (plan v3 R4). It decides on each tool call and each request before the
request leaves, and it fails closed: a tool, path, host or address that no rule allows is refused.
The checks use `if`, never `assert`, so `python -O` keeps them."""

import html
import json
import re
import unicodedata
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import getaddresses
from fnmatch import fnmatchcase
from typing import cast
from urllib.parse import unquote

import httpx

from tests.e2e.recording.families import load

GRAPH_HOST = "graph.microsoft.com"
SEED_TAG = "seed-v1"
PREFLIGHT = "preflight"
DEFAULT_CAP = 40
MAX_CAP = 100
FAMILIES = load()
READ_TOOLS = FAMILIES.read_tools
WRITE_TOOLS: Mapping[str, tuple[str, ...]] = FAMILIES.write_tools
SEED_CASE = f"{SEED_TAG} case-"
INVITING_ARGUMENTS = frozenset(
    {"attendees", "optional_attendees", "room_addresses", "online_meeting"}
)
WELL_KNOWN_FOLDERS = frozenset(
    {"inbox", "archive", "drafts", "sentitems", "deleteditems", "junkemail"}
)
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_PREFLIGHT_PATHS = frozenset({"/v1.0/me", "/v1.0/organization", "/v1.0/me/drive"})
_DESTINATIONS = frozenset({"DestinationId", "destinationId"})
_NAMES = frozenset({"name", "displayName", "subject", "title", "topic"})
_RECIPIENTS = ("toRecipients", "ccRecipients", "bccRecipients")
_EVENT_CALENDAR = "/calendars/*/events/"
_FOLDERS = "/v1.0/me/mailFolders/"
_CREATE_OR_GET = "/v1.0/me/onlineMeetings/createOrGet"
_TEAM_CHANNELS = re.compile(r"/v1\.0/teams/([^/]+)/channels")
_OTHER_USER = re.compile(r"/v1\.0/users/([^/]+)")
_BOUND_USER = re.compile(r"/users\('([^']*)'\)")
_SHARED = "SEED_SHARED_UPN"
_CALENDAR_FIELDS = frozenset({"canEdit", "canShare", "isDefaultCalendar"})
_REPLY = "json.automaticRepliesSetting."
SCHEDULED_REPLY_DAYS = 3
_SEPARATORS = re.compile(r"[\s,;:'\"()<>&?=/\[\]{}|\\]+")
_ANNOTATION_KEY = re.compile(r"(?<=[?&])(?:%40|@)microsoft\.graph\.[A-Za-z]+(?==)")


class Refused(Exception):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC)


def unwrapped(text: str) -> str:
    for _ in range(4):
        text = unicodedata.normalize("NFKC", html.unescape(unquote(text)))
    return text


def foreign_address(text: str, addresses: frozenset[str]) -> str | None:
    """Names the first part of `text` that is not one of `addresses`, or None. Any @, a
    full-width one or a percent-encoded one included, must belong to an address that
    `getaddresses` parses and that is on the allowlist once its domain is IDNA-encoded."""
    for token in _SEPARATORS.split(unwrapped(text)):
        if "@" not in token or any(shape.fullmatch(token) for shape in FAMILIES.thread_id):
            continue
        parsed = [address for _, address in getaddresses([token]) if "@" in address]
        if len(parsed) != 1 or parsed[0].count("@") != token.count("@"):
            return "an @ that is not part of one parseable address"
        local, _, domain = parsed[0].rpartition("@")
        try:
            ascii_domain = domain.encode("idna").decode()
        except UnicodeError:
            return "an address whose domain is not a valid IDNA name"
        if f"{local}@{ascii_domain}".casefold() not in addresses:
            return "an address that is not a test user"
    return None


def match_glob(glob: str, shown: str) -> list[str] | None:
    pattern, path = glob.split("/"), shown.split("/")
    if len(pattern) != len(path) or not all(
        fnmatchcase(p, g) for g, p in zip(pattern, path, strict=True)
    ):
        return None
    return [
        p[: len(p) - len(g.rpartition("*")[2])]
        for g, p in zip(pattern, path, strict=True)
        if g[:1] == "*"
    ]


def _name(where: str) -> bool:
    return where.rsplit(".", 1)[-1] in _NAMES


def strings(value: object, where: str = "args") -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield where, value
    elif isinstance(value, Mapping):
        for key, one in cast("Mapping[str, object]", value).items():
            yield from strings(one, f"{where}.{key}")
    elif isinstance(value, list):
        for n, one in enumerate(cast("list[object]", value)):
            yield from strings(one, f"{where}[{n}]")


def _is_tagged(found: Mapping[str, object]) -> bool:
    categories = found.get("categories")
    if isinstance(categories, list) and SEED_TAG in cast("list[object]", categories):
        return True
    named = found.get("name", found.get("displayName"))
    return isinstance(named, str) and named.startswith(f"{SEED_TAG} ")


def mappings(value: object) -> Iterator[Mapping[str, object]]:
    if isinstance(value, list):
        for one in cast("list[object]", value):
            yield from mappings(one)
    elif isinstance(value, Mapping):
        found = cast("Mapping[str, object]", value)
        yield found
        for one in found.values():
            yield from mappings(one)


def seed_ids(value: object) -> Iterator[str]:
    for found in mappings(value):
        if isinstance(found.get("id"), str) and _is_tagged(found):
            yield cast("str", found["id"])


def default_calendar_ids(value: object) -> Iterator[str]:
    for found in mappings(value):
        if isinstance(found.get("id"), str) and found.get("isDefaultCalendar") is True:
            yield cast("str", found["id"])


@dataclass
class Guard:
    allowed_upn: str
    allowed_addresses: frozenset[str]
    allow_writes: bool
    cap: int = DEFAULT_CAP
    me_id: str = ""
    drive_ids: frozenset[str] = frozenset()
    people: frozenset[str] = frozenset()
    sent: int = 0
    seen_seed: set[str] = field(default_factory=set[str])
    created: set[str] = field(default_factory=set[str])
    default_calendars: set[str] = field(default_factory=set[str])
    well_known: set[str] = field(default_factory=set[str])
    drafted: dict[str, tuple[str, ...]] = field(default_factory=dict[str, tuple[str, ...]])
    redirect: str | None = None
    write_failed: bool = False
    extras: Mapping[str, str] = field(default_factory=dict[str, str])
    case_chats: set[str] = field(default_factory=set[str])
    shared_calendars: set[str] = field(default_factory=set[str])
    now: Callable[[], datetime] = _utc_now

    def _extra_for(self, tool: str, variable: str | None = None) -> frozenset[str]:
        return frozenset(
            address.casefold()
            for name, address in self.extras.items()
            if tool in FAMILIES.address_uses.get(name, ()) and variable in (None, name)
        )

    def _addresses(self, tool: str) -> frozenset[str]:
        return self.allowed_addresses | self._extra_for(tool)

    def refuses_call(self, tool: str, args: Mapping[str, object]) -> str | None:
        writes = tool in WRITE_TOOLS
        if tool not in READ_TOOLS and not writes:
            return f"{tool} is not on the read or the write allowlist of the recorder"
        if writes and not self.allow_writes:
            return f"{tool} is a write and needs --allow-writes"
        mailbox = args.get("mailbox")
        mailboxes = {self.allowed_upn.casefold()} | self._extra_for(tool, _SHARED)
        if mailbox is not None and str(mailbox).casefold() not in mailboxes:
            return f"{tool} args.mailbox names a mailbox that is not the recording user's"
        inviting = sorted(key for key in INVITING_ARGUMENTS if args.get(key))
        if writes and inviting and tool not in FAMILIES.inviters:
            return f"{tool} would invite people or rooms through {inviting}"
        for where, value in strings({key: args[key] for key in inviting} if writes else {}):
            if "@" not in value and value not in self.people and not _name(where):
                return f"{tool} would invite {where}, which is no address and no id of a test user"
        for where, value in strings(args):
            if (outside := foreign_address(value, self._addresses(tool))) is not None:
                return f"{tool} {where} holds {outside}"
        return None

    def refuses_request(self, request: httpx.Request, tool: str) -> str | None:
        if self.sent >= self.cap:
            return f"the cap of {self.cap} requests for one run is reached"
        refusal = self._refuses(request, tool)
        if refusal is None:
            self.sent += 1
        return refusal

    def _refuses(self, request: httpx.Request, tool: str) -> str | None:
        method, host = request.method, request.url.host
        path = self._own(unquote(request.url.path), tool)
        shown = f"{method} {path}"
        shared = path != unquote(request.url.path) and self._own(unquote(request.url.path)) == (
            unquote(request.url.path)
        )
        addresses = self._addresses(tool)
        if request.url.scheme != "https":
            return f"{shown} does not use https"
        if host != GRAPH_HOST:
            return self._refuses_hop(request)
        decoded = unwrapped(request.url.path)
        if "\\" in decoded or any(part in ("", ".", "..") for part in decoded.split("/")[1:]):
            return f"{shown} holds an empty segment or a dot segment"
        if not self._pinned(method, path, tool):
            return f"{shown} is outside /v1.0/me/ and the recording user's own drive"
        target = _ANNOTATION_KEY.sub("", str(request.url.raw_path, "ascii"))
        if outside := foreign_address(target, addresses):
            return f"{method} request URL holds {outside}"
        body = self._body_strings(request)
        for _, value in body:
            if (outside := foreign_address(value, addresses)) is not None:
                return f"{shown} body holds {outside}"
            known = self.people | addresses | {self.me_id.casefold()}
            for bound in cast("list[str]", _BOUND_USER.findall(value)):
                if bound.casefold() not in known - {""}:
                    return f"{shown} body binds a person that is not a test user"
        if method not in _WRITE_METHODS or self._reads_by_glob(shown, tool):
            return None
        return self._refuses_write(shown, path, tool, body, shared)

    def _refuses_hop(self, request: httpx.Request) -> str | None:
        host = request.url.host
        if "authorization" in request.headers:
            return f"a request to {host} carries an Authorization header"
        if not host.endswith(".sharepoint.com") or str(request.url) != self.redirect:
            return f"{request.method} to {host} is not the redirect Graph answered"
        return None if request.method == "GET" else f"{request.method} to {host} is not a GET"

    def _refuses_write(
        self, shown: str, path: str, tool: str, body: list[tuple[str, str]], shared: bool = False
    ) -> str | None:
        if not self.allow_writes or tool not in WRITE_TOOLS:
            return f"{shown} is a write that {tool} may not make here"
        hit = next(
            (
                (glob, found)
                for glob in WRITE_TOOLS[tool]
                if (found := match_glob(glob, shown)) is not None
            ),
            None,
        )
        if hit is None:
            return f"{shown} is not a write path of {tool}"
        glob, matched = hit
        if self.write_failed:
            return f"{shown} would repeat a write after a failed or throttled write"
        targets = [unquote(one) for one in matched]
        targets += [
            value
            for where, value in body
            if where.removeprefix("json.") in _DESTINATIONS | FAMILIES.destinations
        ]
        only = FAMILIES.created_only.get(tool)
        if only is not None and unquote(matched[only]) not in self.created | self.case_chats:
            return f"{shown} is a write of {tool} to an item that this run did not create"
        defaults = (
            self.default_calendars | self.shared_calendars
            if "/calendars/*/events" in glob
            else set[str]()
        )
        for target in targets:
            known = (
                target
                in self.seen_seed | self.created | self.well_known | self.case_chats | defaults
            )
            if target.casefold() not in WELL_KNOWN_FOLDERS and not known:
                return f"{shown} targets an item that this run did not read as seed data"
            for value in self.drafted.get(target, ()):
                if (outside := foreign_address(value, self.allowed_addresses)) is not None:
                    return f"{shown} sends a draft whose recipients hold {outside}"
        for where, value in body:
            if value in FAMILIES.forbidden.get(where.rsplit(".", 1)[-1], ()) and not (
                self._short_reply(where, value, body)
            ):
                return f"{shown} body sets {where} to {value}, which no recording may do"
        if not matched and (shared or not path.startswith("/v1.0/me/")):
            tagged = any(SEED_CASE in value for where, value in body if _name(where))
            if not tagged:
                return f"{shown} creates an item outside /v1.0/me/ with no {SEED_CASE} name"
        return None

    def _short_reply(self, where: str, value: str, body: list[tuple[str, str]]) -> bool:
        """A scheduled automatic reply for nobody outside, and over within three days."""
        found = dict(body)
        if (where, value) != (f"{_REPLY}status", "scheduled"):
            return False
        try:
            end = datetime.fromisoformat(found[f"{_REPLY}scheduledEndDateTime.dateTime"])
        except KeyError, ValueError:
            return False
        end = end if end.tzinfo else end.replace(tzinfo=UTC)
        return (
            found.get(f"{_REPLY}scheduledEndDateTime.timeZone") == "UTC"
            and found.get(f"{_REPLY}externalAudience") == "none"
            and self.now() < end <= self.now() + timedelta(days=SCHEDULED_REPLY_DAYS)
        )

    @staticmethod
    def _reads_by_glob(shown: str, tool: str) -> bool:
        globs = (*FAMILIES.read_posts.get(tool, ()), *FAMILIES.read_gets.get(tool, ()))
        return any(match_glob(glob, shown) is not None for glob in globs)

    def _own(self, path: str, tool: str | None = None) -> str:
        users = (self.me_id, self.allowed_upn, *(self._extra_for(tool, _SHARED) if tool else ()))
        for user in filter(None, users):
            for prefix in (f"/v1.0/users/{user}", f"/v1.0/users('{user}')"):
                if path.casefold() == prefix.casefold() or path.casefold().startswith(
                    prefix.casefold() + "/"
                ):
                    return "/v1.0/me" + path[len(prefix) :]
        return path

    def _pinned(self, method: str, path: str, tool: str) -> bool:
        if tool == PREFLIGHT:
            other = _OTHER_USER.fullmatch(path)
            return method == "GET" and (
                path in _PREFLIGHT_PATHS
                or (other is not None and other[1].casefold() in self.allowed_addresses)
            )
        if path == "/v1.0/me" or path.startswith("/v1.0/me/"):
            return True
        writes = WRITE_TOOLS.get(tool, ())
        if method in _WRITE_METHODS and any(
            match_glob(glob, f"{method} {path}") is not None for glob in writes
        ):
            return True
        if self._reads_by_glob(f"{method} {path}", tool):
            return True
        if method == "GET" and any(path.startswith(prefix) for prefix in FAMILIES.prefixes):
            return True
        return any(path.startswith(f"/v1.0/drives/{drive}/") for drive in self.drive_ids)

    @staticmethod
    def _body_strings(request: httpx.Request) -> list[tuple[str, str]]:
        if not request.content:
            return []
        text = request.content.decode(errors="replace")
        try:
            return list(strings(cast("object", json.loads(text)), "json"))
        except ValueError:
            return [("body", text)]

    def _answers_a_create(self, request: httpx.Request) -> bool:
        if request.method == "PUT":
            return True
        named = any(
            SEED_CASE in value for where, value in self._body_strings(request) if _name(where)
        )
        return request.url.path.endswith(_CREATE_OR_GET) and named

    def _remember_well_known(self, request: httpx.Request, status: int, body: object) -> None:
        path = self._own(unquote(request.url.path))
        named = path.removeprefix(_FOLDERS)
        identifier = (
            cast("Mapping[str, object]", body).get("id") if isinstance(body, Mapping) else None
        )
        if (
            request.method == "GET"
            and status == 200
            and named != path
            and named.casefold() in WELL_KNOWN_FOLDERS
            and isinstance(identifier, str)
        ):
            self.well_known.add(identifier)

    def _remember_channels(self, request: httpx.Request, status: int, body: object) -> None:
        listed = _TEAM_CHANNELS.fullmatch(unquote(request.url.path))
        if (
            request.method == "GET"
            and status == 200
            and listed is not None
            and listed[1] in self.seen_seed
            and isinstance(body, Mapping)
        ):
            self.seen_seed.update(
                cast("str", found["id"])
                for found in mappings(cast("Mapping[str, object]", body).get("value"))
                if isinstance(found.get("id"), str)
            )

    def _remember_members(self, body: object) -> None:
        for found in mappings(body):
            mail = next((found[k] for k in ("email", "mail") if isinstance(found.get(k), str)), "")
            if (
                isinstance(found.get("id"), str)
                and "userId" in found
                and str(mail).casefold() in self.allowed_addresses
            ):
                self.seen_seed.add(cast("str", found["id"]))

    def _remember_chat_and_calendar(self, found: Mapping[str, object]) -> None:
        identifier, owner = found.get("id"), found.get("owner")
        if not isinstance(identifier, str):
            return
        if "topic" in found and SEED_CASE in str(found["topic"]):
            self.case_chats.add(identifier)
        address = (
            cast("Mapping[str, object]", owner).get("address")
            if isinstance(owner, Mapping)
            else None
        )
        if (
            found.keys() & _CALENDAR_FIELDS
            and isinstance(address, str)
            and address.casefold() in self.allowed_addresses
        ):
            self.shared_calendars.add(identifier)

    def _remember_draft(self, found: Mapping[str, object]) -> None:
        identifier = found.get("id")
        if isinstance(identifier, str) and any(key in found for key in _RECIPIENTS):
            recipients = [found.get(key) for key in _RECIPIENTS]
            self.drafted[identifier] = tuple(value for _, value in strings(recipients))

    def saw(self, request: httpx.Request, status: int, location: str | None, body: object) -> None:
        self.redirect = location if 300 <= status < 400 or status == 202 else None
        if status == 429 or status >= 500:
            self.write_failed = True
        self.seen_seed.update(seed_ids(body))
        self.default_calendars.update(default_calendar_ids(body))
        self._remember_well_known(request, status, body)
        self._remember_channels(request, status, body)
        self._remember_members(body)
        for found in mappings(body):
            self._remember_draft(found)
            self._remember_chat_and_calendar(found)
        made = status == 201 or (status == 200 and self._answers_a_create(request))
        if request.method in _WRITE_METHODS and made and isinstance(body, Mapping):
            created = cast("Mapping[str, object]", body).get("id")
            if isinstance(created, str):
                self.created.add(created)
