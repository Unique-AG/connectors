"""The recorder's guard (plan v3 R4). It decides on each tool call and each request before the
request leaves, and it fails closed: a tool, path, host or address that no rule allows is refused.
The checks use `if`, never `assert`, so `python -O` keeps them."""

import html
import json
import re
import unicodedata
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from email.utils import getaddresses
from fnmatch import fnmatch
from typing import cast
from urllib.parse import unquote

import httpx

GRAPH_HOST = "graph.microsoft.com"
SEED_TAG = "seed-v1"
PREFLIGHT = "preflight"
DEFAULT_CAP = 40
MAX_CAP = 100
READ_TOOLS = frozenset(
    {
        "outlook_list_mail",
        "outlook_read_mail",
        "outlook_read_thread",
        "outlook_browse_folders",
        "outlook_list_attachments",
        "outlook_read_attachment",
        "outlook_list_events",
        "outlook_read_event",
        "sharepoint_search_files",
        "sharepoint_read_file",
        "sharepoint_browse_folder",
    }
)
SEARCH_TOOLS = frozenset({"sharepoint_search_files"})
WRITE_TOOLS: Mapping[str, tuple[str, ...]] = {
    "outlook_move_mail": ("POST /v1.0/me/messages/*/move",),
    "outlook_mark_mail": ("PATCH /v1.0/me/messages/*",),
    "outlook_draft_mail": ("POST /v1.0/me/messages", "POST /v1.0/me/mailFolders/*/messages"),
    "outlook_create_event": (
        "POST /v1.0/me/events",
        "POST /v1.0/me/calendar/events",
        "POST /v1.0/me/calendars/*/events",
    ),
}
INVITING_ARGUMENTS = frozenset(
    {"attendees", "optional_attendees", "room_addresses", "online_meeting"}
)
WELL_KNOWN_FOLDERS = frozenset(
    {"inbox", "archive", "drafts", "sentitems", "deleteditems", "junkemail"}
)
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_PREFLIGHT_PATHS = frozenset({"/v1.0/me", "/v1.0/organization", "/v1.0/me/drive"})
_TARGET = re.compile(r"/v1\.0/me/(?:messages|events|mailFolders)/([^/]+)")
_DESTINATIONS = frozenset({"DestinationId", "destinationId"})
_FAILED = frozenset({429, 500, 502, 503, 504})
_SEPARATORS = re.compile(r"[\s,;:'\"()<>&?=/\[\]{}|\\]+")


class Refused(Exception):
    pass


def unwrapped(text: str) -> str:
    for _ in range(4):
        text = unicodedata.normalize("NFKC", html.unescape(unquote(text)))
    return text


def foreign_address(text: str, domains: frozenset[str]) -> str | None:
    """Names the first part of `text` that is not an address in `domains`, or None. Any @, a
    full-width one or a percent-encoded one included, must belong to an address that
    `getaddresses` parses and whose IDNA domain is on the allowlist."""
    for token in _SEPARATORS.split(unwrapped(text)):
        if "@" not in token:
            continue
        parsed = [address for _, address in getaddresses([token]) if "@" in address]
        if len(parsed) != 1 or parsed[0].count("@") != token.count("@"):
            return "an @ that is not part of one parseable address"
        domain = parsed[0].rpartition("@")[2]
        try:
            ascii_domain = domain.encode("idna").decode().casefold()
        except UnicodeError:
            return "an address whose domain is not a valid IDNA name"
        if ascii_domain not in domains:
            return "an address outside the allowed domain"
    return None


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


def seed_ids(value: object) -> Iterator[str]:
    if isinstance(value, list):
        for one in cast("list[object]", value):
            yield from seed_ids(one)
    elif isinstance(value, Mapping):
        found = cast("Mapping[str, object]", value)
        if isinstance(found.get("id"), str) and _is_tagged(found):
            yield cast("str", found["id"])
        for one in found.values():
            yield from seed_ids(one)


