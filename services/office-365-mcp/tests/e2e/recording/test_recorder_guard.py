import json
import subprocess
import sys

import httpx
import pytest

from office_365_mcp.tools import TOOL_NAMES
from tests.e2e.recording.guard import (
    PREFLIGHT,
    READ_TOOLS,
    WRITE_TOOLS,
    Guard,
    foreign_address,
)
from tests.e2e.recording.record import check, describe, main, resolve
from tests.e2e.recording.stand_in import DOMAIN, DRIVE_ID, UPN, USER_ID
from tests.e2e.test_scenarios import Json

ALLOWED = frozenset({DOMAIN})
SEED_MESSAGE = "AAMkSEED"
FOREIGN_MESSAGE = "AAMkFOREIGN"

CALL_PLANTS: dict[str, tuple[str, dict[str, object], str | None]] = {
    "C1 display-name syntax": (
        "outlook_draft_mail",
        {"to": ["Jonas <jonas@evil.com>"]},
        "outside the allowed domain",
    ),
    "C2a upper-case foreign": (
        "outlook_draft_mail",
        {"to": ["x@EVIL.COM"]},
        "outside the allowed domain",
    ),
    "C2b look-alike suffix": (
        "outlook_draft_mail",
        {"to": [f"x@{DOMAIN}.evil.com"]},
        "outside the allowed domain",
    ),
    "C2c upper-case allowed": ("outlook_draft_mail", {"to": [f"x@{DOMAIN.upper()}"]}, None),
    "C2d Cyrillic homoglyph": (
        "outlook_draft_mail",
        {"to": [f"x@{DOMAIN.replace('o', 'о', 1)}"]},
        "outside the allowed domain",
    ),
    "C2e IDN domain": ("outlook_draft_mail", {"to": ["x@évil.com"]}, "outside the allowed domain"),
    "C2f quoted local part": (
        "outlook_draft_mail",
        {"to": ['"jonas"@evil.com']},
        "outside the allowed domain",
    ),
    "C2g IP literal": ("outlook_draft_mail", {"to": ["jonas@[203.0.113.5]"]}, "holds an"),
    "C2h full-width at": (
        "outlook_draft_mail",
        {"to": ["jonas＠evil.com"]},
        "outside the allowed domain",
    ),
    "C2i small form at": (
        "outlook_draft_mail",
        {"to": ["jonas﹫evil.com"]},
        "outside the allowed domain",
    ),
    "C2j percent-encoded at": (
        "outlook_draft_mail",
        {"to": ["jonas%40evil.com"]},
        "outside the allowed domain",
    ),
    "C2k double percent-encoded": (
        "outlook_draft_mail",
        {"to": ["jonas%2540evil.com"]},
        "outside the allowed domain",
    ),
    "C2l HTML entity at": (
        "outlook_draft_mail",
        {"subject": "jonas&#64;evil.com"},
        "outside the allowed domain",
    ),
    "C2m folded address": (
        "outlook_draft_mail",
        {"body": "jonas.huber\r\n @evil.com"},
        "outside the allowed domain",
    ),
    "C3a cc nested object": (
        "outlook_draft_mail",
        {"cc": [{"address": "x@evil.com"}]},
        "outside the allowed domain",
    ),
    "C3b attendees in-domain": (
        "outlook_create_event",
        {"subject": "s", "attendees": [f"ceo@{DOMAIN}"]},
        "would invite",
    ),
    "C3c location in-domain": (
        "outlook_create_event",
        {"subject": "s", "location": f"ceo@{DOMAIN}"},
        None,
    ),
    "C3d online meeting": (
        "outlook_create_event",
        {"subject": "s", "online_meeting": True},
        "would invite",
    ),
    "C3e rooms": (
        "outlook_create_event",
        {"subject": "s", "room_addresses": [f"r@{DOMAIN}"]},
        "would invite",
    ),
    "C4a write not on the list": (
        "outlook_forward_event",
        {"uri": "x", "to": [f"a@{DOMAIN}"]},
        "not on the read or the write allowlist",
    ),
    "C4b anonymous share link": (
        "sharepoint_create_share_link",
        {"item": "x", "audience": "anyone"},
        "not on the read or the write allowlist",
    ),
    "C4c auto-reply": (
        "outlook_set_automatic_reply",
        {"status": "alwaysEnabled"},
        "not on the read or the write allowlist",
    ),
    "C4d Teams message": (
        "teams_send_chat_message",
        {"chat_id": "19:x", "message": "hi"},
        "not on the read or the write allowlist",
    ),
    "C6 another mailbox (write)": (
        "outlook_move_mail",
        {"message_refs": ["x"], "destination": "archive", "mailbox": f"ceo@{DOMAIN}"},
        "args.mailbox",
    ),
    "C6b another mailbox (read)": (
        "outlook_list_mail",
        {"mailbox": f"ceo@{DOMAIN}"},
        "args.mailbox",
    ),
    "C6c directory search": (
        "outlook_find_recipient",
        {"query": "a"},
        "not on the read or the write allowlist",
    ),
    "C6d free/busy": (
        "outlook_check_availability",
        {"addresses": [f"ceo@{DOMAIN}"]},
        "not on the read or the write allowlist",
    ),
    "C6e mail search": (
        "outlook_search_mail",
        {"query": "budget"},
        "not on the read or the write allowlist",
    ),
    "C6f own mailbox by name": ("outlook_list_mail", {"mailbox": UPN.upper()}, None),
}


