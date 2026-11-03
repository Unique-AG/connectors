import base64
import io
import json
import re
import zipfile
from collections.abc import Callable, Collection, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import quote

import pytest

import tests.e2e.test_scenarios as runner
from tests.e2e.recording import stand_in
from tests.e2e.recording.conftest import Recorded
from tests.e2e.recording.guard import GRAPH_HOST, Refused
from tests.e2e.recording.lint import IDENTITIES_VARIABLE, lint_dir, lint_files, main
from tests.e2e.recording.scrub import (
    RESPONSE_HEADERS,
    Fixture,
    Hop,
    Identities,
    Mapper,
    Recording,
    files_of,
    load_corpus,
    made_by_the_mapper,
    map_id,
    mapped_guid,
    mapped_id,
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
MAIL = "bodies/rec-uc-02-01.03.json"
MOVED = "bodies/rec-uc-05-16.03.json"
ITEM = "bodies/rec-uc-01-06.02.json"
DOCX = "bodies/rec-uc-01-06.04.docx"
FIXTURE = "fixtures/rec-uc-01-06.json"
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
        swap(FIXTURE, "/personal/mia_example_test", stand_in.ONEDRIVE_PATH),
        "a OneDrive path",
    ),
    "docx part": (in_docx, "a binary that the seed generator did not make"),
    "token": (swap(MAIL, PREVIEW, stand_in.TEMPAUTH), "a token-like string"),
    "tempauth": (swap(FIXTURE, "Translate=false", "tempauth=x"), "a credential parameter"),
    "sig": (swap(FIXTURE, "Translate=false", "sig=x"), "a credential parameter"),
    "SAS parameter": (swap(FIXTURE, "Translate=false", "skoid=x"), "a credential parameter"),
    "response header": (
        swap(FIXTURE, '"location":', '"x-ms-ags-diagnostic": "{}", "location":'),
        "keeps the response header x-ms-ags-diagnostic",
    ),
    "foreign subject": (
        swap(MAIL, "Laptop rollout: your new device", "Contract renewal"),
        "a subject that is not corpus text",
    ),
    "unknown key": (
        swap(MOVED, '"bodyPreview"', '"internetMessageId": "x", "bodyPreview"'),
        "at internetMessageId: a key that is not in the projection",
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


def test_the_recorded_fixtures_are_clean(recorded: Recorded) -> None:
    assert lint_dir(recorded.out) == []
    assert lint_dir(recorded.out, IDENTITIES) == []


def test_the_hand_written_fixtures_pass_the_lint() -> None:
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


@pytest.mark.parametrize(
    ("body", "short_form_counts"),
    [
        ({"uniqueBody": {"content": "x"}}, False),
        ({"url": "https://graph.microsoft.com/v1.0/me/messages?$select=id,uniqueBody"}, False),
        ({"uniqueBody": {"note": "unique.ch"}}, True),
        ({"note": "the unique team"}, True),
        ({"url": "https://graph.microsoft.com/v1.0/me/messages?$select=id,uniqueFoo"}, True),
    ],
)
def test_a_short_form_inside_a_schema_key_is_no_leak_but_the_full_identity_is(
    body: Mapping[str, object], short_form_counts: bool
) -> None:
    files = {"bodies/x.01.json": json.dumps(body).encode()}
    findings = lint_files(files, {"unique.ch"})
    assert bool(findings) is short_form_counts, findings


def test_a_finding_names_the_path_and_class_but_never_the_text() -> None:
    body = {
        "value": [
            {"name": "ok", "owner": "bob@corp-secret.com"},
            {"links": {"href": "https://leaky.sharepoint.com/a"}, "note": "see Zebra Corp"},
        ]
    }
    files = {"bodies/x.01.json": json.dumps(body).encode()}
    findings = lint_files(files, {"zebra corp"})
    assert findings == [
        "bodies/x.01.json at value[0].owner: an address outside the reserved domains (plain)",
        "bodies/x.01.json at value[1].links.href: a SharePoint host (plain)",
        "bodies/x.01.json at value[1].note: identity #1 (plain)",
    ]
    assert not re.search(r"secret|leaky|zebra", "".join(findings), re.I)


def test_the_lint_fails_closed_without_identities(
    recorded: Recorded, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(IDENTITIES_VARIABLE, raising=False)
    assert main([str(recorded.out), "--require-identities"]) == 2
    assert f"{IDENTITIES_VARIABLE} is not set" in capsys.readouterr().err
    monkeypatch.setenv(IDENTITIES_VARIABLE, ",".join(sorted(IDENTITIES)))
    assert main([str(recorded.out), "--require-identities"]) == 0
    assert "scrub lint: clean (7 identities)" in capsys.readouterr().out


def test_amapped_id_keeps_its_format_and_is_stable() -> None:
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


def test_amapped_id_never_holds_a_token_header() -> None:
    raw = "AAMKAGF1F" + "aaA" * 15
    assert "eyJ" in mapped_id(raw, 0)
    mapped = map_id(raw)
    assert "eyJ" not in mapped and made_by_the_mapper(mapped) and mapped == map_id(raw)


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
        for path in (recorded.out / "fixtures").glob("rec-*.json")
        for one in items(loaded(path))
        for name in mapping(mapping(one).get("response_headers", {}))
    }
    assert {"x-ms-ags-diagnostic", "request-id", "set-cookie", "sprequestguid"} <= raw
    assert kept <= RESPONSE_HEADERS
    moved = mapping(loaded(recorded.out / MOVED))
    assert not {"internetMessageHeaders", "internetMessageId", "@odata.context"} & set(moved)
    assert select(moved, "body.content") == "synthetic text 01"


def test_foreign_text_and_addresses_become_placeholders(recorded: Recorded) -> None:
    pages = ("bodies/rec-uc-02-01.03.json", "bodies/rec-uc-02-01.04.json")
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


def test_a_page_element_id_in_a_request_maps_like_the_one_in_the_page() -> None:
    mapper = Mapper(load_corpus(), {}, frozenset(), "")
    raw = f"p:{{{stand_in.TENANT_ID}}}{{12}}"
    assert mapper.request_value(raw) == mapper.page_attribute("id", raw)
    assert mapper.request_value(raw) == f"p:{{{mapped_guid(stand_in.TENANT_ID)}}}{{12}}"


def test_a_page_read_keeps_the_include_ids_flag_in_its_query() -> None:
    mapper = Mapper(load_corpus(), {}, frozenset(), "")
    assert mapper.query({"includeIDs": "true", "tempauth": "x"}) == {"includeIDs": "true"}


def test_the_download_location_loses_its_credentials(recorded: Recorded) -> None:
    location = select(loaded(recorded.out / FIXTURE), "[2].response_headers.location")
    assert location == (
        "https://contoso-my.sharepoint.com/personal/mia_example_test/_layouts/15/download.aspx"
        + f"?itemId={mapped_guid(stand_in.FILE_UNIQUE_ID)}&Translate=false&ApiVersion=2.0"
    )
    assert lint_dir(recorded.out, {"unique.ch"}) == []


def test_a_binary_that_the_seed_did_not_make_is_refused(recorded: Recorded) -> None:
    recording = recorded.outcomes["uc-01-06"].recording
    hops = list(recording.hops)
    hops[3] = replace(hops[3], body=hops[3].body + b"\x00")
    with pytest.raises(Refused, match="not a file that the seed generator made"):
        _ = scrub(replace(recording, hops=tuple(hops)))


def one_hop(
    path: str,
    *,
    method: str = "GET",
    query: Mapping[str, str] | None = None,
    sent: object = None,
    answer: object = None,
    literals: Collection[str] = (),
) -> Fixture:
    asked = {"method": method, "host": GRAPH_HOST, "path": path, "query": dict(query or {})}
    asked |= {"headers": {}, "json": sent}
    body = json.dumps(answer).encode() if answer is not None else b""
    headers = (("content-type", "application/json"),) if body else ()
    hop = Hop(asked, f"https://{GRAPH_HOST}{path}", False, 200, headers, body)
    day = datetime(2026, 10, 29, tzinfo=UTC)
    identities = Identities(frozenset(), "token")
    recording = Recording(
        "one", "rec-one", "stand-in", day, (hop,), identities, {}, frozenset(literals)
    )
    return scrub(recording)


def shared(link: str) -> str:
    return "u!" + base64.urlsafe_b64encode(link.encode()).decode().rstrip("=")


def interaction_of(fixture: Fixture) -> Mapping[str, object]:
    return mapping(fixture.interactions[0])


class TestQueryAndPath:
    def test_a_date_window_in_the_query_becomes_day_symbols(self) -> None:
        window = {
            "startDateTime": "2026-10-28T00:00:00+00:00",
            "endDateTime": "2026-10-30T00:00:00+00:00",
        }
        fixture = one_hop("/v1.0/me/calendars/x/calendarView", query=window)
        assert interaction_of(fixture)["query"] == {
            "startDateTime": "~yesterday",
            "endDateTime": "~tomorrow",
        }

    def test_a_conflict_behavior_and_a_search_key_survive_and_a_stray_key_does_not(self) -> None:
        asked = {"@microsoft.graph.conflictBehavior": "fail", "search": "seed-v1", "stray": "x"}
        fixture = one_hop("/v1.0/sites", query=asked)
        assert interaction_of(fixture)["query"] == {
            "@microsoft.graph.conflictBehavior": "fail",
            "search": "seed-v1",
        }

    def test_an_id_with_a_slash_is_mapped_in_pieces_and_passes_the_lint(self) -> None:
        item = "AAMkAbCdEfGhIjKlMnOpQrSt%2FUvWxYzAbCdEfGhIjKlMnOp"
        link = f"https://outlook.office365.com/owa/?ItemID={item}&exvsurl=1"
        fixture = one_hop("/v1.0/me/reminders", answer={"webLink": link})
        assert lint_files(files_of(fixture)) == []
        assert "AbCdEfGhIjKlMnOpQrSt" not in fixture.bodies["rec-one.01.json"].decode()

    @pytest.mark.parametrize(
        "path",
        [
            "/v1.0/me/outlook/supportedTimeZones()",
            "/v1.0/me/onenote/notebooks/getRecentNotebooks(includePersonalNotebooks=true)",
            "/v1.0/me/preview()",
        ],
    )
    def test_a_function_call_in_a_path_is_kept(self, path: str) -> None:
        assert interaction_of(one_hop(path))["path"] == path

    def test_a_dated_function_call_gets_day_symbols_and_an_address_argument_is_replaced(
        self,
    ) -> None:
        dates = (
            "startDateTime='2026-10-28T00:00:00.0000000',endDateTime='2026-10-30T00:00:00.0000000'"
        )
        window = f"reminderView({dates})"
        assert interaction_of(one_hop(f"/v1.0/me/{window}"))["path"] == (
            "/v1.0/me/reminderView(startDateTime='~yesterday',endDateTime='~tomorrow')"
        )
        found = one_hop("/v1.0/me/lookup(who='real@corp.ch',day='x')")
        assert (
            interaction_of(found)["path"] == "/v1.0/me/lookup(who='user-01@example.test',day='x')"
        )

    def test_a_call_with_an_argument_outside_the_grammar_is_not_kept(self) -> None:
        path = interaction_of(one_hop("/v1.0/me/lookup(name=secret)"))["path"]
        assert path == "/v1.0/me/synthetic text 01"

    def test_a_segment_that_ends_in_a_colon_maps_its_id_and_keeps_the_colon(self) -> None:
        parent, name = "01ABCDEFGHIJKLMNOPQRSTUVWXYZ012345", "seed-v1 case-x.txt"
        drive = "b!" + "Q7" * 15
        path = f"/v1.0/drives/{drive}/items/{parent}:/{name}:/content"
        fixture = one_hop(
            path,
            method="PUT",
            sent="seed-v1 text",
            answer={"id": parent, "name": name, "parentReference": {"driveId": drive}},
            literals=frozenset({name, "seed-v1 text"}),
        )
        shown = interaction_of(fixture)
        assert shown["path"] == (
            f"/v1.0/drives/{map_id(drive)}/items/{map_id(parent)}:/{name}:/content"
        )
        assert shown["json"] == "seed-v1 text"
        assert lint_files(files_of(fixture)) == []

    def test_a_share_token_is_decoded_scrubbed_and_encoded_again(self) -> None:
        link = "https://acme-my.sharepoint.com/personal/jane_acme_ch/Documents/secret.docx"
        fixture = one_hop(f"/v1.0/shares/{shared(link)}/driveItem")
        scrubbed = (
            "https://contoso-my.sharepoint.com/personal/user_01_example_test/Documents/"
            + "synthetic%20text%2001"
        )
        assert interaction_of(fixture)["path"] == f"/v1.0/shares/{shared(scrubbed)}/driveItem"
        assert lint_files(files_of(fixture)) == []

    def test_a_share_token_that_holds_no_link_is_mapped_as_an_id(self) -> None:
        token = shared("jane acme secret document text")
        path = str(interaction_of(one_hop(f"/v1.0/shares/{token}/driveItem"))["path"])
        assert token not in path


class TestRequestValues:
    def test_a_list_of_option_words_stays_and_a_list_of_names_does_not(self) -> None:
        tips = "automaticReplies, mailboxFullStatus, customMailTip"
        body = {"EmailAddresses": ["mia@example.test"], "MailTipsOptions": tips}
        kept = one_hop("/v1.0/me/getMailTips", method="POST", sent=body)
        assert mapping(interaction_of(kept)["json"])["MailTipsOptions"] == tips
        named = one_hop("/v1.0/me/getMailTips", method="POST", sent={"x": "Smith, John"})
        assert mapping(interaction_of(named)["json"])["x"] == "synthetic text 01"

    @pytest.mark.parametrize(
        "emoji",
        [
            "\U0001f44d",
            "\U0001f44d\U0001f3fd",
            "\u2764\ufe0f",
            "\U0001f468\u200d\U0001f469\u200d\U0001f467",
        ],
    )
    def test_a_reaction_emoji_stays_and_passes_the_lint(self, emoji: str) -> None:
        path = "/v1.0/me/messages/x/setReaction"
        fixture = one_hop(path, method="POST", sent={"reactionType": emoji})
        assert mapping(interaction_of(fixture)["json"])["reactionType"] == emoji
        assert lint_files(files_of(fixture)) == []

    @pytest.mark.parametrize(
        "word", ["great job", "John Smith", "\U0001f44d thanks", "\U0001f44d1", "\U0001f44d" * 9]
    )
    def test_a_word_in_the_reaction_key_is_still_replaced(self, word: str) -> None:
        fixture = one_hop("/v1.0/me/x", method="POST", sent={"reactionType": word})
        assert mapping(interaction_of(fixture)["json"])["reactionType"] == "synthetic text 01"

    def test_the_webdav_address_of_a_file_matches_the_attachment_that_carries_it(self) -> None:
        address = "https://tenant-my.sharepoint.com/personal/mia_tenant_com/Documents/seed-v1%20Seed%20Files/a.txt"
        item = one_hop("/v1.0/me/drive/items/x", answer={"name": "a.txt", "webDavUrl": address})
        message = one_hop(
            "/v1.0/me/chats/x/messages",
            method="POST",
            sent={"attachments": [{"contentUrl": address}]},
        )
        answered = mapping(cast("object", json.loads(item.bodies["rec-one.01.json"])))["webDavUrl"]
        sent = mapping(items(mapping(interaction_of(message)["json"])["attachments"])[0])[
            "contentUrl"
        ]
        assert answered == sent
        assert "tenant" not in str(answered)
        assert lint_files(files_of(item)) == []

    def test_a_page_keeps_its_envelope_and_scrubs_only_its_text(self) -> None:
        page = (
            "<!DOCTYPE html><html><head><title>{}</title>"
            + '<meta name="created" content="2026-10-29T09:00:00+00:00" /></head><body><p>{}</p>'
            + "</body></html>"
        )
        literals = frozenset({"seed-v1 case-x", "seed-v1 text"})
        sent = page.format("seed-v1 case-x", "seed-v1 text")
        kept = one_hop("/v1.0/me/onenote/pages", method="POST", sent=sent, literals=literals)
        assert interaction_of(kept)["json"] == sent.replace("2026-10-29T09:00:00+00:00", "~today")
        foreign = page.format("seed-v1 case-x", "Contract renewal")
        shown = str(interaction_of(one_hop("/v1.0/x", method="POST", sent=foreign))["json"])
        assert shown.startswith("<!DOCTYPE html><html><head><title>")
        assert "<body>synthetic text 02</body>" in shown
        assert "Contract" not in shown

    @pytest.mark.parametrize("tag", ['<p data-id="intro">', '<p data-id="a-b_1">'])
    def test_a_page_keeps_a_paragraph_with_a_data_id(self, tag: str) -> None:
        page = (
            "<!DOCTYPE html><html><head><title>seed-v1 case-x</title>"
            + '<meta name="created" content="2026-10-29T09:00:00+00:00" /></head><body>{}'
            + "seed-v1 text</p></body></html>"
        )
        literals = frozenset({"seed-v1 case-x", "seed-v1 text"})
        sent = page.format(tag)
        kept = one_hop("/v1.0/me/onenote/pages", method="POST", sent=sent, literals=literals)
        assert interaction_of(kept)["json"] == sent.replace("2026-10-29T09:00:00+00:00", "~today")
        assert lint_files(files_of(kept)) == []

    @pytest.mark.parametrize(
        "tag", ['<p data-id="Contract renewal">', '<p data-id="x@evil.ch">', '<p data-other="a">']
    )
    def test_a_page_with_another_attribute_or_a_free_data_id_is_replaced(self, tag: str) -> None:
        page = (
            "<!DOCTYPE html><html><head><title>seed-v1 case-x</title>"
            + '<meta name="created" content="2026-10-29T09:00:00+00:00" /></head><body>{}'
            + "seed-v1 text</p></body></html>"
        )
        literals = frozenset({"seed-v1 case-x", "seed-v1 text"})
        sent = page.format(tag)
        shown = str(
            interaction_of(one_hop("/v1.0/x", method="POST", sent=sent, literals=literals))["json"]
        )
        assert "<body>synthetic text 01</body>" in shown

    def test_a_date_under_an_object_key_stays_and_other_text_does_not(self) -> None:
        fixture = one_hop("/v1.0/me/x", answer={"value": [{"start": "2026-10-29T14:00:00Z"}]})
        assert '"start": "2026-10-29T14:00:00Z"' in fixture.bodies["rec-one.01.json"].decode()
        other = one_hop("/v1.0/me/x", answer={"start": "late afternoon"})
        assert "late afternoon" not in other.bodies["rec-one.01.json"].decode()

    def test_a_join_link_in_a_filter_is_scrubbed_like_the_link_in_the_answer(self) -> None:
        link = (
            "https://teams.microsoft.com/l/meetup-join/19%3ameeting_abcdefghijklmnop%40thread.v2/0"
        )
        fixture = one_hop(
            "/v1.0/me/onlineMeetings",
            query={"$filter": f"JoinWebUrl eq '{link}'"},
            answer={"value": [{"joinWebUrl": link}]},
        )
        body = mapping(cast("object", json.loads(fixture.bodies["rec-one.01.json"])))
        joined = mapping(items(body["value"])[0])["joinWebUrl"]
        wanted = f"JoinWebUrl eq '{joined}'"
        assert mapping(interaction_of(fixture)["query"])["$filter"] == wanted
        assert "abcdefghijklmnop" not in wanted


class TestThreadIds:
    @pytest.mark.parametrize(
        "thread",
        ["19:Zm9vYmFyYmF6cXV4MTIzNDU2@thread.v2", "19:a1b2c3d4_e5f6a7b8c9d0e1f2@unq.gbl.spaces"],
    )
    def test_a_thread_id_keeps_its_suffix_and_stays_made_by_the_mapper(self, thread: str) -> None:
        mapped = map_id(thread)
        suffix = thread.partition("@")[2]
        assert mapped.endswith(f"@{suffix}") and mapped != thread
        assert made_by_the_mapper(mapped) and not made_by_the_mapper(thread)

    def test_an_address_that_looks_like_a_thread_id_is_not_kept(self) -> None:
        mapper = Mapper(load_corpus(), {}, frozenset(), "")
        raw = "19:Zm9vYmFyYmF6cXV4MTIzNDU2@thread.v2"
        assert mapper.plain(f"chatId eq '{raw}'") == "chatId eq '19:user-01@example.test'"
        assert mapper.plain(f"x eq '{map_id(raw)}'") == f"x eq '{map_id(raw)}'"

    @pytest.mark.parametrize(
        ("text", "clean"),
        [
            ("19:abc@thread.v2", True),
            ("19:abc@unq.gbl.spaces", True),
            ("19:abc@xyz.unq.gbl.spaces", True),
            ("abc@aa.bb.cc.dd.spaces", False),
            ("abc@xyz.unq.gbl.spaces.evil.ch", False),
            ("abc@thread.v2.evil.ch", False),
            ("abc@unq.gbl.spaces.evil.ch", False),
            ("abc@unq.gbl.evil.ch", False),
        ],
    )
    def test_the_lint_exempts_a_thread_suffix_and_nothing_longer(
        self, text: str, clean: bool
    ) -> None:
        found = lint_files({"x.json": json.dumps([text]).encode()})
        assert (found == []) == clean, found


BIND_FIXTURE = "fixtures/rec-x.json"


class TestTheBindKey:
    def lint_key(self, key: str) -> list[str]:
        interaction = {"method": "POST", "path": "/v1.0/chats", "json": {"members": [{key: "x"}]}}
        return lint_files({BIND_FIXTURE: json.dumps([interaction]).encode()})

    def test_the_bind_key_of_a_member_is_no_address(self) -> None:
        assert self.lint_key("user@odata.bind") == []

    @pytest.mark.parametrize(
        "key",
        ["xuser@odata.bind", "user@odata.bind.evil.ch", "user@odata.bindings", "a@odata.bind"],
    )
    def test_a_look_alike_key_is_still_an_address_and_the_finding_names_its_path(
        self, key: str
    ) -> None:
        found = self.lint_key(key)
        assert found == [
            f"{BIND_FIXTURE} at [0].json.members[0].(a key): an address outside the reserved "
            + "domains (plain)"
        ]


ATTACHED = "1E3A8B2C-4D5E-4F60-8A7B-9C0D1E2F3A4B"
NOTES = "seed-v1 case-x notes"


def sent_with_tag(text: str, guid: str) -> str:
    return f'<p>{text}</p> <attachment id="{guid}"></attachment>'


class TestAttachmentTags:
    def request(self, raw: str) -> str:
        return Mapper(load_corpus(), {}, frozenset(), NOTES).request_value(raw)

    def test_a_request_tag_keeps_its_text_and_maps_its_id_as_the_answer_does(self) -> None:
        etag = Mapper(load_corpus(), {}, frozenset(), "").id(f'"{{{ATTACHED}}},3"')
        mapped = mapped_guid(ATTACHED.lower())
        assert self.request(sent_with_tag(NOTES, ATTACHED.lower())) == sent_with_tag(NOTES, mapped)
        assert mapped in etag.lower()

    def test_a_request_tag_with_free_text_is_replaced_whole(self) -> None:
        assert self.request(sent_with_tag("a private word", ATTACHED)) == "synthetic text 01"
