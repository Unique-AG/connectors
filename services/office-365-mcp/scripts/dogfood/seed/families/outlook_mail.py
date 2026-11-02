import os
from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, Any

from model import Context, Step

if TYPE_CHECKING:
    from seed import Graph

CASE = "seed-v1 case-"
PHASES: tuple[str, ...] = ()
MESSAGE_FOLDERS = ("inbox", "sentitems", "drafts", "deleteditems")
MESSAGE_FIELDS = {"$select": "id,subject,categories,from", "$top": "100"}
NAME_FIELDS = {"$select": "id,displayName", "$top": "100"}


def steps(ctx: Context, owner: str, phases: set[str]) -> list[Step]:
    return []


def _holds_case(*texts: Any) -> bool:
    return any(isinstance(text, str) and text.startswith(CASE) for text in texts)


def _personas() -> frozenset[str]:
    raw = os.environ.get("SEED_UPNS", "")
    return frozenset(one.strip().casefold() for one in raw.split(",") if one.strip())


def _sender(message: Mapping[str, Any]) -> str:
    address = ((message.get("from") or {}).get("emailAddress") or {}).get("address")
    return str(address or "").casefold()


def _named(graph: Graph, path: str, params: Mapping[str, str]) -> list[str]:
    return [
        str(item["id"])
        for item in graph.get_all(path, params)
        if _holds_case(item.get("displayName"))
    ]


def sweep(graph: Graph, owner: str) -> Iterator[tuple[str, str]]:
    personas = _personas()
    for folder in MESSAGE_FOLDERS:
        path = f"/me/mailFolders/{folder}/messages"
        for message in list(graph.get_all(path, MESSAGE_FIELDS)):
            ours = _sender(message) in {"", *personas}
            if ours and _holds_case(message.get("subject"), *(message.get("categories") or [])):
                yield "DELETE", f"/me/messages/{message['id']}"
    for path in ("/me/mailFolders", "/me/mailFolders/deleteditems/childFolders"):
        for found in _named(graph, path, NAME_FIELDS):
            yield "POST", f"/me/mailFolders/{found}/permanentDelete"
    for found in _named(graph, "/me/mailFolders/inbox/messageRules", NAME_FIELDS):
        yield "DELETE", f"/me/mailFolders/inbox/messageRules/{found}"
    for found in _named(graph, "/me/outlook/masterCategories", {}):
        yield "DELETE", f"/me/outlook/masterCategories/{found}"
    for override in list(graph.get_all("/me/inferenceClassification/overrides", {})):
        address = str((override.get("senderEmailAddress") or {}).get("address", ""))
        if address.casefold() in personas:
            yield "DELETE", f"/me/inferenceClassification/overrides/{override['id']}"