def guard(*, allow_writes: bool = True, cap: int = 40) -> Guard:
    made = Guard(UPN, ALLOWED, allow_writes, cap, me_id=USER_ID, drive_ids=frozenset({DRIVE_ID}))
    made.seen_seed.add(SEED_MESSAGE)
    return made


def graph(method: str, path: str, body: object = None, **headers: str) -> httpx.Request:
    content = json.dumps(body).encode() if body is not None else b""
    return httpx.Request(
        method, f"https://graph.microsoft.com{path}", content=content, headers=headers
    )


REQUEST_PLANTS: dict[str, tuple[httpx.Request, str, str | None]] = {
    "R1 move in another mailbox": (
        graph(
            "POST",
            f"/v1.0/users/ceo@{DOMAIN}/messages/{SEED_MESSAGE}/move",
            {"destinationId": "archive"},
        ),
        "outlook_move_mail",
        "outside /v1.0/me/",
    ),
    "R2 IDN recipient in the body": (
        graph(
            "POST",
            "/v1.0/me/messages",
            {"toRecipients": [{"emailAddress": {"address": "x@évil.com"}}]},
        ),
        "outlook_draft_mail",
        "outside the allowed domain",
    ),
    "R3 quoted local part in the body": (
        graph(
            "POST",
            "/v1.0/me/messages",
            {"toRecipients": [{"emailAddress": {"address": '"x"@evil.com'}}]},
        ),
        "outlook_draft_mail",
        "outside the allowed domain",
    ),
    "R4 allowed tool, unrelated write": (
        graph(
            "PATCH",
            "/v1.0/me/mailboxSettings",
            {"automaticRepliesSetting": {"status": "alwaysEnabled"}},
        ),
        "outlook_mark_mail",
        "not a write path of outlook_mark_mail",
    ),
    "R5 free/busy of another user": (
        graph(
            "POST",
            f"/v1.0/users/ceo@{DOMAIN}/calendar/getSchedule",
            {"schedules": [f"ceo@{DOMAIN}"]},
        ),
        "outlook_list_events",
        "outside /v1.0/me/",
    ),
    "R6 a write from a read tool": (
        graph("POST", "/v1.0/me/sendMail", {}),
        "outlook_list_mail",
        "a write that outlook_list_mail may not make",
    ),
    "R7 another user's drive": (
        graph("GET", "/v1.0/drives/b!other/items/01X"),
        "sharepoint_read_file",
        "outside /v1.0/me/",
    ),
    "R8 search from a mail tool": (
        graph("POST", "/v1.0/search/query", {}),
        "outlook_list_mail",
        "outside /v1.0/me/",
    ),
    "R9 move of a foreign message": (
        graph("POST", f"/v1.0/me/messages/{FOREIGN_MESSAGE}/move", {"DestinationId": "archive"}),
        "outlook_move_mail",
        "did not read as seed data",
    ),
    "R10 move into a foreign folder": (
        graph("POST", f"/v1.0/me/messages/{SEED_MESSAGE}/move", {"DestinationId": "AAMkFOLDER"}),
        "outlook_move_mail",
        "did not read as seed data",
    ),
    "R11 address in the filter": (
        graph("GET", "/v1.0/me/messages?$filter=from/emailAddress/address eq 'x%40evil.com'"),
        "outlook_list_mail",
        "outside the allowed domain",
    ),
    "R12 plain http": (
        httpx.Request("GET", "http://graph.microsoft.com/v1.0/me"),
        "outlook_list_mail",
        "does not use https",
    ),
    "R13 own mailbox by id": (
        graph("GET", f"/v1.0/users/{USER_ID}/mailFolders/inbox"),
        "outlook_list_mail",
        None,
    ),
    "R14 own drive": (
        graph("GET", f"/v1.0/drives/{DRIVE_ID}/items/01X"),
        "sharepoint_read_file",
        None,
    ),
    "R15 seed move into a well-known folder": (
        graph("POST", f"/v1.0/me/messages/{SEED_MESSAGE}/move", {"DestinationId": "archive"}),
        "outlook_move_mail",
        None,
    ),
}


