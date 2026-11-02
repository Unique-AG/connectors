import asyncio
import base64
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar, cast
from urllib.parse import unquote, urlsplit

import httpx
import pytest

from office_365_mcp.shared.notes import owner_of_graph_url, resource_id_in
from tests.e2e.recording import record as record_module
from tests.e2e.recording import stand_in
from tests.e2e.recording.conftest import record_on
from tests.e2e.recording.guard import Guard, Refused
from tests.e2e.recording.lint import lint_files
from tests.e2e.recording.record import (
    Plan,
    persona_values,
    preflight,
    resolve,
    tool_of,
    uses_ids,
    with_personas,
)
from tests.e2e.recording.scrub import (
    Corpus,
    Hop,
    Identities,
    Persona,
    Recording,
    files_of,
    holds_bytes,
    mapped_guid,
    normalized,
    scrub,
)
from tests.e2e.test_scenarios import Json, attribute_in, mapping, select
from tests.graph_fixtures import generate, response

GRAPH = "https://graph.microsoft.com/v1.0"
KEPT = b"seed attachment bytes"
OTHER = b"not a seed attachment"
STRINGS = frozenset({"seed-v1 Gallery", "This page holds one picture.", "A blue square", "intro"})
CORPUS = Corpus(
    "seed-v1",
    STRINGS,
    frozenset({hashlib.sha256(KEPT).hexdigest()}),
    (Persona("anna", 2, "Anna Meier"),),
    "\x00".join(normalized(one) for one in sorted(STRINGS)),
)
PAGE_ID = "1-0f1e2d3c-4b5a-4978-8796-a5b4c3d2e1f0!1-8d4f1a2b-3c5e-4f60-9a7b-2c1d0e9f8a7b"
RESOURCE = "1-aaaa1111-bbbb-4222-8333-cccc44445555!1-dddd6666-eeee-4777-8888-ffff99990000"
SOURCE = f"{GRAPH}/users('{stand_in.USER_ID}')/onenote/resources/{RESOURCE}/$value"
PAGE = (
    '<html lang="en-US"><head><title>seed-v1 Gallery</title>'
    + '<meta name="created" content="2026-10-29T10:00:00.0000000" /></head>'
    + '<body data-absolute-enabled="true" style="font-family:Calibri;font-size:11pt">'
    + f'<div style="position:absolute;left:48px;top:120px"><p id="p:{{{stand_in.TENANT_ID}}}{{3}}"'
    + ' data-id="intro">This page holds one picture.</p>'
    + "<p>Call Zephyr Corp about the deal.</p><!-- a note by someone --></div>"
    + f'<img id="img:{{{stand_in.USER_ID}}}{{14}}" src="{SOURCE}" data-src-type="image/png"'
    + f' data-fullres-src="{SOURCE}" alt="A blue square" width="64" height="64" />'
    + '<img src="https://evil.example/pixel.png?token=abc" alt="Zephyr Corp logo" />'
    + "</body></html>"
)


def hop(path: str, body: bytes, media: str, status: int = 200) -> Hop:
    asked = {"method": "GET", "host": "graph.microsoft.com", "path": path}
    asked |= {"query": {}, "headers": {}, "json": None}
    return Hop(asked, f"{GRAPH}{path[5:]}", True, status, (("content-type", media),), body)


def scrubbed(*hops: Hop) -> dict[str, bytes]:
    recording = Recording(
        "page-scrub",
        "rec-tool-page-scrub",
        "stand-in",
        datetime(2026, 10, 29, tzinfo=UTC),
        hops,
        Identities(frozenset({stand_in.USER_ID, stand_in.UPN, stand_in.TENANT_ID}), "token"),
        {stand_in.UPN.casefold(): "mia"},
        frozenset(),
    )
    return files_of(scrub(recording, CORPUS))


def lint(files: dict[str, bytes]) -> list[str]:
    return lint_files(files, {stand_in.USER_ID, stand_in.UPN, stand_in.TENANT_ID}, CORPUS)


def page_files(markup: str = PAGE) -> dict[str, bytes]:
    path = f"/v1.0/me/onenote/pages/{PAGE_ID}/content"
    return scrubbed(hop(path, markup.encode(), "text/html; charset=utf-8"))


def page_text(files: dict[str, bytes]) -> str:
    return files["bodies/rec-tool-page-scrub.01.html"].decode()


