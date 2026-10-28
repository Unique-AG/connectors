"""A stand-in for Microsoft Graph and SharePoint, for the recorder's offline tests. It answers like
the seeded test tenant: Mia's seed mail and files come from the seed corpus and the seed's own
document generator. Next to them it serves foreign data that is not synthetic: real-looking
senders, subjects and phone numbers, a tenant GUID and a UPN in a safelink, another user's file,
and noisy headers. The tests prove that none of it reaches a cassette."""

import importlib.util
import json
import re
import uuid
from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import cast
from urllib.parse import quote

import yaml
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from tests.e2e.recording.scrub import SEED
from tests.e2e.test_scenarios import Json, mapping

DOMAIN = "northwind-lab.onmicrosoft.com"
VANITY_DOMAIN = "northwind-lab.ch"
TENANT_ID = "6c2a9f4e-3b71-4d8a-a5e2-91f0c7d3b8a6"
TENANT_NAME = "Northwind Lab"
UPNS = (f"tester3@{DOMAIN}", f"tester1@{DOMAIN}", f"tester2@{DOMAIN}")
UPN = UPNS[0]
USER_ID = "d41f7b23-8e6a-4c19-b0d5-3a7e2f9c1b64"
USER_NAME = "Tester Three"
TOKEN = "eyJ0eXAiOiJKV1QifQ.eyJ1cG4iOiJzdGFuZC1pbiJ9.c3RhbmQtaW4tdG9rZW4"
SITE_ID = "a87c3e15-6d29-4b0f-9e47-c2d18f5b6a30"
LIST_ID = "f02b6d94-71ce-4e3a-8b55-3d9a0e1c7f28"
FILE_UNIQUE_ID = "5e8d1c3a-94b7-4f20-a6e1-7c2b9d0f4a85"
MY_HOST = "northwindlab-my.sharepoint.com"
ONEDRIVE_PATH = "/personal/tester3_northwind-lab_onmicrosoft_com"
GRAPH = "https://graph.microsoft.com/v1.0"
TEMPAUTH = "v1.eyJhdWQiOiIwMDAwMDAwMy0wMDAwLTBmZjEtY2UwMC0wMDAwMDAwMDAwMDAifQ.c2lnbmF0dXJl"
DRIVE_ID = "b!" + urlsafe_b64encode(
    uuid.UUID(SITE_ID).bytes_le + uuid.UUID(TENANT_ID).bytes_le + uuid.UUID(LIST_ID).bytes_le
).decode().rstrip("=")
OTHER_DRIVE_ID = "b!" + urlsafe_b64encode(uuid.UUID(LIST_ID).bytes * 2).decode().rstrip("=")
ITEM_ID = "01KQ3ZBXW7HN5RMDPJ4FGTL2YVCE6UOA3S"
FOLDER_ITEM_ID = "01KQ3ZBXV6Y2GOVW7725BZO354PWSELRRZ"
JSON_TYPE = "application/json;odata.metadata=minimal;odata.streaming=true;charset=utf-8"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
NOISY_HEADERS = {
    "request-id": "c3f0a1d2-58b4-4e7c-9a26-0d1e8f3b5c47",
    "client-request-id": "c3f0a1d2-58b4-4e7c-9a26-0d1e8f3b5c47",
    "x-ms-ags-diagnostic": '{"ServerInfo":{"RoleInstance":"AM2PEPF0001A7C3"}}',
    "set-cookie": "fpc=AkXq8v2HbF9Mj3s; path=/; secure",
    "sprequestguid": "8a4f2c61-3e9b-4d07-b5a8-1f6c0e2d9b73",
}
SAFELINK = (
    "https://eur02.safelinks.protection.outlook.com/?url=https%3A%2F%2Fteams.microsoft.com&data=05"
    + f"%7C02%7C{quote(UPN, safe='')}%7C{TENANT_ID}%7C0"
)
FOREIGN_MAIL = (
    (
        "Jonas Huber",
        "jonas.huber@brightway-partners.ch",
        "Contract renewal Northwind Lab",
        False,
        1,
        "06:40",
    )
    + (f"Hi, the draft is here: {SAFELINK} Jonas Huber | Brightway Partners | +41 44 555 01 23",),
    ("Lena Graf", f"lena.graf@{VANITY_DOMAIN}", "Parking spaces from Monday", False, 1, "06:10")
    + ("The garage is closed until Friday. Lena Graf, Facilities",),
    (
        "Microsoft 365 Message center",
        "o365mc@microsoft.com",
        "Weekly digest: service updates",
        True,
        3,
        "05:00",
    )
    + ("Major update: new admin center for Northwind Lab.",),
)
PAGE = 4