@pytest.mark.parametrize("plant", CALL_PLANTS)
def test_a_red_team_call_plant_gets_its_verdict(plant: str) -> None:
    tool, args, expected = CALL_PLANTS[plant]
    refusal = guard().refuses_call(tool, args)
    if expected is None:
        assert refusal is None
    else:
        assert refusal is not None and expected in refusal, refusal


@pytest.mark.parametrize("plant", REQUEST_PLANTS)
def test_a_red_team_request_plant_gets_its_verdict(plant: str) -> None:
    request, tool, expected = REQUEST_PLANTS[plant]
    refusal = guard().refuses_request(request, tool)
    if expected is None:
        assert refusal is None
    else:
        assert refusal is not None and expected in refusal, refusal


def test_every_allowlisted_tool_exists() -> None:
    assert (READ_TOOLS | set(WRITE_TOOLS)) <= set(TOOL_NAMES)


def test_a_write_needs_allow_writes() -> None:
    assert guard(allow_writes=False).refuses_call("outlook_move_mail", {}) == (
        "outlook_move_mail is a write and needs --allow-writes"
    )
    request = graph("POST", f"/v1.0/me/messages/{SEED_MESSAGE}/move", {"DestinationId": "archive"})
    refusal = guard(allow_writes=False).refuses_request(request, "outlook_move_mail")
    assert refusal is not None and "may not make here" in refusal


def test_the_preflight_reads_only_its_three_paths() -> None:
    assert guard().refuses_request(graph("GET", "/v1.0/organization"), PREFLIGHT) is None
    refusal = guard().refuses_request(graph("GET", "/v1.0/me/messages"), PREFLIGHT)
    assert refusal is not None
    assert guard().refuses_request(graph("GET", "/v1.0/organization"), "outlook_list_mail")


def test_a_hop_to_another_host_must_be_the_redirect_and_carry_no_token() -> None:
    location = "https://northwindlab-my.sharepoint.com/personal/x/_layouts/15/download.aspx?a=1"
    made = guard()
    made.saw(graph("GET", "/v1.0/me/drive/items/1/content"), 302, location, None)
    with_token = httpx.Request("GET", location, headers={"authorization": "Bearer x"})
    assert made.refuses_request(with_token, "sharepoint_read_file") == (
        "a request to northwindlab-my.sharepoint.com carries an Authorization header"
    )
    elsewhere = httpx.Request("GET", "https://northwindlab-my.sharepoint.com/other")
    assert made.refuses_request(elsewhere, "sharepoint_read_file") is not None
    assert made.refuses_request(httpx.Request("GET", location), "sharepoint_read_file") is None
    evil = httpx.Request("GET", "https://evil.example/x")
    made.saw(graph("GET", "/v1.0/me/drive/items/1/content"), 302, str(evil.url), None)
    assert made.refuses_request(evil, "sharepoint_read_file") is not None