class TestPageHtml:
    def test_a_page_keeps_its_structure_and_the_corpus_text_and_nothing_else(self) -> None:
        shown = page_text(page_files())
        for kept in ("<title>seed-v1 Gallery</title>", ">This page holds one picture.</p>"):
            assert kept in shown
        assert 'data-id="intro"' in shown
        assert 'alt="A blue square"' in shown
        assert 'style="position:absolute;left:48px;top:120px"' in shown
        assert 'data-src-type="image/png"' in shown
        assert "Zephyr" not in shown
        assert "synthetic text 01" in shown
        assert "a note by someone" not in shown

    def test_a_font_family_gets_a_generic_fallback_and_no_other_style_changes(self) -> None:
        shown = page_text(page_files())
        assert 'style="font-family:Calibri,sans-serif;font-size:11pt"' in shown
        assert 'style="position:absolute;left:48px;top:120px"' in shown

    def test_an_id_and_a_url_go_through_the_mapper(self) -> None:
        shown = page_text(page_files())
        assert stand_in.USER_ID not in shown
        assert stand_in.TENANT_ID not in shown
        assert mapped_guid(stand_in.USER_ID) in shown
        assert RESOURCE not in shown
        assert f'id="p:{{{mapped_guid(stand_in.TENANT_ID)}}}{{3}}"' in shown

    def test_an_image_address_to_a_foreign_host_never_survives(self) -> None:
        shown = page_text(page_files())
        assert "evil.example" not in shown
        assert "token=abc" not in shown
        assert shown.count("https://graph.microsoft.com/v1.0/users(") == 2

    def test_the_scrubbed_page_passes_the_lint_and_is_served_as_html(self) -> None:
        files = page_files()
        assert lint(files) == []
        meta = cast("list[Json]", json.loads(files["fixtures/rec-tool-page-scrub.json"]))
        assert meta[0]["body"] == "rec-tool-page-scrub.01.html"
        headers = cast("Json", meta[0]["response_headers"])
        assert str(headers["content-type"]).startswith("text/html")

    def test_only_a_get_of_a_page_content_is_html_and_other_html_stays_a_binary(self) -> None:
        elsewhere = hop(f"/v1.0/me/onenote/pages/{PAGE_ID}", PAGE.encode(), "text/html")
        with pytest.raises(Refused, match="not a file that the seed generator made"):
            _ = scrubbed(elsewhere)
        post = hop(f"/v1.0/me/onenote/pages/{PAGE_ID}/content", PAGE.encode(), "text/html")
        post.asked["method"] = "POST"  # pyright: ignore[reportIndexIssue]
        with pytest.raises(Refused, match="not a file that the seed generator made"):
            _ = scrubbed(post)
        plain = hop(f"/v1.0/me/onenote/pages/{PAGE_ID}/content", b"\x89PNG", "image/png")
        with pytest.raises(Refused, match="not a file that the seed generator made"):
            _ = scrubbed(plain)

    @pytest.mark.parametrize(
        ("old", "new", "finding"),
        [
            ("seed-v1 Gallery", "Quarterly numbers", "a text node that is not corpus text"),
            ("A blue square", "Zephyr Corp logo", "an attribute alt that is not corpus text"),
            (
                f"{GRAPH}/users(&#x27;{mapped_guid(stand_in.USER_ID)}&#x27;)/onenote/resources",
                "https://other.example/onenote/resources",
                "an attribute src that is not a Graph or synthetic address",
            ),
            (
                'data-id="intro"',
                'data-id="AAMkAGE0YjQ3ZTQ5LWQyZjYtNDFhZS04OGU3LWE0ZTNiMDg2YzQxOQBGAAAA"',
                "an attribute data-id holds an id the mapper did not make",
            ),
        ],
    )
    def test_the_lint_finds_what_a_bad_scrub_would_leave(
        self, old: str, new: str, finding: str
    ) -> None:
        files = page_files()
        name = "bodies/rec-tool-page-scrub.01.html"
        planted = {**files, name: files[name].decode().replace(old, new, 1).encode()}
        assert any(finding in one for one in lint(planted)), lint(planted)

    def test_the_lint_finds_an_address_and_a_raw_guid_in_the_page(self) -> None:
        files = page_files()
        name = "bodies/rec-tool-page-scrub.01.html"
        text = files[name].decode().replace("<p>", f"<p>{stand_in.UPN} ", 1)
        assert any("an address outside" in one for one in lint({**files, name: text.encode()}))
        raw = files[name].decode().replace("<p>", f"<p>{stand_in.USER_ID} ", 1)
        assert any(
            "a GUID the mapper did not make" in one for one in lint({**files, name: raw.encode()})
        )


