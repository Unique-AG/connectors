import asyncio
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import httpx
import pytest
import yaml
from fastmcp import FastMCP

import tests.e2e.recording.record as record_module
import tests.e2e.test_scenarios as runner
from tests.conftest import RecordedSleeps
from tests.e2e.recording import stand_in
from tests.e2e.recording.conftest import SCENARIOS, Recorded, record_on
from tests.e2e.recording.drift import differences, stored
from tests.e2e.recording.drift import main as drift_main
from tests.e2e.recording.guard import Guard, Refused
from tests.e2e.recording.record import (
    GRAPH,
    RECORDED,
    Plan,
    Recorder,
    check,
    guard_for,
    link,
    main,
    persona_guards,
    preflight,
    replay_check,
    resolve,
)
from tests.e2e.recording.scrub import files_of
from tests.e2e.recording.stand_in import StandIn
from tests.e2e.test_scenarios import Json, build_server, entries, mapping

SERVICE = Path(__file__).parents[3]


def variant_of(scenario: str) -> Json:
    return mapping(mapping(cast("object", yaml.safe_load(RECORDED.read_text())))[scenario])


@pytest.fixture(scope="module")
def server() -> FastMCP[None]:
    return build_server()


@pytest.mark.parametrize("scenario", SCENARIOS)
async def test_a_recorded_fixture_replays_through_the_repo_runner(
    recorded: Recorded,
    scenario: str,
    server: FastMCP[None],
    retry_sleeps: RecordedSleeps,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner.patch_obo(monkeypatch)
    monkeypatch.setattr(runner, "HERE", recorded.out)
    entry = dict(entries())[scenario]
    await runner.test_the_scenario_runs_as_its_sidecar_says(
        entry, variant_of(scenario), server, retry_sleeps
    )


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_a_second_record_gives_the_same_files(recorded: Recorded, scenario: str) -> None:
    again = record_on(scenario)
    fixture = recorded.outcomes[scenario].fixture.name
    assert differences(stored(fixture, recorded.out), files_of(again.fixture)) == []


def test_the_recorder_reports_its_replacements(recorded: Recorded) -> None:
    report = recorded.outcomes["uc-02-01"].report
    assert report[0] == (
        "uc-02-01: 4 requests -> 4 interactions, 4 bodies, lint clean, replay clean"
    )
    counts = recorded.outcomes["uc-02-01"].fixture.counts
    assert counts["text replaced"] >= 6
    assert counts["other addresses replaced"] >= 3
    assert "tool output changed by the scrub: replaced" in report[2]


def test_an_expect_on_a_replaced_field_is_refused() -> None:
    plan = resolve("uc-02-01")
    step = dict(plan.steps[0])
    step["expect"] = {"result": {"messages[*].subject": []}}
    with pytest.raises(Refused, match="asserts on fields the scrub replaced") as refused:
        _ = record_on(replace(plan, steps=(step,)))
    assert "messages[*].subject reads messages[" in str(refused.value)
    assert "(replaced)" in str(refused.value)


def test_a_lint_refusal_keeps_the_scrubbed_candidate_for_inspection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

    def leaking(*_: object) -> list[str]:
        return ["bodies/x.json at value[0].id: a GUID"]

    monkeypatch.setattr(record_module, "lint_files", leaking)
    with pytest.raises(Refused, match=r"at value\[0\]\.id: a GUID"):
        _ = record_on("uc-02-01", refused=tmp_path)
    kept = tmp_path / "uc-02-01"
    assert kept.stat().st_mode & 0o777 == 0o700
    assert sorted(p.name for p in (kept / "fixtures").glob("*.json"))[0] == "rec-uc-02-01.json"
    held = cast("list[Json]", json.loads((kept / "fixtures" / "rec-uc-02-01.json").read_text()))
    assert sum("response_json" in one for one in held) == 4
    assert stand_in.TOKEN not in "".join(p.read_text() for p in kept.rglob("*.json"))


def test_a_replay_refusal_keeps_the_candidate_and_names_the_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded: Recorded, server: FastMCP[None]
) -> None:
    fixture = recorded.outcomes["uc-02-01"].fixture
    extra = {"method": "DELETE", "path": "/v1.0/me/never", "status": 204}
    unused = replace(fixture, interactions=[*fixture.interactions, extra])
    _, broken, _ = asyncio.run(replay_check(resolve("uc-02-01"), unused, server, {}))
    assert broken == ["interaction 5 (DELETE /v1.0/me/never) is never reached on replay"]

    async def failing(*_: object) -> tuple[list[object], list[str], list[str]]:
        return [], broken, []

    monkeypatch.setattr(record_module, "replay_check", failing)
    with pytest.raises(Refused, match=r"interaction 5 \(DELETE /v1.0/me/never\)"):
        _ = record_on("uc-02-01", refused=tmp_path)
    assert (tmp_path / "uc-02-01" / "fixtures" / "rec-uc-02-01.json").is_file()