def test_the_cap_stops_the_run() -> None:
    made = guard(cap=2)
    assert (
        made.refuses_request(graph("GET", "/v1.0/me/mailFolders/inbox"), "outlook_list_mail")
        is None
    )
    assert (
        made.refuses_request(graph("GET", "/v1.0/me/mailFolders/inbox"), "outlook_list_mail")
        is None
    )
    refusal = made.refuses_request(graph("GET", "/v1.0/me/mailFolders/inbox"), "outlook_list_mail")
    assert refusal == "the cap of 2 requests for one run is reached"


def test_a_write_is_not_repeated_after_a_throttled_write() -> None:
    made = guard()
    move = graph("POST", f"/v1.0/me/messages/{SEED_MESSAGE}/move", {"DestinationId": "archive"})
    assert made.refuses_request(move, "outlook_move_mail") is None
    made.saw(move, 503, None, None)
    refusal = made.refuses_request(move, "outlook_move_mail")
    assert refusal is not None and "would repeat a write" in refusal


def test_a_seed_item_is_known_by_its_tag() -> None:
    made = guard()
    body: Json = {
        "value": [
            {"id": "AAMkA", "categories": ["seed-v1"]},
            {"id": "AAMkB", "categories": list[str]()},
        ]
    }
    made.saw(graph("GET", "/v1.0/me/messages"), 200, None, body)
    assert {"AAMkA", SEED_MESSAGE} == made.seen_seed


def test_an_address_check_is_quiet_on_text_without_an_at() -> None:
    assert foreign_address("Lunch on Friday?", ALLOWED) is None
    assert foreign_address(f"Mia <mia@{DOMAIN}>, tom@{DOMAIN}", ALLOWED) is None
    assert (
        foreign_address("Lunch @ noon", ALLOWED) == "an @ that is not part of one parseable address"
    )


def test_the_dry_run_plans_the_calls_and_shows_the_refusals() -> None:
    lines = describe(resolve("uc-05-16"), guard(allow_writes=False))
    assert lines == [
        "uc-05-16 -> cassette rec-uc-05-16 (dry run, nothing is sent):",
        '  step 1: outlook_list_mail({"category": "seed-v1", "limit": 3}) -> allowed',
        '  step 2: outlook_move_mail({"destination": "archive", "message_refs": '
        + '"$prev.messages[*].uri"}) -> REFUSED: outlook_move_mail is a write and needs '
        + "--allow-writes",
    ]
    assert check(resolve("uc-02-01"), guard(allow_writes=False)) == []


def test_the_dry_run_cli_needs_no_token(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GRAPH_TOKEN", raising=False)
    monkeypatch.setenv("SEED_UPNS", f"{UPN},tester1@{DOMAIN}")
    assert main(["uc-02-01", "--target", "graph", "--dry-run"]) == 0
    assert "step 1: outlook_list_mail" in capsys.readouterr().out
    assert main(["uc-05-16", "--target", "graph", "--dry-run"]) == 2
    assert main(["uc-05-16", "--target", "graph", "--dry-run", "--allow-writes"]) == 0


def test_the_guard_refuses_under_python_o() -> None:
    script = (
        "import httpx\n"
        "from tests.e2e.recording.guard import Guard\n"
        f"g = Guard({UPN!r}, frozenset({{{DOMAIN!r}}}), True)\n"
        "print(g.refuses_call('outlook_draft_mail', {'to': ['x＠evil.com']}))\n"
        "print(g.refuses_call('outlook_list_mail', {'mailbox': 'ceo@x.ch'}))\n"
        "print(g.refuses_request(httpx.Request('POST', 'https://graph.microsoft.com/v1.0/me/"
        "messages/AAMkX/move', json={'DestinationId': 'archive'}), 'outlook_move_mail'))\n"
        "print(g.refuses_request(httpx.Request('GET', 'https://evil.example/x'), 'x'))\n"
    )
    finished = subprocess.run(
        [sys.executable, "-O", "-c", script], capture_output=True, text=True, check=False
    )
    lines = finished.stdout.splitlines()
    assert finished.returncode == 0, finished.stderr[-2000:]
    assert len(lines) == 4 and "None" not in lines, lines
