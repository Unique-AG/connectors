import base64
import io
import json
import re
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import cast
from urllib.parse import quote

import pytest

import tests.e2e.test_scenarios as runner
from tests.e2e.recording import stand_in
from tests.e2e.recording.conftest import Recorded
from tests.e2e.recording.guard import Refused
from tests.e2e.recording.lint import IDENTITIES_VARIABLE, lint_dir, lint_files, main
from tests.e2e.recording.scrub import (
    RESPONSE_HEADERS,
    Mapper,
    load_corpus,
    made_by_the_mapper,
    map_id,
    mapped_guid,
    scrub,
)
from tests.e2e.test_scenarios import items, mapping, select

type Files = Mapping[str, bytes]
type Plant = Callable[[Files], Files]

IDENTITIES = frozenset(
    {
        stand_in.TENANT_ID,
        stand_in.USER_ID,
        stand_in.UPN,
        stand_in.DOMAIN,
        stand_in.VANITY_DOMAIN,
        stand_in.TENANT_NAME,
        stand_in.DRIVE_ID,
    }
)
MAIL = "fixtures/rec-uc-02-01.03.json"
MOVED = "fixtures/rec-uc-05-16.03.json"
ITEM = "fixtures/rec-uc-01-06.02.json"
DOCX = "fixtures/rec-uc-01-06.04.docx"
CASSETTE = "cassettes/rec-uc-01-06.json"
PREVIEW = "Your new laptop is ready."


def loaded(path: Path) -> object:
    return cast("object", json.loads(path.read_text()))


def files_in(out: Path) -> dict[str, bytes]:
    return {str(p.relative_to(out)): p.read_bytes() for p in sorted(out.glob("*/*"))}


def swap(name: str, old: str, new: str) -> Plant:
    def plant(files: Files) -> Files:
        if old.encode() not in files[name]:
            raise LookupError(f"{old} is not in {name}")
        return {**files, name: files[name].replace(old.encode(), new.encode())}

    return plant


def first_id(name: str) -> Callable[[Files], str]:
    def found(files: Files) -> str:
        match = re.search(r'"id": "([^"]+)"', files[name].decode())
        if match is None:
            raise LookupError(f"no id in {name}")
        return match[1]

    return found


def swap_first_id(name: str, new: str) -> Plant:
    return lambda files: swap(name, first_id(name)(files), new)(files)


def in_docx(files: Files) -> Files:
    source = zipfile.ZipFile(io.BytesIO(files[DOCX]))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for member in source.namelist():
            data = source.read(member)
            target.writestr(member, data.replace(b"Mia Keller", stand_in.UPN.encode()))
    return {**files, DOCX: out.getvalue()}


