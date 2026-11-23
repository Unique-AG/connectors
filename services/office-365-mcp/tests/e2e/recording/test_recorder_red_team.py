"""The plants of a red team review (2026-10-23), kept as a regression suite. Each plant puts a
real-looking identifier into a raw answer, as Graph would send it. A plant is through when the
scrub does not refuse and its witness bytes reach a written file (zip members and gzip included).
Every plant must stay out."""

import base64
import gzip
import io
import json
import uuid
import zipfile
import zlib
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import cast

import pytest

from tests.e2e.recording import stand_in
from tests.e2e.recording.conftest import Recorded
from tests.e2e.recording.guard import Refused
from tests.e2e.recording.lint import lint_files
from tests.e2e.recording.scrub import Hop, files_of, scrub
from tests.e2e.test_scenarios import Json, items, mapping

type Mutate = Callable[[Hop], Hop]

TID, UID, UPN = stand_in.TENANT_ID, stand_in.USER_ID, stand_in.UPN
VANITY, NAME, DOMAIN = stand_in.VANITY_DOMAIN, stand_in.TENANT_NAME, stand_in.DOMAIN
REAL = "jonas.huber@brightway-partners.ch"
MAIL, ITEM, LOCATION, DOWNLOAD = ("uc-02-01", 1), ("uc-01-06", 1), ("uc-01-06", 2), ("uc-01-06", 3)


def b64(value: str | bytes) -> str:
    return base64.b64encode(value.encode() if isinstance(value, str) else value).decode()


def _edited(hop: Hop, edit: Callable[[Json], Json]) -> Hop:
    parsed = mapping(cast("object", json.loads(hop.body)))
    return replace(hop, body=json.dumps(edit(parsed), ensure_ascii=False).encode())


def preview(text: str) -> Mutate:
    def edit(page: Json) -> Json:
        rows = [mapping(row) for row in items(page["value"])]
        return {**page, "value": [{**rows[0], "bodyPreview": text}, *rows[1:]]}

    return lambda hop: _edited(hop, edit)


def raw_preview(raw: bytes) -> Mutate:
    def mutate(hop: Hop) -> Hop:
        marked = preview("PLANT-MARK")(hop)
        return replace(hop, body=marked.body.replace(b'"PLANT-MARK"', b'"' + raw + b'"'))

    return mutate


def at(key: str, value: object) -> Mutate:
    return lambda hop: _edited(hop, lambda found: {**found, key: value})


def header(name: str, value: str) -> Mutate:
    def mutate(hop: Hop) -> Hop:
        kept = tuple((k, v) for k, v in hop.headers if k.lower() != name)
        return replace(hop, headers=(*kept, (name, value)))

    return mutate


def docx_with(extra: Mapping[str, bytes]) -> Mutate:
    def mutate(hop: Hop) -> Hop:
        source = zipfile.ZipFile(io.BytesIO(hop.body))
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            for member in source.namelist():
                if member not in extra:
                    archive.writestr(member, source.read(member))
            for member, data in extra.items():
                archive.writestr(member, data)
        return replace(hop, body=out.getvalue())

    return mutate


def binary(media: str, body: bytes) -> Mutate:
    def mutate(hop: Hop) -> Hop:
        kept = tuple((k, v) for k, v in hop.headers if k.lower() != "content-type")
        return replace(hop, headers=(*kept, ("content-type", media)), body=body)

    return mutate


def inner_docx() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("docProps/core.xml", f"<dc:creator>INNER {UPN} {TID} {NAME}</dc:creator>")
    return buffer.getvalue()


def entities(text: str) -> str:
    return "".join(f"&#{ord(c)};" for c in text)


def escapes(text: str) -> str:
    return "".join(f"\\\\u{ord(c):04x}" for c in text)


