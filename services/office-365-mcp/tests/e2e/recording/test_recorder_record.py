import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
import yaml
from fastmcp import FastMCP

import tests.e2e.test_scenarios as runner
from tests.conftest import RecordedSleeps
from tests.e2e.recording import stand_in
from tests.e2e.recording.conftest import SCENARIOS, Recorded, record_on
from tests.e2e.recording.drift import differences, stored
from tests.e2e.recording.drift import main as drift_main
from tests.e2e.recording.guard import Refused
from tests.e2e.recording.record import RECORDED, Plan, link, main, resolve
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


def test_a_search_without_a_hit_is_refused_with_advice() -> None:
    with pytest.raises(Refused, match="wait for the search index"):
        record_on("uc-01-06", StandIn(variants=frozenset({"unindexed"})))


def test_drift_exits_1_on_a_changed_field_type(
    recorded: Recorded, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = ["uc-02-01", "--target", "stand-in", "--out", str(recorded.out)]
    assert drift_main(arguments) == 0
    assert drift_main([*arguments, "--stand-in-variant", "drift"]) == 1
    assert '+  "totalItemCount": "29",' in capsys.readouterr().out


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
