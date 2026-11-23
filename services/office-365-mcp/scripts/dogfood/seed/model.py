import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit


class SeedError(Exception):
    code = 1


class ConfigError(SeedError):
    code = 2


@dataclass(frozen=True)
class Step:
    phase: str
    kind: str  # "lookup", "create" or "upload" (createUploadSession, then PUT of `payload`)
    method: str
    path: str  # "{key}" placeholders name ids found or created earlier in the run
    params: tuple[tuple[str, str], ...] = ()
    body: Any = None  # dict (JSON) or bytes (file upload)
    content_type: str | None = None
    key: str | None = None
    lookup: str | None = None  # how a step finds an id, stored under `key`: "tagged", "named",
    # "subject", "drive-folder", "drive-children", "single", "site", "columns", "attachments", "replies"
    poll: bool = False  # the answer is 202: wait for the operation in its Location header
    learns: str | None = (
        None  # "team", "drive", "site" or "chat": the id of the found or created item joins the guard
    )
    payload: bytes | None = None  # the bytes that an "upload" step sends to the uploadUrl in chunks
    generated: tuple[str, int, str] | None = None  # (generator, size, label) of docgen.generate


def site_id(drive: Mapping[str, Any]) -> str | None:
    """The Graph site id (host,SPSite id,SPWeb id) from a drive's SharePoint ids."""
    ids = drive.get("sharePointIds") or drive.get("sharepointIds")
    if not ids or not all(ids.get(key) for key in ("siteUrl", "siteId", "webId")):
        return None
    return f"{urlsplit(ids['siteUrl']).hostname},{ids['siteId']},{ids['webId']}"


@dataclass(frozen=True)
class Context:
    corpus: dict[str, Any]
    upns: tuple[str, str, str]
    anchor: dt.date
    mail_mode: str
    extras: Mapping[str, str] = field(default_factory=dict[str, str])

    def extra(self, name: str) -> str:
        if name not in self.extras:
            raise ConfigError(f"set {name} to the address that the seed may use")
        return self.extras[name]

    def persona(self, index: int) -> str:
        for name, persona in self.corpus["personas"]["personas"].items():
            if persona["index"] == index:
                return name
        raise ConfigError(f"no persona has index {index}")

    def address(self, person: str) -> dict[str, dict[str, str]]:
        if person.startswith("env:"):
            return {"emailAddress": {"address": self.extra(person.removeprefix("env:"))}}
        personas = self.corpus["personas"]["personas"]
        if person in personas:
            persona = personas[person]
            return {
                "emailAddress": {
                    "name": persona["display_name"],
                    "address": self.upns[persona["index"] - 1],
                }
            }
        return {"emailAddress": {"address": person}}

    def display_name(self, person: str) -> str:
        return self.corpus["personas"]["personas"].get(person, {}).get("display_name", person)