class TestAttachmentBytes:
    def attachment(self, content: str) -> dict[str, bytes]:
        body = {"id": "AAMkAGatt", "name": "q3.csv", "size": 12, "contentBytes": content}
        path = "/v1.0/me/messages/AAMkAGmsg/attachments/AAMkAGatt"
        return scrubbed(hop(path, json.dumps(body).encode(), "application/json"))

    def kept(self, files: dict[str, bytes]) -> object:
        body = cast("object", json.loads(files["bodies/rec-tool-page-scrub.01.json"]))
        return select(body, "contentBytes")

    def test_bytes_of_a_seed_file_are_kept_and_pass_the_lint(self) -> None:
        encoded = base64.b64encode(KEPT).decode()
        files = self.attachment(encoded)
        assert self.kept(files) == encoded
        assert lint(files) == []

    def test_bytes_that_the_seed_did_not_make_are_replaced(self) -> None:
        encoded = base64.b64encode(OTHER).decode()
        files = self.attachment(encoded)
        assert self.kept(files) == "synthetic text 01"
        assert encoded.encode() not in b"".join(files.values())

    @pytest.mark.parametrize(
        "content", [base64.b64encode(KEPT + b"!").decode(), "not base64 %%%", "", KEPT.hex()]
    )
    def test_a_near_miss_or_a_bad_encoding_is_never_kept(self, content: str) -> None:
        assert not holds_bytes(CORPUS, content)
        assert self.kept(self.attachment(content)) != content or content == ""

    def test_the_lint_finds_bytes_that_are_not_in_the_corpus(self) -> None:
        files = self.attachment(base64.b64encode(KEPT).decode())
        name = "bodies/rec-tool-page-scrub.01.json"
        other = base64.b64encode(OTHER).decode()
        planted = {
            **files,
            name: files[name].decode().replace(base64.b64encode(KEPT).decode(), other).encode(),
        }
        assert any("a contentBytes that is not corpus text" in one for one in lint(planted))


class TestPersonaPlaceholders:
    UPNS: ClassVar[tuple[str, ...]] = stand_in.UPNS
    IDS: ClassVar[dict[str, str]] = {
        "mia": stand_in.USER_ID,
        "anna": "4c1e8b2a-7d3f-4a96-b5e0-9f2d1c6a8e37",
    }

    def test_a_live_run_gets_the_address_the_id_and_the_name_of_a_test_user(self) -> None:
        live = persona_values(self.UPNS, self.IDS, synthetic=False)
        assert live["persona:anna"] == self.UPNS[1]
        assert live["persona:anna.id"] == self.IDS["anna"]
        assert live["persona:anna.name"] == "Anna Meier"
        assert "persona:tom.id" not in live

    def test_a_replay_gets_the_synthetic_address_and_the_id_the_mapper_makes(self) -> None:
        replay = persona_values(self.UPNS, self.IDS, synthetic=True)
        assert replay["persona:anna"] == "anna@example.test"
        assert replay["persona:anna.id"] == mapped_guid(self.IDS["anna"])
        assert self.UPNS[1] not in json.dumps(replay)

    def test_a_placeholder_is_replaced_in_text_lists_and_objects(self) -> None:
        live = persona_values(self.UPNS, self.IDS, synthetic=False)
        step = {
            "args": {"members": [{"user_id": "persona:anna.id", "name": "persona:anna.name"}]},
            "bind": {"membership_id": "$prev.members[email=persona:anna].membership_id"},
        }
        done = cast("Json", with_personas(step, live))
        assert select(done, "args.members[0].user_id") == self.IDS["anna"]
        assert select(done, "bind.membership_id") == (
            f"$prev.members[email={self.UPNS[1]}].membership_id"
        )

    @pytest.mark.parametrize("placeholder", ["persona:bob", "persona:tom.id", "persona:anna.mail"])
    def test_a_placeholder_for_nobody_or_for_an_unread_id_stops_the_run(
        self, placeholder: str
    ) -> None:
        with pytest.raises(Refused, match="names no test user"):
            _ = with_personas(
                {"x": placeholder}, persona_values(self.UPNS, self.IDS, synthetic=False)
            )

    def test_only_an_id_placeholder_makes_the_recorder_read_the_test_users(self) -> None:
        def plan(step: Json) -> Plan:
            return Plan("p", "rec-p", (step,))

        assert uses_ids(plan({"args": {"m": [{"user_id": "persona:anna.id"}]}}))
        assert not uses_ids(plan({"args": {"recipients": ["persona:anna"]}}))
        assert not uses_ids(plan({"args": {"name": "persona:anna.name"}}))