def _seed() -> tuple[Json, Json, Json]:
    corpus = SEED / "corpus"
    return cast(
        "tuple[Json, Json, Json]",
        tuple(
            yaml.safe_load((corpus / f"{name}.yaml").read_text())
            for name in ("personas", "mail", "files")
        ),
    )


def _docgen() -> Callable[[list[str], dict[str, str]], bytes]:
    spec = importlib.util.spec_from_file_location("seed_docgen", SEED / "docgen.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("the seed document generator is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast("Callable[[list[str], dict[str, str]], bytes]", module.docx)


def exchange_id(kind: bytes, n: int) -> str:
    return urlsafe_b64encode(kind + USER_ID.encode() + b"\x00\x46" + n.to_bytes(9, "big")).decode()


def folder_id(name: str) -> str:
    return exchange_id(b"\x01\x03\x24\x00", sum(name.encode()))


def _at(spec: str, today: date) -> str:
    days, hour, minute = (int(g) for g in cast("list[str]", re.findall(r"\d+", spec)))
    moment = datetime.combine(today - timedelta(days=days), datetime.min.time(), UTC)
    return (moment + timedelta(hours=hour, minutes=minute)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _preview(text: str) -> str:
    return " ".join(re.sub(r"<[^>]*>", " ", text).split())[:255]


def _person(name: str, address: str) -> dict[str, object]:
    return {"emailAddress": {"address": address, "name": name}}


def _message(n: int, subject: str | None, sender: Json, preview: str, at: str) -> dict[str, object]:
    made = exchange_id(b"\x00\x03\x24\x00", n)
    return {
        "@odata.etag": 'W/"CQAAABYAAAC'
        + urlsafe_b64encode(uuid.UUID(USER_ID).bytes).decode()
        + '"',
        "id": made,
        "subject": subject,
        "bodyPreview": preview,
        "from": sender,
        "sender": sender,
        "toRecipients": [_person("Mia Keller", UPN)],
        "replyTo": [],
        "receivedDateTime": at,
        "hasAttachments": False,
        "parentFolderId": folder_id("inbox"),
        "webLink": f"https://outlook.office365.com/owa/?ItemID={quote(made, safe='')}&exvsurl=1",
        "importance": "normal",
        "flag": {"flagStatus": "notFlagged"},
        "categories": [],
        "isDraft": False,
    }


def inbox(today: date) -> list[dict[str, object]]:
    personas, mail, _ = _seed()
    people = {
        key: _person(str(one["display_name"]), UPNS[cast("int", one["index"]) - 1])
        for key, one in cast("Mapping[str, Json]", personas["personas"]).items()
    }
    found: list[dict[str, object]] = []
    for n, spec in enumerate(cast("list[Json]", mail["messages"]), 1):
        if spec.get("owner", "mia") != "mia" or spec["folder"] != "inbox":
            continue
        body = cast("Json", spec["body"])
        made = _message(
            n,
            cast("str | None", spec.get("subject")),
            people[str(spec["from"])],
            _preview(str(body["content"])),
            _at(str(spec["received"]), today),
        )
        made |= {
            "isRead": bool(spec.get("read")),
            "hasAttachments": bool(spec.get("attachments")),
            "importance": spec.get("importance", "normal"),
            "flag": {"flagStatus": spec.get("flag", "notFlagged")},
            "categories": ["seed-v1", *cast("list[str]", spec.get("categories", []))],
        }
        found.append(made)
    for n, (name, address, subject, read, days, clock, preview) in enumerate(FOREIGN_MAIL, 900):
        foreign = _message(
            n, subject, _person(name, address), preview, _at(f"-{days}d {clock}", today)
        )
        found.append(foreign | {"isRead": read})
    return sorted(found, key=lambda one: str(one["receivedDateTime"]), reverse=True)


def plan_document() -> bytes:
    personas, _, files = _seed()
    names = {
        key: str(one["display_name"])
        for key, one in cast("Mapping[str, Json]", personas["personas"]).items()
    }
    spec = next(one for one in cast("list[Json]", files["files"]) if one["id"] == "f01")
    properties = cast("Mapping[str, str]", spec["properties"])
    shown = {
        k: names.get(v, v) if k in {"creator", "last_modified_by"} else v
        for k, v in properties.items()
    }
    return _docgen()(cast("list[str]", spec["paragraphs"]), shown)


def _created_by(name: str, address: str, user_id: str) -> dict[str, object]:
    return {"user": {"displayName": name, "email": address, "id": user_id}}


def drive_item(*, drift: bool) -> dict[str, object]:
    return {
        "@odata.context": f"{GRAPH}/$metadata#drives('{quote(DRIVE_ID)}')/items/$entity",
        "@microsoft.graph.downloadUrl": f"https://{MY_HOST}{ONEDRIVE_PATH}/_layouts/15/download.aspx?tempauth={TEMPAUTH}",
        "id": ITEM_ID,
        "name": "seed-v1 Project Plan.docx",
        "size": "1902" if drift else len(plan_document()),
        "eTag": f'"{{{FILE_UNIQUE_ID.upper()}}},3"',
        "cTag": f'"c:{{{FILE_UNIQUE_ID.upper()}}},3"',
        "webUrl": f"https://{MY_HOST}{ONEDRIVE_PATH}/Documents/seed-v1%20Seed%20Files/seed-v1%20Project%20Plan.docx",
        "createdDateTime": "2026-09-01T08:00:00Z",
        "lastModifiedDateTime": "2026-10-01T16:00:00Z",
        "createdBy": _created_by(USER_NAME, UPN, USER_ID),
        "lastModifiedBy": _created_by(USER_NAME, UPN, USER_ID),
        "file": {"mimeType": DOCX_TYPE, "hashes": {"quickXorHash": "pR3m0n0p0lyH4sh="}},
        "parentReference": {
            "driveId": DRIVE_ID,
            "driveType": "business",
            "id": FOLDER_ITEM_ID,
            "path": f"/drives/{DRIVE_ID}/root:/seed-v1 Seed Files",
            "siteId": f"{MY_HOST},{SITE_ID},{LIST_ID}",
        },
    }


def _foreign_item() -> dict[str, object]:
    return {
        "id": "01ZQ7W3RNB4XKPL2M5TYEJ6DCVHF8GUOA2",
        "name": "Northwind Board Minutes Q3.docx",
        "webUrl": "https://northwindlab.sharepoint.com/sites/Board/Shared%20Documents/Northwind%20Board%20Minutes%20Q3.docx",
        "size": 48211,
        "lastModifiedDateTime": "2026-10-02T09:00:00Z",
        "createdBy": _created_by(
            "Lena Graf", f"lena.graf@{VANITY_DOMAIN}", "9b3e5d71-2f4c-4a86-8d1e-6c0b7a2f5e93"
        ),
        "file": {"mimeType": DOCX_TYPE},
        "parentReference": {
            "driveId": OTHER_DRIVE_ID,
            "id": "01ZQ7W3RNA3BOARDMINUTESFOLDER0001",
            "siteId": f"northwindlab.sharepoint.com,{LIST_ID},{SITE_ID}",
        },
    }


@dataclass
class StandIn:
    variants: frozenset[str] = frozenset()
    token: str = field(default=TOKEN, repr=False)
    today: date = field(default_factory=lambda: datetime.now(UTC).date())
    seen: list[str] = field(default_factory=list[str])
    failed_once: bool = False

    def app(self) -> Starlette:
        return Starlette(
            routes=[Route("/{path:path}", self._answer, methods=["GET", "POST", "PATCH"])]
        )

    async def _answer(self, request: Request) -> Response:
        host, path = request.url.hostname, request.url.path
        self.seen.append(f"{request.method} {host}{path}")
        if host == MY_HOST:
            return self._download(request)
        if request.headers.get("authorization") != f"Bearer {self.token}":
            return _error(401, "InvalidAuthenticationToken", "Access token is empty.")
        if "retry" in self.variants and path.endswith("/inbox") and not self.failed_once:
            self.failed_once = True
            return _error(503, "serviceNotAvailable", "Try again.", {"retry-after": "0"})
        body = await request.body()
        answer = self._graph(request.method, path.removeprefix("/v1.0"), request, body)
        if isinstance(answer, Response):
            return answer
        return JSONResponse(answer, headers=NOISY_HEADERS, media_type=JSON_TYPE)

    def _graph(
        self, method: str, path: str, request: Request, body: bytes
    ) -> dict[str, object] | Response:
        match method, path.split("/")[1:]:
            case "GET", ["me"]:
                return {
                    "id": USER_ID,
                    "userPrincipalName": UPN,
                    "mail": UPN,
                    "displayName": USER_NAME,
                }
            case "GET", ["organization"]:
                domains = [{"name": DOMAIN}, {"name": VANITY_DOMAIN}]
                return {
                    "value": [
                        {"id": TENANT_ID, "displayName": TENANT_NAME, "verifiedDomains": domains}
                    ]
                }
            case "GET", ["me", "drive"]:
                return {"id": DRIVE_ID, "driveType": "business"}
            case "GET", ["me", "mailFolders", "inbox"]:
                return {
                    "@odata.context": f"{GRAPH}/$metadata#users('{USER_ID}')/mailFolders/$entity",
                    "id": folder_id("inbox"),
                    "displayName": "Inbox",
                    "totalItemCount": "29" if "drift" in self.variants else len(inbox(self.today)),
                    "unreadItemCount": sum(not m["isRead"] for m in inbox(self.today)),
                }
            case "GET", ["me", "mailFolders", "inbox", "messages"]:
                return self._messages(request)
            case "POST", ["me", "messages", moved, "move"]:
                return self._move(moved, request)
            case "POST", ["search", "query"]:
                return self._search(mapping(cast("object", json.loads(body))))
            case "GET", ["drives", drive, "items", item] if (drive, item) == (DRIVE_ID, ITEM_ID):
                return drive_item(drift="drift" in self.variants)
            case "GET", ["drives", drive, "items", item, "content"] if (drive, item) == (
                DRIVE_ID,
                ITEM_ID,
            ):
                location = (
                    f"https://{MY_HOST}{ONEDRIVE_PATH}/_layouts/15/download.aspx?UniqueId="
                    + f"{FILE_UNIQUE_ID}&Translate=false&tempauth={TEMPAUTH}&ApiVersion=2.0"
                )
                return Response(status_code=302, headers=NOISY_HEADERS | {"location": location})
            case _:
                pass
        return _error(404, "itemNotFound", f"No stand-in answer for {method} {path} of {UPN}")

    def _messages(self, request: Request) -> dict[str, object]:
        query = request.query_params
        rows = inbox(self.today)
        if "token-leak" in self.variants:
            rows = [rows[-1] | {"subject": f"Bearer {self.token}"}, *rows[:-1]]
        if "isRead eq false" in query.get("$filter", ""):
            rows = [row for row in rows if not row["isRead"]]
        if (after := re.search(r"receivedDateTime ge (\S+)", query.get("$filter", ""))) is not None:
            rows = [row for row in rows if str(row["receivedDateTime"]) >= after[1]]
        skip = 0
        if "$skiptoken" in query:
            skip = int(
                str(
                    mapping(cast("object", json.loads(urlsafe_b64decode(query["$skiptoken"]))))["o"]
                )
            )
        size = min(int(query.get("$top", "10")), PAGE)
        answer: dict[str, object] = {
            "@odata.context": f"{GRAPH}/$metadata#users('{quote(UPN)}')/messages",
            "value": rows[skip : skip + size],
        }
        if skip + size < len(rows):
            token = urlsafe_b64encode(
                json.dumps({"m": USER_ID, "o": skip + size}).encode()
            ).decode()
            following = {key: value for key, value in query.items() if key != "$skiptoken"}
            answer["@odata.nextLink"] = f"{GRAPH}/me/mailFolders/inbox/messages?" + "&".join(
                f"{quote(k)}={quote(v)}" for k, v in {**following, "$skiptoken": token}.items()
            )
        return answer

    def _move(self, moved: str, request: Request) -> Response:
        if "echo" in self.variants:
            echoed = f"Access denied for {UPN} with {request.headers.get('authorization')}"
            return _error(403, "ErrorAccessDenied", echoed)
        original = next((row for row in inbox(self.today) if row["id"] == moved), None)
        if original is None:
            return _error(
                404, "ErrorItemNotFound", "The specified object was not found in the store."
            )
        noisy = {
            "id": exchange_id(b"\x00\x05\x24\x00", sum(moved.encode())),
            "parentFolderId": folder_id("archive"),
            "changeKey": "CQAAABYAAAC" + urlsafe_b64encode(uuid.UUID(USER_ID).bytes).decode(),
            "internetMessageId": f"<CAF8x7q2Lm9vR3pQ5tW1@{VANITY_DOMAIN}>",
            "internetMessageHeaders": [
                {"name": "X-MS-Exchange-CrossTenant-Id", "value": TENANT_ID}
            ],
            "body": {
                "contentType": "html",
                "content": f'<p>Hi</p><a href="mailto:{UPN}">{TENANT_NAME}</a>',
            },
        }
        return JSONResponse(
            original | noisy, status_code=201, headers=NOISY_HEADERS, media_type=JSON_TYPE
        )

    def _search(self, asked: Json) -> dict[str, object]:
        terms = str(cast("Json", cast("list[Json]", asked["requests"])[0]["query"])["queryString"])
        mine = {"@odata.type": "#microsoft.graph.driveItem"} | drive_item(drift=False)
        hits = [
            {
                "hitId": ITEM_ID,
                "rank": 1,
                "summary": "<c0>Project</c0> <c0>Plan</c0><ddd/>",
                "resource": mine,
            },
            {
                "hitId": "01ZQ7W3RNB4XKPL2M5TYEJ6DCVHF8GUOA2",
                "rank": 2,
                "summary": "Minutes of the board, Lena Graf",
                "resource": {"@odata.type": "#microsoft.graph.driveItem"} | _foreign_item(),
            },
        ]
        hits = [] if "unindexed" in self.variants else hits
        container = {"hits": hits, "total": len(hits), "moreResultsAvailable": False}
        return {"value": [{"searchTerms": terms.lower().split(), "hitsContainers": [container]}]}

    def _download(self, request: Request) -> Response:
        if request.query_params.get("tempauth") != TEMPAUTH or "authorization" in request.headers:
            return Response(status_code=401)
        disposition = {"content-disposition": 'attachment; filename="seed-v1 Project Plan.docx"'}
        return Response(plan_document(), media_type=DOCX_TYPE, headers=NOISY_HEADERS | disposition)


def _error(
    status: int, code: str, message: str, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    inner = {"date": "2026-10-23T08:00:00", "request-id": NOISY_HEADERS["request-id"]}
    return JSONResponse(
        {"error": {"code": code, "message": message, "innerError": inner}},
        status_code=status,
        headers={**NOISY_HEADERS, **(headers or {})},
    )