PLANTED: dict[str, tuple[Plant, str]] = {
    "plain address": (
        swap(MAIL, "anna@example.test", "anna.meier@northwind-lab.ch"),
        "an address outside",
    ),
    "URL-encoded twice": (
        swap(MAIL, PREVIEW, quote(quote(stand_in.UPN, safe=""), safe="")),
        "(URL-decoded x2)",
    ),
    "raw Exchange id": (
        swap_first_id(MAIL, stand_in.exchange_id(b"\x00\x03\x24\x00", 7)),
        "an id the mapper did not make",
    ),
    "raw drive id": (swap_first_id(ITEM, stand_in.ITEM_ID), "an id the mapper did not make"),
    "tenant GUID": (swap(MAIL, PREVIEW, stand_in.TENANT_ID), "a GUID the mapper did not make"),
    "GUID without dashes": (
        swap(MAIL, PREVIEW, stand_in.TENANT_ID.replace("-", "")),
        "a GUID without dashes",
    ),
    "OneDrive path": (
        swap(CASSETTE, "/personal/mia_example_test", stand_in.ONEDRIVE_PATH),
        "a OneDrive path",
    ),
    "docx part": (in_docx, "a binary that the seed generator did not make"),
    "token": (swap(MAIL, PREVIEW, stand_in.TEMPAUTH), "a token-like string"),
    "tempauth": (swap(CASSETTE, "Translate=false", "tempauth=x"), "a credential parameter"),
    "sig": (swap(CASSETTE, "Translate=false", "sig=x"), "a credential parameter"),
    "SAS parameter": (swap(CASSETTE, "Translate=false", "skoid=x"), "a credential parameter"),
    "response header": (
        swap(CASSETTE, '"location":', '"x-ms-ags-diagnostic": "{}", "location":'),
        "keeps the response header x-ms-ags-diagnostic",
    ),
    "foreign subject": (
        swap(MAIL, "Laptop rollout: your new device", "Contract renewal"),
        "a subject that is not corpus text",
    ),
    "unknown key": (
        swap(MOVED, '"bodyPreview"', '"internetMessageId": "x", "bodyPreview"'),
        "the key 'internetMessageId' is not in the projection",
    ),
    "foreign address key": (
        swap(MAIL, "anna@example.test", "anna@example.com"),
        "an address that is not synthetic",
    ),
}
ENCODED: dict[str, tuple[str, str]] = {
    "tenant name": (stand_in.TENANT_NAME, "(plain)"),
    "tenant short name": ("Northwind team", "a short form"),
    "drive id in base64": (stand_in.DRIVE_ID, "encoded"),
    "OneDrive path": (stand_in.ONEDRIVE_PATH, "underscored"),
    "UPN in base32": (base64.b32encode(stand_in.UPN.encode()).decode(), "encoded"),
    "UPN as HTML entities": ("".join(f"&#{ord(c)};" for c in stand_in.UPN), "HTML-unescaped"),
    "UPN as \\u escapes": ("".join(f"\\\\u{ord(c):04x}" for c in stand_in.UPN), "\\u-unescaped"),
    "UPN in MIME Q": (
        "=?UTF-8?Q?" + "".join(f"={ord(c):02X}" for c in stand_in.UPN) + "?=",
        "MIME-decoded",
    ),
    "GUID without dashes": (stand_in.USER_ID.replace("-", ""), "without dashes"),
    "double base64": (
        base64.b64encode(base64.b64encode(stand_in.UPN.encode())).decode(),
        "encoded",
    ),
}


def test_the_recorded_cassettes_are_clean(recorded: Recorded) -> None:
    assert lint_dir(recorded.out) == []
    assert lint_dir(recorded.out, IDENTITIES) == []


def test_the_hand_written_cassettes_pass_the_lint() -> None:
    assert lint_dir(runner.HERE) == []


@pytest.mark.parametrize("plant", PLANTED)
def test_a_planted_leak_fails_the_lint(recorded: Recorded, plant: str) -> None:
    made, expected = PLANTED[plant]
    findings = lint_files(made(files_in(recorded.out)))
    assert any(expected in line for line in findings), findings


@pytest.mark.parametrize("plant", ENCODED)
def test_an_identity_is_found_in_its_encoded_form(recorded: Recorded, plant: str) -> None:
    planted, form = ENCODED[plant]
    findings = lint_files(swap(MAIL, PREVIEW, planted)(files_in(recorded.out)), IDENTITIES)
    assert any("identity #" in line and form in line for line in findings), findings