@dataclass
class Guard:
    allowed_upn: str
    allowed_domains: frozenset[str]
    allow_writes: bool
    cap: int = DEFAULT_CAP
    me_id: str = ""
    drive_ids: frozenset[str] = frozenset()
    sent: int = 0
    seen_seed: set[str] = field(default_factory=set[str])
    redirect: str | None = None
    write_failed: bool = False

    def refuses_call(self, tool: str, args: Mapping[str, object]) -> str | None:
        writes = tool in WRITE_TOOLS
        if tool not in READ_TOOLS and not writes:
            return f"{tool} is not on the read or the write allowlist of the recorder"
        if writes and not self.allow_writes:
            return f"{tool} is a write and needs --allow-writes"
        mailbox = args.get("mailbox")
        if mailbox is not None and str(mailbox).casefold() != self.allowed_upn.casefold():
            return f"{tool} args.mailbox names a mailbox that is not the recording user's"
        inviting = sorted(key for key in INVITING_ARGUMENTS if args.get(key))
        if writes and inviting:
            return f"{tool} would invite people or rooms through {inviting}"
        for where, value in strings(args):
            if (outside := foreign_address(value, self.allowed_domains)) is not None:
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
        path = self._own(unquote(request.url.path))
        shown = f"{method} {path}"
        if request.url.scheme != "https":
            return f"{shown} does not use https"
        if host != GRAPH_HOST:
            return self._refuses_hop(request)
        if not self._pinned(method, path, tool):
            return f"{shown} is outside /v1.0/me/ and the recording user's own drive"
        if outside := foreign_address(str(request.url.raw_path, "ascii"), self.allowed_domains):
            return f"{method} request URL holds {outside}"
        body = self._body_strings(request)
        for _, value in body:
            if (outside := foreign_address(value, self.allowed_domains)) is not None:
                return f"{shown} body holds {outside}"
        if method not in _WRITE_METHODS or (method, path) == ("POST", "/v1.0/search/query"):
            return None
        return self._refuses_write(shown, path, tool, body)

    def _refuses_hop(self, request: httpx.Request) -> str | None:
        host = request.url.host
        if "authorization" in request.headers:
            return f"a request to {host} carries an Authorization header"
        if not host.endswith(".sharepoint.com") or str(request.url) != self.redirect:
            return f"{request.method} to {host} is not the redirect Graph answered"
        return None if request.method == "GET" else f"{request.method} to {host} is not a GET"

    def _refuses_write(
        self, shown: str, path: str, tool: str, body: list[tuple[str, str]]
    ) -> str | None:
        if not self.allow_writes or tool not in WRITE_TOOLS:
            return f"{shown} is a write that {tool} may not make here"
        if not any(fnmatch(shown, pattern) for pattern in WRITE_TOOLS[tool]):
            return f"{shown} is not a write path of {tool}"
        if self.write_failed:
            return f"{shown} would repeat a write after a failed or throttled write"
        targets = [unquote(found[1]) for found in [_TARGET.match(path)] if found]
        targets += [value for where, value in body if where.rsplit(".", 1)[-1] in _DESTINATIONS]
        for target in targets:
            if target.casefold() not in WELL_KNOWN_FOLDERS and target not in self.seen_seed:
                return f"{shown} targets an item that this run did not read as seed data"
        return None

    def _own(self, path: str) -> str:
        for user in filter(None, (self.me_id, self.allowed_upn)):
            for prefix in (f"/v1.0/users/{user}", f"/v1.0/users('{user}')"):
                if path.casefold() == prefix.casefold() or path.casefold().startswith(
                    prefix.casefold() + "/"
                ):
                    return "/v1.0/me" + path[len(prefix) :]
        return path

    def _pinned(self, method: str, path: str, tool: str) -> bool:
        if tool == PREFLIGHT:
            return method == "GET" and path in _PREFLIGHT_PATHS
        if path == "/v1.0/me" or path.startswith("/v1.0/me/"):
            return True
        if path == "/v1.0/search/query":
            return method == "POST" and tool in SEARCH_TOOLS
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

    def saw(self, request: httpx.Request, status: int, location: str | None, body: object) -> None:
        self.redirect = location if 300 <= status < 400 else None
        if request.method in _WRITE_METHODS and status in _FAILED:
            self.write_failed = True
        self.seen_seed.update(seed_ids(body))