class TestPreflightPeople:
    ANNA: ClassVar[str] = "4c1e8b2a-7d3f-4a96-b5e0-9f2d1c6a8e37"
    TOM: ClassVar[str] = "9a7b3d5e-1c2f-4e48-8d6a-0b5c4e3f2a19"

    def answer(self, path: str) -> dict[str, object]:
        users = {stand_in.UPNS[1]: self.ANNA, stand_in.UPNS[2]: self.TOM}
        fixed: dict[str, dict[str, object]] = {
            "/v1.0/me": {
                "id": stand_in.USER_ID,
                "userPrincipalName": stand_in.UPN,
                "mail": stand_in.UPN,
                "displayName": "Tester",
            },
            "/v1.0/organization": {
                "value": [{"id": stand_in.TENANT_ID, "displayName": "Org", "verifiedDomains": []}]
            },
            "/v1.0/me/drive": {"id": stand_in.DRIVE_ID},
        }
        wanted = unquote(path).removesuffix("?$select=id")
        return fixed.get(wanted.split("?")[0]) or {"id": users[wanted.rsplit("/", 1)[1]]}

    def run(self, *, people: bool) -> tuple[Guard, tuple[Identities, dict[str, str]], list[str]]:
        asked: list[str] = []

        async def send(_: httpx.AsyncBaseTransport, request: httpx.Request) -> httpx.Response:
            asked.append(unquote(request.url.path))
            return httpx.Response(200, json=self.answer(request.url.raw_path.decode()))

        guard = Guard(stand_in.UPN, frozenset(stand_in.UPNS), False)
        found = asyncio.run(
            preflight(send, httpx.AsyncHTTPTransport(), guard, "t", stand_in.UPNS, people=people)
        )
        return guard, found, asked

    def test_the_other_test_users_are_read_only_when_a_case_needs_their_ids(self) -> None:
        guard, (identities, ids), asked = self.run(people=True)
        assert ids == {"mia": stand_in.USER_ID, "anna": self.ANNA, "tom": self.TOM}
        assert guard.people == {stand_in.USER_ID, self.ANNA, self.TOM}
        assert {self.ANNA, self.TOM} <= identities.values
        assert [p for p in asked if "/users/" in p] == [
            f"/v1.0/users/{stand_in.UPNS[1]}",
            f"/v1.0/users/{stand_in.UPNS[2]}",
        ]

    def test_no_other_user_is_read_when_no_case_needs_an_id(self) -> None:
        guard, (_, ids), asked = self.run(people=False)
        assert ids == {"mia": stand_in.USER_ID}
        assert guard.people == {stand_in.USER_ID}
        assert not [p for p in asked if "/users/" in p]


class TestCasesWithPlaceholders:
    CASE: ClassVar[str] = (
        "outlook_list_mail-x:\n  chain:\n    - tool: outlook_list_mail\n"
        + "      args: {folder: inbox, from_address: persona:anna, limit: 3}\n"
    )

    def test_a_case_runs_with_the_real_address_and_replays_with_the_synthetic_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        resolved: list[object] = []
        original = record_module.with_personas

        def spying(value: object, values: Mapping[str, str]) -> object:
            resolved.append(done := original(value, values))
            return done

        monkeypatch.setattr(record_module, "with_personas", spying)
        _ = (tmp_path / "f.yaml").write_text(self.CASE)
        outcome = record_on(resolve("outlook_list_mail-x", cases=tmp_path))
        steps = [
            cast("Json", one) for one in resolved if isinstance(one, Mapping) and "args" in one
        ]
        asked = [select(one, "args.from_address") for one in steps]
        assert asked == [stand_in.UPNS[1], "anna@example.test"]
        assert outcome.unmet == []
        assert stand_in.UPNS[1] not in str(outcome.fixture.metadata)
        assert "persona:anna" in str(outcome.fixture.metadata["literals"])

    def test_a_case_with_a_placeholder_for_nobody_is_refused_before_any_request(
        self, tmp_path: Path
    ) -> None:
        _ = (tmp_path / "f.yaml").write_text(self.CASE.replace("persona:anna", "persona:bob"))
        with pytest.raises(Refused, match="persona:bob names no test user"):
            _ = record_on(resolve("outlook_list_mail-x", cases=tmp_path))