PLANTS: dict[str, tuple[tuple[str, int], Mutate, bytes]] = {
    "A1 GUID, 32 hex without dashes": (
        MAIL,
        preview(f"ref {TID.replace('-', '')}"),
        TID.replace("-", "").encode(),
    ),
    "A2 GUID in upper case": (MAIL, preview(f"ref {TID.upper()}"), TID.upper().encode()),
    "A3 GUID in braces": (MAIL, preview("ref {" + TID + "}"), TID.encode()),
    "A4 GUID in base32": (
        MAIL,
        preview("ref " + base64.b32encode(uuid.UUID(TID).bytes).decode()),
        base64.b32encode(uuid.UUID(TID).bytes),
    ),
    "A4b UPN in base32": (
        MAIL,
        preview("ref " + base64.b32encode(UPN.encode()).decode()),
        base64.b32encode(UPN.encode()),
    ),
    "A5 base64 of JSON with tid": (
        MAIL,
        preview("state=" + b64(json.dumps({"tid": TID}))),
        b64(json.dumps({"tid": TID})).encode(),
    ),
    "A5b base64, misaligned": (
        MAIL,
        preview("statex" + b64(json.dumps({"upn": UPN, "tid": TID}))),
        b64(json.dumps({"upn": UPN, "tid": TID})).encode(),
    ),
    "A5c base64 split in chunks": (
        MAIL,
        preview(" ".join(b64(UPN)[i : i + 12] for i in range(0, len(b64(UPN)), 12))),
        b64(UPN)[:12].encode(),
    ),
    "A5d base64 not JSON, misaligned r": (
        MAIL,
        preview("r" + b64(f"tid={TID};upn={UPN}")),
        b64(f"tid={TID};upn={UPN}").encode(),
    ),
    "A5d base64 not JSON, misaligned re": (
        MAIL,
        preview("re" + b64(f"tid={TID};upn={UPN}")),
        b64(f"tid={TID};upn={UPN}").encode(),
    ),
    "A5d base64 not JSON, misaligned ref": (
        MAIL,
        preview("ref" + b64(f"tid={TID};upn={UPN}")),
        b64(f"tid={TID};upn={UPN}").encode(),
    ),
    "A5e base64 not JSON, aligned": (
        MAIL,
        preview("ref " + b64(f"tid={TID};upn={UPN}")),
        b64(f"tid={TID};upn={UPN}").encode(),
    ),
    "A6 UPN as JSON escapes": (MAIL, raw_preview(escapes(UPN).encode()), escapes("@").encode()),
    "A6b GUID dashes as escapes": (
        MAIL,
        raw_preview(TID.replace("-", "\\\\u002d").encode()),
        TID[:8].encode(),
    ),
    "A7 UPN as HTML entities": (MAIL, preview(entities(UPN)), entities(UPN).encode()),
    "A7b third party with &#64;": (
        MAIL,
        preview(REAL.replace("@", "&#64;")),
        REAL.replace("@", "&#64;").encode(),
    ),
    "A7c tenant name with &nbsp;": (MAIL, preview("Northwind&nbsp;Lab"), b"Northwind&nbsp;Lab"),
    "A8 UPN in double base64": (MAIL, preview("t=" + b64(b64(UPN))), b64(b64(UPN)).encode()),
    "A9 UPN in upper case": (MAIL, preview(UPN.upper()), UPN.upper().encode()),
    "A10 UPN with a plus tag": (MAIL, preview(f"tester3+rec@{DOMAIN}"), b"+rec@"),
    "A10b persona local part, foreign domain": (
        MAIL,
        preview("anna.meier@evil-corp.ch"),
        b"evil-corp.ch",
    ),
    "A11 MIME B encoded word": (
        MAIL,
        preview("=?UTF-8?B?" + b64(f"Jonas <{REAL}>") + "?="),
        b64(f"Jonas <{REAL}>").encode(),
    ),
    "A11b MIME Q encoded word": (
        MAIL,
        preview("=?UTF-8?Q?" + REAL.replace("@", "=40") + "?="),
        REAL.replace("@", "=40").encode(),
    ),
    "A11c MIME B split words": (
        MAIL,
        preview(
            " ".join("=?UTF-8?B?" + b64(REAL[i : i + 9]) + "?=" for i in range(0, len(REAL), 9))
        ),
        ("=?UTF-8?B?" + b64(REAL[:9])).encode(),
    ),
    "A12 address folded in the domain": (
        MAIL,
        preview("jonas.huber@brightway-\r\n partners.ch"),
        b"jonas.huber@brightway-",
    ),
    "A12b address folded before the at": (
        MAIL,
        preview("jonas.huber\r\n @brightway-partners.ch"),
        b"@brightway-partners.ch",
    ),
    "A13 IDN look-alike tenant domain": (
        MAIL,
        preview("see xn--northwnd-lab-x8b.ch and northwіnd-lab.ch"),
        b"xn--northwnd",
    ),
    "A13b bare vanity domain": (MAIL, preview("visit " + VANITY), VANITY.encode()),
    "A14 tenant name in a longer word": (
        MAIL,
        preview("NorthwindLab intranet, Northwind-Lab"),
        b"NorthwindLab",
    ),
    "A14b tenant short name alone": (MAIL, preview("Northwind team"), b"Northwind team"),
    "A15 a real person in free text": (
        MAIL,
        preview("Hi Mia, Jonas Huber says hi"),
        b"Jonas Huber",
    ),
    "A16a docx document.xml name": (
        DOWNLOAD,
        docx_with({"word/document.xml": b"<w:t>Owner: Jonas Huber</w:t>"}),
        b"Jonas Huber",
    ),
    "A16b docx app.xml company": (
        DOWNLOAD,
        docx_with(
            {"docProps/app.xml": b"<Company>Northwind</Company><Manager>Jonas Huber</Manager>"}
        ),
        b"Jonas Huber",
    ),
    "A16c docx core lastModifiedBy": (
        DOWNLOAD,
        docx_with(
            {
                "docProps/core.xml": b"<dc:creator>Anna Meier</dc:creator>"
                + b"<cp:lastModifiedBy>Jonas Huber</cp:lastModifiedBy>"
            }
        ),
        b"Jonas Huber",
    ),
    "A16d docx comment author": (
        DOWNLOAD,
        docx_with({"word/comments.xml": b'<w:comment w:author="Jonas Huber"/>'}),
        b"Jonas Huber",
    ),
    "A16e docx customXml GUID": (
        DOWNLOAD,
        docx_with({"customXml/item1.xml": f"<x>{TID.replace('-', '')}</x>".encode()}),
        TID.replace("-", "").encode(),
    ),
    "A16f docx upper-case member": (
        DOWNLOAD,
        docx_with({"customXml/item2.XML": UPN.encode()}),
        UPN.encode(),
    ),
    "A16g docx member name": (
        DOWNLOAD,
        docx_with({f"customXml/{DOMAIN}.bin": b"x"}),
        DOMAIN.encode(),
    ),
    "A16h docx thumbnail EXIF": (
        DOWNLOAD,
        docx_with(
            {"docProps/thumbnail.jpeg": b"\xff\xd8\xff\xe1Exif\0\0" + UPN.encode("utf-16-le")}
        ),
        UPN.encode("utf-16-le"),
    ),
    "A16i docx inside a docx": (
        DOWNLOAD,
        docx_with({"word/embeddings/Doc1.docx": inner_docx()}),
        b"INNER",
    ),
    "A17 gzip body": (
        DOWNLOAD,
        binary("application/octet-stream", gzip.compress(f"{UPN} {TID} {NAME}".encode())),
        b"\x1f\x8b",
    ),
    "A18 JPEG with EXIF": (
        DOWNLOAD,
        binary(
            "image/jpeg",
            b"\xff\xd8\xff\xe1Exif\0\0Artist\0Jonas Huber\0" + REAL.encode("utf-16-le"),
        ),
        b"Jonas Huber",
    ),
    "A19 PDF author": (
        DOWNLOAD,
        binary(
            "application/pdf",
            b"%PDF-1.7\n1 0 obj<</Author(Jonas Huber)/Producer(" + UPN.encode() + b")>>endobj",
        ),
        b"Jonas Huber",
    ),
    "A19b PDF as octet-stream, deflated": (
        DOWNLOAD,
        binary(
            "application/octet-stream",
            b"%PDF-1.7\nstream\n" + zlib.compress(UPN.encode()) + b"\nendstream",
        ),
        b"%PDF",
    ),
    "B1 webUrl on a CDN host": (
        ITEM,
        at("webUrl", "https://northwindlab.webhook.office.com/x"),
        b"northwindlab.webhook",
    ),
    "B1b mail.onmicrosoft.com host": (
        ITEM,
        at("webUrl", "https://northwind-lab.mail.onmicrosoft.com/x"),
        b"northwind-lab",
    ),
    "B1c sovereign SharePoint host": (
        ITEM,
        at("webUrl", "https://northwindlab-my.sharepoint.de/personal/x"),
        b"northwindlab-my.sharepoint.de",
    ),
    "B1d SharePoint host, mixed case": (
        ITEM,
        at("webUrl", "https://NorthwindLab-my.SharePoint.com/x"),
        b"NorthwindLab",
    ),
    "B1e Graph URL, hex user id": (
        ITEM,
        at("webUrl", f"https://graph.microsoft.com/v1.0/users/{UID.replace('-', '')}"),
        UID.replace("-", "").encode(),
    ),
    "B1f Graph URL with the UPN": (
        ITEM,
        at("webUrl", f"https://graph.microsoft.com/v1.0/users/{UPN}/drive"),
        UPN.encode(),
    ),
    "B2 nextLink over http": (
        MAIL,
        at(
            "@odata.nextLink",
            "http://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages?$skiptoken="
            + b64(json.dumps({"m": UID})),
        ),
        b64(json.dumps({"m": UID}))[:20].encode(),
    ),
    "B2b nextLink, binary GUID skiptoken": (
        MAIL,
        at(
            "@odata.nextLink",
            "http://graph.microsoft.com/v1.0/me/messages?$skiptoken="
            + base64.urlsafe_b64encode(b"\x01\x00" + uuid.UUID(UID).bytes_le).decode(),
        ),
        base64.urlsafe_b64encode(b"\x01\x00" + uuid.UUID(UID).bytes_le)[:16],
    ),
    "B3a location with access_token": (
        LOCATION,
        header("location", "https://contoso.sharepoint.com/dl?access_token=EwBoA8l6BAAU7p9QDpi"),
        b"EwBoA8l6BAAU7p9QDpi",
    ),
    "B3b location with SAS parameters": (
        LOCATION,
        header(
            "location",
            f"https://x.blob.core.windows.net/c/f?sv=2022-11-02&skoid={TID}&sktid={TID}&Sig=AbCdEf123456",
        ),
        b"AbCdEf123456",
    ),
    "B3c X-Amz-Signature": (
        LOCATION,
        header(
            "location",
            "https://s3.example.com/f?X-Amz-Credential=AKIAIOSFODNN7EXAMPLE&X-Amz-Signature=deadbeefcafe0123",
        ),
        b"deadbeefcafe0123",
    ),
    "B3d SIG in upper case": (
        LOCATION,
        header("location", "https://contoso.sharepoint.com/dl?SIG=Kd9yX2bQm7rT1vZ0"),
        b"Kd9yX2bQm7rT1vZ0",
    ),
    "B4 token in the fragment": (
        LOCATION,
        header("location", "https://contoso.sharepoint.com/dl#sig=Kd9yX2bQm7rT1vZ0&code=0.AXkA"),
        b"Kd9yX2bQm7rT1vZ0",
    ),
    "B5 a JSON key holds an identity": (ITEM, at("Northwind Lab|NorthwindLab", 1), b"NorthwindLab"),
    "B5b a JSON key holds an address": (ITEM, at(REAL, 1), REAL.encode()),
}