def test_the_lint_fails_closed_without_identities(
    recorded: Recorded, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(IDENTITIES_VARIABLE, raising=False)
    assert main([str(recorded.out), "--require-identities"]) == 2
    assert f"{IDENTITIES_VARIABLE} is not set" in capsys.readouterr().err
    monkeypatch.setenv(IDENTITIES_VARIABLE, ",".join(sorted(IDENTITIES)))
    assert main([str(recorded.out), "--require-identities"]) == 0
    assert "scrub lint: clean (7 identities)" in capsys.readouterr().out


def test_a_mapped_id_keeps_its_format_and_is_stable() -> None:
    raw = stand_in.exchange_id(b"\x00\x03\x24\x00", 101)
    mapped = map_id(raw)
    assert mapped == map_id(raw) != raw
    assert len(mapped) == len(raw) and mapped.startswith("AAMkAG")
    assert [c for c in mapped if not c.isalnum()] == [c for c in raw if not c.isalnum()]
    assert [c.isdigit() for c in mapped] == [c.isdigit() for c in raw]
    assert made_by_the_mapper(mapped) and not made_by_the_mapper(raw)
    item = map_id(stand_in.ITEM_ID)
    assert re.fullmatch(r"01[A-Z0-9]{32}", item) and item != stand_in.ITEM_ID
    assert map_id(stand_in.DRIVE_ID).startswith("b!")


def test_a_guid_becomes_a_recognizable_guid() -> None:
    mapped = mapped_guid(stand_in.TENANT_ID)
    assert re.fullmatch(r"00000000-[0-9a-f]{4}-4[0-9a-f]{3}-8[0-9a-f]{3}-[0-9a-f]{12}", mapped)
    assert mapped_guid(stand_in.TENANT_ID.upper()) == mapped.upper()


def test_the_corpus_decides_what_text_stays() -> None:
    corpus = load_corpus()
    assert corpus.accepts("RE: Website relaunch: launch checklist")
    assert corpus.accepts("<c0>Project</c0> <c0>Plan</c0><ddd/>")
    assert corpus.accepts("Inbox")
    assert not corpus.accepts("Contract renewal Northwind Lab")
    assert not corpus.accepts('<a href="mailto:x@y.ch">Project Plan</a>')
    assert not corpus.accepts("Ann")


def test_the_scrub_drops_headers_and_keys_outside_the_allowlists(recorded: Recorded) -> None:
    recording = recorded.outcomes["uc-05-16"].recording
    raw = {name.lower() for hop in recording.hops for name, _ in hop.headers}
    kept = {
        name
        for path in (recorded.out / "cassettes").glob("rec-*.json")
        for one in items(loaded(path))
        for name in mapping(mapping(one).get("response_headers", {}))
    }
    assert {"x-ms-ags-diagnostic", "request-id", "set-cookie", "sprequestguid"} <= raw
    assert kept <= RESPONSE_HEADERS
    moved = mapping(loaded(recorded.out / MOVED))
    assert not {"internetMessageHeaders", "internetMessageId", "@odata.context"} & set(moved)
    assert select(moved, "body.content") == "synthetic text 01"


def test_foreign_text_and_addresses_become_placeholders(recorded: Recorded) -> None:
    pages = ("fixtures/rec-uc-02-01.03.json", "fixtures/rec-uc-02-01.04.json")
    rows = [row for page in pages for row in items(select(loaded(recorded.out / page), "value"))]
    assert [select(row, "subject") for row in rows][-2:] == [
        "synthetic text 03",
        "synthetic text 06",
    ]
    senders = {select(row, "from.emailAddress.address") for row in rows}
    assert senders <= {"mia@example.test", "anna@example.test", "tom@example.test"} | {
        f"user-{n:02d}@example.test" for n in range(1, 10)
    }


def test_a_persona_keeps_the_persona_name_that_the_corpus_gives_it() -> None:
    mapper = Mapper(load_corpus(), {"tester3@dogfood.test": "mia"}, frozenset(), "")
    row = {"from": {"emailAddress": {"address": "tester3@dogfood.test", "name": "Tester Three"}}}
    stranger = {"emailAddress": {"address": "ann@other.test", "name": "Ann Other"}}
    assert mapper.response(row) == {
        "from": {"emailAddress": {"address": "mia@example.test", "name": "Mia Keller"}}
    }
    assert mapper.response(stranger) == {
        "emailAddress": {"address": "user-01@example.test", "name": "synthetic text 01"}
    }


def test_the_download_location_loses_its_credentials(recorded: Recorded) -> None:
    location = select(loaded(recorded.out / CASSETTE), "[2].response_headers.location")
    assert location == (
        "https://contoso-my.sharepoint.com/personal/mia_example_test/_layouts/15/download.aspx"
        + f"?UniqueId={mapped_guid(stand_in.FILE_UNIQUE_ID)}&Translate=false&ApiVersion=2.0"
    )


def test_a_binary_that_the_seed_did_not_make_is_refused(recorded: Recorded) -> None:
    recording = recorded.outcomes["uc-01-06"].recording
    hops = list(recording.hops)
    hops[3] = replace(hops[3], body=hops[3].body + b"\x00")
    with pytest.raises(Refused, match="not a file that the seed generator made"):
        _ = scrub(replace(recording, hops=tuple(hops)))