class TestOneNoteCases:
    def test_the_scrubbed_page_gives_read_resource_an_address_it_accepts_and_maps_alike(
        self,
    ) -> None:
        src = attribute_in(page_text(page_files()), "img[src]")
        assert (found := resource_id_in(src)) is not None
        assert found == unquote(urlsplit(src).path.split("/")[-2])
        assert RESOURCE not in src
        assert owner_of_graph_url(src) is None

    def test_the_two_cases_read_the_gallery_page_and_the_picture_from_its_markup(self) -> None:
        page, picture = (resolve(f"onenote_read_{one}-gallery") for one in ("page", "resource"))
        assert [tool_of(step) for step in page.steps][-1] == "onenote_read_page"
        assert [tool_of(step) for step in picture.steps][-2:] == [
            "onenote_read_page",
            "onenote_read_resource",
        ]
        assert mapping(picture.steps[-1]["bind"])["resource"] == "$prev.html~img[src]"
        assert page.needs == picture.needs == ("onenote_seed",)


BIG_LABEL = "seed-v1 Big page"
BIG_SIZE = 400_000
BIG = Corpus(
    "seed-v1",
    frozenset({BIG_LABEL}),
    frozenset({"a" * 64}),
    (Persona("anna", 2, "Anna Meier"),),
    normalized(BIG_LABEL),
    {
        "a" * 64: {
            "generator": "onenote-html",
            "size": 900_000,
            "label": BIG_LABEL,
            "sha256": "a" * 64,
        }
    },
)


def big_files(text: str) -> dict[str, bytes]:
    markup = f"<html><head><title>{BIG_LABEL}</title></head><body><p>{text}</p></body></html>"
    path = f"/v1.0/me/onenote/pages/{PAGE_ID}/content"
    recording = Recording(
        "page-scrub",
        "rec-tool-page-scrub",
        "stand-in",
        datetime(2026, 10, 29, tzinfo=UTC),
        (hop(path, markup.encode(), "text/html"),),
        Identities(frozenset({stand_in.USER_ID, stand_in.UPN}), "token"),
        {stand_in.UPN.casefold(): "mia"},
        frozenset(),
    )
    return files_of(scrub(recording, BIG))


class TestBigPage:
    def test_a_text_node_that_the_generator_made_is_stored_as_a_stub_and_comes_back_whole(
        self, tmp_path: Path
    ) -> None:
        text = generate("filler-text", BIG_SIZE, BIG_LABEL).decode()
        files = big_files(text)
        shown = page_text(files)
        assert len(shown) < 1000
        assert f"&lt;generated:filler-text:{BIG_SIZE}:{BIG_LABEL}&gt;" in shown
        assert lint_files(files, {stand_in.USER_ID, stand_in.UPN}, BIG) == []
        _ = (tmp_path / "page.html").write_bytes(files["bodies/rec-tool-page-scrub.01.html"])
        replayed = response({"body": "page.html", "status": 200}, tmp_path)
        assert text in replayed.text

    def test_a_large_text_node_that_the_generator_did_not_make_is_replaced(self) -> None:
        shown = page_text(big_files("x" * BIG_SIZE))
        assert "generated:" not in shown
        assert "synthetic text 01" in shown

    def test_a_stub_for_a_label_that_the_corpus_lacks_fails_the_lint(self) -> None:
        files = big_files(generate("filler-text", BIG_SIZE, BIG_LABEL).decode())
        name = "bodies/rec-tool-page-scrub.01.html"
        files[name] = files[name].replace(BIG_LABEL.encode() + b"&gt;", b"other&gt;")
        found = lint_files(files, {stand_in.USER_ID}, BIG)
        assert any("not corpus text" in line for line in found)