def test_a_later_success_deletes_the_refused_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stale = tmp_path / "refused" / "uc-02-01"
    stale.mkdir(parents=True)
    _ = (stale / "old.json").write_text("{}")
    monkeypatch.setattr(record_module, "REFUSED", tmp_path / "refused")
    assert main(["uc-02-01", "--target", "stand-in", "--out", str(tmp_path / "out")]) == 0
    assert not stale.exists()


def test_an_expect_that_does_not_hold_is_reported() -> None:
    plan = resolve("uc-02-01")
    step = dict(plan.steps[0])
    step["expect"] = {"result": {"capped": True}}
    outcome = record_on(replace(plan, steps=(step,)))
    assert outcome.unmet == ["step 1: capped is False, the variant expects True"]


def test_a_write_needs_allow_writes() -> None:
    graph = StandIn()
    with pytest.raises(Refused, match="outlook_move_mail is a write and needs --allow-writes"):
        _ = record_on("uc-05-16", graph, allow_writes=False)
    assert graph.seen == []


def test_another_mailbox_is_refused_before_any_request() -> None:
    step: Json = {
        "tool": "outlook_move_mail",
        "args": {"destination": "archive", "mailbox": f"ceo@{stand_in.DOMAIN}"},
    }
    graph = StandIn()
    with pytest.raises(Refused, match="refused before any request"):
        _ = record_on(Plan("c6", "rec-c6", (step,)), graph)
    assert graph.seen == []


def test_a_move_of_a_foreign_message_is_refused_before_it_is_sent() -> None:
    steps: tuple[Json, ...] = (
        {"tool": "outlook_list_mail", "args": {"unread_only": True, "received_after": "yesterday"}},
        {
            "tool": "outlook_move_mail",
            "args": {"destination": "archive"},
            "bind": {"message_refs": "$prev.messages[*].uri"},
        },
    )
    graph = StandIn()
    with pytest.raises(Refused, match="did not read as seed data"):
        _ = record_on(Plan("foreign-move", "rec-foreign-move", steps), graph)
    moved = [seen for seen in graph.seen if seen.endswith("/move")]
    foreign = [stand_in.exchange_id(b"\x00\x03\x24\x00", n) for n in (900, 901, 902)]
    assert moved and not any(one in seen for seen in moved for one in foreign)


def test_a_token_of_another_user_is_refused() -> None:
    graph = StandIn()
    with pytest.raises(Refused, match="GET /me does not answer SEED_UPNS position 1"):
        _ = record_on("uc-02-01", graph, upns=(f"someone@{stand_in.DOMAIN}",))
    assert graph.seen == ["GET graph.microsoft.com/v1.0/me"]


def test_a_step_as_another_persona_without_its_token_is_refused_before_any_request() -> None:
    graph = StandIn()
    with pytest.raises(Refused, match="no token for persona 2"):
        _ = record_on(Plan("as", "rec-as", ({"tool": "get_me", "as": 2},)), graph)
    assert graph.seen == []


