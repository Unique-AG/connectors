import base64
import datetime as dt
import os
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import docgen
import yaml
from model import ConfigError, Context, Step

if TYPE_CHECKING:
    from seed import Graph

TAG = "seed-v1"
CASE = f"{TAG} case-"
PHASES: tuple[str, ...] = ("mail-attach", "mail-people", "mail-prefs")
SPEC: Mapping[str, Any] = yaml.safe_load(
    (Path(__file__).resolve().parents[1] / "corpus" / "mail-extra.yaml").read_text(encoding="utf-8")
)
KEY_PROP = "String {8c0e3b2a-6f1d-4d6e-9a57-2f3c5b7e9d10} Name SeedKey"
KEY_EXPAND = f"singleValueExtendedProperties($filter=id eq '{KEY_PROP}')"
TAG_FILTER = f"categories/any(c:c eq '{TAG}')"
INLINE_MAX = 3 * 1024 * 1024
SEND_PREFIX = "Seed "
REPLY_PREFIX = "Automatic reply: "
MESSAGE_FOLDERS = ("inbox", "sentitems", "drafts", "deleteditems", "archive", "junkemail")
MESSAGE_FIELDS = {"$select": "id,subject,categories,from", "$top": "100"}
NAME_FIELDS = {"$select": "id,displayName", "$top": "100"}
TAGGED = {
    "$filter": TAG_FILTER,
    "$select": "id,categories,subject",
    "$expand": KEY_EXPAND,
    "$top": "100",
}

type Spec = Mapping[str, Any]


def _received(spec: str, anchor: dt.date) -> str:
    found = re.fullmatch(r"-(\d+)d (\d{2}):(\d{2})", spec)
    if not found:
        raise ConfigError(f"bad received value {spec!r}, expected '-<days>d HH:MM'")
    day = anchor - dt.timedelta(days=int(found[1]))
    return f"{day.isoformat()}T{found[2]}:{found[3]}:00Z"


def _owned(items: list[Spec], owner: str, field: str = "owner") -> list[Spec]:
    return [one for one in items if one.get(field, "mia") == owner]


def _bytes(spec: Spec, ctx: Context) -> bytes:
    if spec["kind"] != "xlsx":
        return docgen.generate(spec["kind"], spec["size"], spec["label"])
    named = ("creator", "last_modified_by")
    props = {k: ctx.display_name(v) if k in named else v for k, v in spec["properties"].items()}
    return docgen.xlsx(spec["rows"], props)


def _is_large(spec: Spec) -> bool:
    return spec["kind"] in docgen.GENERATORS and spec["size"] > INLINE_MAX


def _message(ctx: Context, message: Spec, attachments: list[Spec]) -> dict[str, Any]:
    body: dict[str, Any] = {
        "subject": message["subject"],
        "body": {"contentType": message["body"]["type"], "content": message["body"]["content"]},
        "toRecipients": [ctx.address(person) for person in message["to"]],
        "categories": [TAG],
    }
    props = [{"id": KEY_PROP, "value": f"{TAG}:mail:{message['id']}"}]
    if ctx.mail_mode != "draft":
        moment = _received(message["received"], ctx.anchor)
        body |= {
            "from": ctx.address(message["from"]),
            "sender": ctx.address(message["from"]),
            "isRead": bool(message.get("read")),
        }
        props += [
            {"id": "Integer 0x0E07", "value": "1" if message.get("read") else "0"},
            {"id": "SystemTime 0x0E06", "value": moment},
            {"id": "SystemTime 0x0039", "value": moment},
        ]
    body["singleValueExtendedProperties"] = props
    inline = [one for one in attachments if not _is_large(one)]
    if inline:
        body["attachments"] = [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": one["name"],
                "contentType": one["content_type"],
                "contentBytes": base64.b64encode(_bytes(one, ctx)).decode("ascii"),
            }
            for one in inline
        ]
    return body


def _attachments(ctx: Context, owner: str) -> list[Step]:
    messages = _owned(SPEC["messages"], owner)
    if not messages:
        return []
    files = {one["id"]: one for one in SPEC["attachments"]}
    steps = [
        Step("mail-attach", "lookup", "GET", "/me/messages", tuple(TAGGED.items()), lookup="tagged")
    ]
    for message in messages:
        attached = [files[ref] for ref in message["attachments"]]
        found = f"mail:{message['id']}"
        folder = f"/me/mailFolders/{message['folder']}/messages"
        steps.append(
            Step(
                "mail-attach",
                "create",
                "POST",
                folder,
                body=_message(ctx, message, attached),
                key=found,
            )
        )
        for one in filter(_is_large, attached):
            parent = f"/me/messages/{{{found}}}/attachments"
            item = {
                "attachmentType": "file",
                "name": one["name"],
                "size": one["size"],
                "contentType": one["content_type"],
            }
            steps += [
                Step(
                    "mail-attach",
                    "lookup",
                    "GET",
                    parent,
                    (("$select", "id,name"),),
                    key=message["id"],
                    lookup="attachments",
                ),
                Step(
                    "mail-attach",
                    "upload",
                    "POST",
                    f"{parent}/createUploadSession",
                    body={"AttachmentItem": item},
                    key=f"attachment:{message['id']}:{one['name']}",
                    payload=_bytes(one, ctx),
                    generated=(one["kind"], one["size"], one["label"]),
                ),
            ]
    return steps