def everything(files: Mapping[str, bytes]) -> bytes:
    found = b""
    for name, body in files.items():
        found += name.encode() + b"\n" + body + b"\n"
        if body.startswith(b"\x1f\x8b"):
            found += gzip.decompress(body)
        if body.startswith(b"PK\x03\x04"):
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                for member in archive.namelist():
                    found += member.encode() + b"\n" + everything({member: archive.read(member)})
    return found


def outcome_of(recorded: Recorded, plant: str) -> str:
    (scenario, index), mutate, witness = PLANTS[plant]
    recording = recorded.outcomes[scenario].recording
    hops = list(recording.hops)
    hops[index] = mutate(hops[index])
    shown = "".join(f"{k}: {v}\n" for k, v in hops[index].headers).encode()
    if witness not in everything({"raw": hops[index].body}) + shown:
        return "THROUGH? the plant did not land in the raw answer"
    planted = replace(recording, hops=tuple(hops))
    try:
        files = files_of(scrub(planted))
    except Refused:
        return "refused by the scrub"
    if witness in everything(files):
        found = lint_files(files, recording.identities.everything())
        return (
            f"THROUGH the scrub ({'the record-time lint refuses it' if found else 'and the lint'})"
        )
    return "replaced or dropped by the scrub"


@pytest.mark.parametrize("plant", PLANTS)
def test_a_red_team_plant_never_reaches_a_written_file(recorded: Recorded, plant: str) -> None:
    result = outcome_of(recorded, plant)
    assert not result.startswith("THROUGH"), f"{plant}: {result}"


def test_every_plant_is_counted(recorded: Recorded) -> None:
    results = {plant: outcome_of(recorded, plant) for plant in PLANTS}
    through = [plant for plant, result in results.items() if result.startswith("THROUGH")]
    tally = {
        result: list(results.values()).count(result) for result in sorted(set(results.values()))
    }
    print(f"red team: {len(through)} of {len(PLANTS)} plants through; {tally}")
    assert (len(PLANTS), through) == (59, [])