def test_a_step_as_a_persona_outside_the_three_is_refused(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    cases.mkdir()
    _ = (cases / "x.yaml").write_text("x-one:\n  chain:\n    - tool: get_me\n      as: 4\n")
    with pytest.raises(Refused, match="step 1 runs as a persona outside 1..3"):
        _ = resolve("x-one", cases=cases)


def test_a_token_of_the_wrong_user_for_a_step_persona_is_refused_before_a_step_runs() -> None:
    graph = StandIn()
    with pytest.raises(Refused, match="GET /me does not answer SEED_UPNS position 2"):
        _ = record_on(
            Plan("as", "rec-as", ({"tool": "get_me"}, {"tool": "get_me", "as": 2})),
            graph,
            others={2: stand_in.TOKEN},
        )
    assert {seen.rpartition("/")[2] for seen in graph.seen} <= {"me", "organization", "drive"}


def test_each_step_runs_with_the_token_of_its_persona() -> None:
    other = "eyJ0eXAiOiJKV1QifQ.eyJ1cG4iOiJhbm5hIn0.b3RoZXItdG9rZW4"
    steps: tuple[Json, ...] = ({"tool": "get_me"}, {"tool": "get_me", "as": 2}, {"tool": "get_me"})
    outcome = record_on(
        Plan("as", "rec-as", steps),
        StandIn(others={other: stand_in.UPNS[1]}),
        others={2: other},
    )
    answered = [
        mapping(one["response_json"])["userPrincipalName"] for one in outcome.fixture.interactions
    ]
    assert answered == ["mia@example.test", "anna@example.test", "mia@example.test"]


def test_a_transient_answer_is_never_recorded() -> None:
    with pytest.raises(Refused, match=r"transient answers \['503 GET'\]"):
        _ = record_on("uc-02-01", StandIn(frozenset({"retry"})))


def test_a_token_echoed_by_graph_is_never_printed_or_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(Refused) as refused:
        _ = record_on("uc-05-16", StandIn(frozenset({"echo"})))
    assert stand_in.TOKEN not in str(refused.value)
    assert stand_in.UPN not in str(refused.value)
    leaked = record_on("uc-02-01", StandIn(frozenset({"token-leak"})))
    written = b"".join(files_of(leaked.fixture).values())
    assert stand_in.TOKEN.encode() not in written
    assert main(["uc-02-01", "--target", "stand-in", "--out", str(tmp_path)]) == 0
    shown = capsys.readouterr()
    assert stand_in.TOKEN not in shown.out + shown.err
    assert stand_in.UPN not in shown.out + shown.err


def test_nothing_prints_the_tempauth_url_or_the_upn(recorded: Recorded) -> None:
    outcome = recorded.outcomes["uc-01-06"]
    shown = repr(outcome) + repr(outcome.recording) + repr(outcome.recording.hops)
    shown += repr(outcome.recording.identities)
    for secret in ("tempauth", stand_in.TOKEN, stand_in.UPN, stand_in.TENANT_ID):
        assert secret not in shown


def test_a_search_without_a_hit_is_refused_and_names_the_empty_list() -> None:
    with pytest.raises(
        Refused, match=r"step 2 binds .* does not have: \$prev\.\S+ reads an empty list"
    ):
        record_on("uc-01-06", StandIn(variants=frozenset({"unindexed"})))


ANSWERS: list[tuple[list[object], str, str]] = [
    ([{"channels": []}], "$prev.channels[0].id", "reads an empty list"),
    ([{"channels": [{"id": "a"}]}], "$1.channels[0].name", "reads no value"),
    ([{"other": 1}], "$prev.channels[0].id", "reads no value"),
    ([{"channels": []}], "$9.channels[0].id", "reads no value"),
]


@pytest.mark.parametrize(("results", "selector", "said"), ANSWERS)
def test_a_bind_that_finds_nothing_names_its_selector(
    results: list[object], selector: str, said: str
) -> None:
    assert record_module.unbound({"id": selector}, results) == f"{selector} {said}"


def test_a_literal_with_a_day_symbol_is_also_a_literal_in_its_resolved_form() -> None:
    steps: tuple[Json, ...] = (
        {"tool": "t", "args": {"name": "seed-v1 case-x ~today", "n": "$prev.a"}},
    )
    day = datetime.now(UTC).date().isoformat()
    assert Plan("s", "f", steps).literals == {"seed-v1 case-x ~today", f"seed-v1 case-x {day}"}


def test_a_family_gap_is_the_default_gap_of_its_cases_and_a_case_gap_wins(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    cases.mkdir()
    _ = (cases / "x.yaml").write_text(
        "a-one:\n  chain:\n    - tool: onenote_list_notebooks\n"
        + "a-two:\n  gap: 3\n  chain:\n    - tool: onenote_list_notebooks\n"
        + "a-three:\n  chain:\n    - tool: outlook_list_mail\n"
    )
    assert [resolve(name, cases=cases).gap for name in ("a-one", "a-two", "a-three")] == [20, 3, 0]


def test_a_selector_with_a_field_test_covers_any_index_of_its_list() -> None:
    covered = record_module.covers("teams[display_name=seed-v1 team].team_id")
    assert covered.fullmatch("teams[3].team_id") is not None
    assert covered.fullmatch("teams.team_id") is None


def test_drift_exits_1_on_a_changed_field_type(
    recorded: Recorded, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = ["uc-02-01", "--target", "stand-in", "--out", str(recorded.out)]
    assert drift_main(arguments) == 0
    assert drift_main([*arguments, "--stand-in-variant", "drift"]) == 1
    assert '+      "totalItemCount": "29",' in capsys.readouterr().out


def test_the_cli_records_and_refuses_under_python_o(tmp_path: Path) -> None:
    command = [sys.executable, "-O", "-m", "tests.e2e.recording.record"]
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join(["src", "."])}
    recorded = subprocess.run(
        [*command, "uc-02-01", "--target", "stand-in", "--out", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        cwd=SERVICE,
        env=environment,
    )
    assert recorded.returncode == 0, recorded.stderr[-2000:]
    assert "lint clean, replay clean" in recorded.stdout
    refused = subprocess.run(
        [*command, "uc-05-16", "--target", "stand-in", "--out", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        cwd=SERVICE,
        env=environment,
    )
    assert refused.returncode == 2
    assert "outlook_move_mail is a write and needs --allow-writes" in refused.stderr


def test_a_failing_step_stops_the_chain_under_python_o(tmp_path: Path) -> None:
    failed = subprocess.run(
        [
            sys.executable,
            "-O",
            "-W",
            "ignore",
            "-m",
            "tests.e2e.recording.record",
            "onenote_list_notebooks-seed",
            "--target",
            "stand-in",
            "--allow-writes",
            "--out",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=SERVICE,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(["src", "."])},
    )
    assert failed.returncode == 2
    assert "step 1 failed while recording" in failed.stderr
    assert not list(tmp_path.rglob("*.json"))


async def test_a_send_that_raises_stops_every_later_write() -> None:
    seen = Guard(stand_in.UPN, frozenset(stand_in.UPNS), True)

    async def timed_out(_: httpx.AsyncBaseTransport, request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    recorder = Recorder(interactions=[], send=timed_out, guard=seen, token="t")
    token = f"Bearer {runner._OBO_TOKEN}"  # pyright: ignore[reportPrivateUsage]
    request = httpx.Request("GET", f"{GRAPH}/me", headers={"authorization": token})
    with pytest.raises(httpx.ReadTimeout):
        _ = await recorder.hop(httpx.AsyncBaseTransport(), request)
    assert seen.write_failed


def test_a_failed_write_of_one_persona_stops_the_writes_of_the_next() -> None:
    first = Guard(stand_in.UPN, frozenset(stand_in.UPNS), True)
    second = Guard(stand_in.UPNS[1], frozenset(stand_in.UPNS), True, counter=first.counter)

    write = httpx.Request("PATCH", f"{GRAPH}/drives/b!DRIVE/items/ITEM")
    before = second.refuses_request(write, "sharepoint_rename_item")
    first.write_failed = True
    after = second.refuses_request(write, "sharepoint_rename_item")

    assert "failed or throttled write" not in str(before)
    assert after is not None
    assert "failed or throttled write" in after


@pytest.mark.parametrize(
    ("status", "stops"), [(404, False), (403, False), (429, True), (503, True)]
)
def test_only_a_throttled_or_server_failed_answer_stops_the_later_writes(
    status: int, stops: bool
) -> None:
    seen = Guard(stand_in.UPN, frozenset(stand_in.UPNS), True)

    seen.saw(httpx.Request("PATCH", f"{GRAPH}/drives/b!DRIVE/items/ITEM"), status, None, None)

    assert seen.write_failed is stops


async def test_a_preflight_answers_without_a_drive() -> None:
    bodies = {
        "/v1.0/me": {"id": "u1", "userPrincipalName": stand_in.UPN, "displayName": "Tester"},
        "/v1.0/organization": {"value": [{"id": "o1", "displayName": "Org"}]},
    }

    async def send(_: httpx.AsyncBaseTransport, request: httpx.Request) -> httpx.Response:
        body = bodies.get(request.url.path)
        return httpx.Response(200 if body else 403, json=body or {}, request=request)

    seen = Guard(stand_in.UPN, frozenset(stand_in.UPNS), False)
    _ = await preflight(send, httpx.AsyncBaseTransport(), seen, "t", (stand_in.UPN,))
    assert seen.drive_ids == frozenset()
    assert seen.me_id == "u1"


@pytest.mark.parametrize(
    ("failing", "refused"),
    [("/v1.0/me", True), ("/v1.0/organization", True), ("/v1.0/me/drive", False)],
)
async def test_a_preflight_request_that_gets_a_503_refuses_the_case_except_the_drive(
    failing: str, refused: bool
) -> None:
    bodies = {
        "/v1.0/me": {"id": "u1", "userPrincipalName": stand_in.UPN, "displayName": "Tester"},
        "/v1.0/organization": {"value": [{"id": "o1", "displayName": "Org"}]},
        "/v1.0/me/drive": {"id": "d1"},
    }

    async def send(_: httpx.AsyncBaseTransport, request: httpx.Request) -> httpx.Response:
        if request.url.path == failing:
            return httpx.Response(503, json={}, request=request)
        return httpx.Response(200, json=bodies[request.url.path], request=request)

    seen = Guard(stand_in.UPN, frozenset(stand_in.UPNS), False)
    if refused:
        with pytest.raises(Refused, match="answered 503"):
            _ = await preflight(send, httpx.AsyncBaseTransport(), seen, "t", (stand_in.UPN,))
    else:
        _ = await preflight(send, httpx.AsyncBaseTransport(), seen, "t", (stand_in.UPN,))
        assert seen.drive_ids == frozenset()


_RECORDED_BLOCK = """\
uc-01-01:
  fixture: rec-uc-01-01
  1:
    expect:
      result: {capped: false}
"""
_NEXT = "\nuc-01-02:\n  status: untested\n"
_SIDECARS = {
    "no variants": "uc-01-01:\n  chain:\n    - tool: t\n" + _NEXT,
    "other variants": "uc-01-01:\n  variants:\n    busy:\n      1: {fault: {transport: timeout}}\n"
    + _NEXT,
    "old recorded variant": "uc-01-01:\n  variants:\n    recorded:\n      fixture: old\n" + _NEXT,
}


def _linkable(tmp_path: Path, sidecar: str) -> tuple[Path, Path, Path]:
    recorded, features = tmp_path / "recorded.calls.yaml", tmp_path / "features"
    features.mkdir()
    _ = recorded.write_text(_RECORDED_BLOCK)
    _ = (features / "01-x.calls.yaml").write_text(_SIDECARS[sidecar])
    return recorded, features, features / "01-x.calls.yaml"


@pytest.mark.parametrize("sidecar", _SIDECARS)
def test_link_puts_the_recorded_block_in_the_sidecar_entry(sidecar: str, tmp_path: Path) -> None:
    recorded, features, path = _linkable(tmp_path, sidecar)
    assert link("uc-01-01", recorded, features) == path
    loaded = mapping(cast("object", yaml.safe_load(path.read_text())))
    variants = mapping(mapping(loaded["uc-01-01"])["variants"])
    wanted = mapping(mapping(cast("object", yaml.safe_load(_RECORDED_BLOCK)))["uc-01-01"])
    assert mapping(variants["recorded"]) == wanted
    assert ("busy" in variants) == (sidecar == "other variants")
    assert loaded["uc-01-02"] == {"status": "untested"}


def test_link_twice_changes_nothing(tmp_path: Path) -> None:
    recorded, features, path = _linkable(tmp_path, "other variants")
    _ = link("uc-01-01", recorded, features)
    once = path.read_text()
    _ = link("uc-01-01", recorded, features)
    assert path.read_text() == once


def test_link_refuses_a_scenario_that_has_no_entry_or_no_block(tmp_path: Path) -> None:
    recorded, features, _ = _linkable(tmp_path, "no variants")
    with pytest.raises(Refused, match="has no block"):
        link("uc-01-02", recorded, features)
    _ = recorded.write_text(_RECORDED_BLOCK.replace("uc-01-01", "uc-09-09"))
    with pytest.raises(Refused, match="is not an entry"):
        link("uc-09-09", recorded, features)


def test_the_cli_refuses_link_for_a_stand_in_recording(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["uc-02-01", "--target", "stand-in", "--link"]) == 2
    assert "--link needs a graph recording" in capsys.readouterr().err


def test_the_request_cap_counts_the_steps_of_all_personas_together() -> None:
    other = "eyJ0eXAiOiJKV1QifQ.eyJ1cG4iOiJhbm5hIn0.b3RoZXItdG9rZW4"
    steps: tuple[Json, ...] = ({"tool": "get_me"}, {"tool": "get_me", "as": 2}, {"tool": "get_me"})
    with pytest.raises(Refused, match="cap of 8 requests"):
        _ = record_on(
            Plan("as", "rec-as", steps, cap=8),
            StandIn(others={other: stand_in.UPNS[1]}),
            others={2: other},
        )


def test_a_token_for_the_case_persona_in_others_never_replaces_the_validated_token() -> None:
    other = "eyJ0eXAiOiJKV1QifQ.eyJ1cG4iOiJhbm5hIn0.b3RoZXItdG9rZW4"
    outcome = record_on(
        Plan("as", "rec-as", ({"tool": "get_me"},)),
        StandIn(others={other: stand_in.UPNS[1]}),
        others={1: other},
    )
    answered = [
        mapping(one["response_json"])["userPrincipalName"] for one in outcome.fixture.interactions
    ]
    assert answered == ["mia@example.test"]


def test_a_step_is_checked_with_the_guard_of_its_persona() -> None:
    steps: tuple[Json, ...] = (
        {"tool": "outlook_list_mail", "as": 2, "args": {"mailbox": stand_in.UPNS[1]}},
    )
    plan = Plan("as", "rec-as", steps)
    guard = guard_for(stand_in.UPNS, plan, True, 40)

    assert check(plan, guard) != []
    assert check(plan, guard, by_persona=persona_guards(stand_in.UPNS, plan, guard)) == []