def _sends(ctx: Context, owner: str) -> list[Step]:
    sends = _owned(SPEC["sends"], owner, "from")
    if not sends:
        return []
    params = (
        ("$filter", f"startswith(subject,'{SEND_PREFIX}')"),
        ("$select", "id,subject"),
        ("$top", "100"),
    )
    found = [
        Step(
            "mail-people",
            "lookup",
            "GET",
            "/me/mailFolders/sentitems/messages",
            params,
            lookup="subject",
        )
    ]
    for send in sends:
        message = {
            "subject": send["subject"],
            "body": {"contentType": "text", "content": send["body"]},
            "toRecipients": [ctx.address(person) for person in send["to"]],
        }
        body = {"message": message, "saveToSentItems": True}
        key = f"subject:{send['subject']}"
        found.append(Step("mail-people", "create", "POST", "/me/sendMail", body=body, key=key))
    return found


def _reply_window(ctx: Context) -> dict[str, dict[str, str]]:
    reply = SPEC["reply"]

    def moment(days: int) -> dict[str, str]:
        return {"dateTime": f"{ctx.anchor + dt.timedelta(days=days)}T00:00:00", "timeZone": "UTC"}

    return {
        "scheduledStartDateTime": moment(reply["from_day"]),
        "scheduledEndDateTime": moment(reply["until_day"]),
    }


def _reply(ctx: Context, owner: str) -> list[Step]:
    reply = SPEC["reply"]
    if reply["owner"] != owner:
        return []
    setting = {
        "status": "scheduled",
        "externalAudience": reply["audience"],
        "internalReplyMessage": reply["internal"],
        **_reply_window(ctx),
    }
    body = {"automaticRepliesSetting": setting}
    return [
        Step("mail-prefs", "create", "PATCH", "/me/mailboxSettings", body=body, key="prefs:reply")
    ]


def steps(ctx: Context, owner: str, phases: set[str]) -> list[Step]:
    return [
        *(_attachments(ctx, owner) if "mail-attach" in phases else []),
        *(_sends(ctx, owner) if "mail-people" in phases else []),
        *(_reply(ctx, owner) if "mail-prefs" in phases else []),
    ]


def _holds_case(*texts: Any) -> bool:
    return any(isinstance(text, str) and text.startswith(CASE) for text in texts)


def _personas() -> frozenset[str]:
    raw = os.environ.get("SEED_UPNS", "")
    return frozenset(one.strip().casefold() for one in raw.split(",") if one.strip())


def _sender(message: Mapping[str, Any]) -> str:
    address = ((message.get("from") or {}).get("emailAddress") or {}).get("address")
    return str(address or "").casefold()


def _seed_key(item: Mapping[str, Any]) -> str | None:
    for prop in item.get("singleValueExtendedProperties") or []:
        value = str(prop.get("value", ""))
        if str(prop.get("id", "")).lower() == KEY_PROP.lower() and value.startswith(f"{TAG}:"):
            return value[len(TAG) + 1 :]
    return None


def cleanup(
    graph: Graph, ctx: Context, owner: str, phases: set[str]
) -> Iterator[tuple[str, str, Any]]:
    if "mail-attach" in phases:
        keys = {f"mail:{one['id']}" for one in _owned(SPEC["messages"], owner)}
        for item in list(graph.get_all("/me/messages", TAGGED)):
            if _seed_key(item) in keys:
                yield "POST", f"/me/messages/{item['id']}/permanentDelete", None
    if "mail-people" in phases:
        sent = [one["subject"] for one in SPEC["sends"]]
        subjects = {*sent, *(f"{REPLY_PREFIX}{subject}" for subject in sent)}
        for folder in ("sentitems", "inbox"):
            for item in list(graph.get_all(f"/me/mailFolders/{folder}/messages", MESSAGE_FIELDS)):
                if item.get("subject") in subjects and _sender(item) in _personas():
                    yield "POST", f"/me/messages/{item['id']}/permanentDelete", None
    if "mail-prefs" in phases and SPEC["reply"]["owner"] == owner:
        yield "PATCH", "/me/mailboxSettings", {"automaticRepliesSetting": {"status": "disabled"}}


def _named(graph: Graph, path: str, params: Mapping[str, str]) -> list[str]:
    return [
        str(item["id"])
        for item in graph.get_all(path, params)
        if _holds_case(item.get("displayName"))
    ]


def _seed_folders(graph: Graph) -> list[str]:
    found: list[str] = []
    queue = ["/me/mailFolders"]
    while queue:
        for folder in graph.get_all(queue.pop(0), NAME_FIELDS):
            if str(folder.get("displayName", "")).startswith(f"{TAG} "):
                found.append(str(folder["id"]))
                queue.append(f"/me/mailFolders/{folder['id']}/childFolders")
    return found


def _left_on(graph: Graph) -> bool:
    answer = graph.request(
        "GET", "/me/mailboxSettings", params={"$select": "automaticRepliesSetting"}
    ).json()
    setting = answer.get("automaticRepliesSetting") or {}
    texts = (setting.get("internalReplyMessage"), setting.get("externalReplyMessage"))
    return setting.get("status") != "disabled" and any(CASE in str(one) for one in texts)


def sweep(graph: Graph, owner: str) -> Iterator[tuple[str, str] | tuple[str, str, Any]]:
    personas = _personas()
    delivered = set(SPEC["delivered"])
    folders = [f"/me/mailFolders/{name}" for name in MESSAGE_FOLDERS]
    folders += [f"/me/mailFolders/{found}" for found in _seed_folders(graph)]
    for folder in folders:
        for message in list(graph.get_all(f"{folder}/messages", MESSAGE_FIELDS)):
            ours = _sender(message) in {"", *personas}
            case = _holds_case(message.get("subject"), *(message.get("categories") or []))
            copy = folder.endswith("/inbox") and message.get("subject") in delivered
            if ours and (case or copy):
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
    if _left_on(graph):
        yield "PATCH", "/me/mailboxSettings", {"automaticRepliesSetting": {"status": "disabled"}}
