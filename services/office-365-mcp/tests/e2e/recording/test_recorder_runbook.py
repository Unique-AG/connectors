import importlib.util
import json
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast, final

import httpx
import pytest

from tests.e2e.recording import runbook
from tests.e2e.recording.cases import case_entries
from tests.e2e.recording.families import load
from tests.e2e.recording.guard import Guard
from tests.e2e.recording.record import GRAPH, Plan, resolve
from tests.e2e.recording.runbook import (
    SCRIPTS,
    SignInRequired,
    dry_results,
    execute,
    main,
    plan_runs,
    report,
)
from tests.e2e.recording.stand_in import UPNS
from tests.e2e.test_scenarios import Json

SEED = str(SCRIPTS / "seed" / "seed.py")


def plan(tool: str, name: str, **options: object) -> Plan:
    steps: tuple[Json, ...] = ({"tool": tool},)
    return Plan(name, f"rec-tool-{name}", steps, True, **options)  # pyright: ignore[reportArgumentType]


READ = plan("outlook_list_mail", "r1")
WRITE = plan("outlook_mark_mail", "w1", persona=2)
DESTROY = plan("outlook_move_mail", "d1", destructive=True, reseed=("mail",))
OUTSIDE = plan("outlook_mark_mail", "w0", external=True)
NEEDY = plan("outlook_list_events", "n1", needs=("k",))


def names(found: Sequence[runbook.Run]) -> list[str]:
    return [one.plan.scenario for one in found]


class TestPlanning:
    def test_reads_come_first_then_writes_then_destructive_cases(self) -> None:
        found = plan_runs([DESTROY, OUTSIDE, WRITE, READ], frozenset(), {}, False)
        assert names(found) == ["r1", "w1", "w0", "d1"]

    def test_an_existing_fixture_is_skipped_unless_forced(self) -> None:
        stored = frozenset({READ.fixture})
        assert plan_runs([READ], stored, {}, False)[0].status == "skip"
        assert plan_runs([READ], stored, {}, True)[0].status == "run"

    def test_a_missing_need_blocks_with_its_sentence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(runbook, "load", lambda: replace(load(), needs={"k": "Book a talk."}))
        assert plan_runs([NEEDY], frozenset(), {}, False)[0].reason == "Book a talk."
        assert plan_runs([NEEDY], frozenset(), {"k": False}, False)[0].status == "blocked"
        assert plan_runs([NEEDY], frozenset(), {"k": True}, False)[0].status == "run"

    def test_the_report_has_three_lists_and_the_human_steps(self) -> None:
        text = report(
            {
                "a": {"status": "recorded", "note": "ok"},
                "b": {"status": "refused", "note": "refused: no"},
                "c": {"status": "blocked", "note": "Book a talk."},
            }
        )
        for heading in ("## Recorded (1)", "## Refused (1)", "## Blocked (1)"):
            assert heading in text
        assert "- b: refused: no" in text
        assert "## Simulated or human steps\n- Sign in" in text
        assert "- Book a talk." in text
        assert "## Not recorded (" in text
        assert "## Simulated or human steps\n- Sign in" in text

    def test_a_dry_run_marks_a_refused_case(self) -> None:
        refused = plan("teams_unlisted_tool", "s1")
        found = plan_runs([READ, refused], frozenset(), {}, False)
        results = dry_results(found, UPNS)
        assert results["r1"]["status"] == "would-record"
        assert results["s1"]["status"] == "refused"
        assert "allowlist" in results["s1"]["note"]


@final
class Calls:
    def __init__(self, fixtures: Path, throttle: bool = False, signed_in: bool = True) -> None:
        self.fixtures, self.throttle, self.signed_in = fixtures, throttle, signed_in
        self.commands: list[list[str]] = []
        self.envs: list[Mapping[str, str]] = []
        self.sleeps: list[float] = []

    def __call__(
        self, command: Sequence[str], env: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(list(command))
        self.envs.append(env)
        if command[1].endswith("get_token.py"):
            code = 0 if self.signed_in else 3
            return subprocess.CompletedProcess(command, code, "tok-SECRET\n", "")
        if command[2:3] == ["tests.e2e.recording.record"] or "-m" in command[1:2]:
            if self.throttle:
                self.throttle = False
                return subprocess.CompletedProcess(command, 2, "", "refused: retry-after 5\n")
            _ = (self.fixtures / f"rec-tool-{command[3]}.json").write_text("[]")
        return subprocess.CompletedProcess(command, 0, "", "")

    def seeds(self, *arguments: str) -> list[list[str]]:
        return [
            c for c in self.commands if c[1] == SEED and c[2 : 2 + len(arguments)] == [*arguments]
        ]


@pytest.fixture
def fixtures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(runbook, "FIXTURES", tmp_path)
    return tmp_path


class TestExecution:
    def test_a_run_sweeps_records_and_reseeds_a_destructive_case(
        self, fixtures: Path, tmp_path: Path
    ) -> None:
        calls = Calls(fixtures)
        found = plan_runs([READ, DESTROY], frozenset(), {}, False)
        results = execute(found, UPNS, calls, calls.sleeps.append, tmp_path / "results.json")
        assert {name: one["status"] for name, one in results.items()} == {
            "r1": "recorded",
            "d1": "recorded",
        }
        assert [c[-1] for c in calls.seeds("cleanup", "--cases")][:3] == ["1", "2", "3"]
        assert calls.seeds("cleanup", "--phases", "mail") == [
            [calls.commands[0][0], SEED, "cleanup", "--phases", "mail", "--as", "1"]
        ]
        assert calls.seeds("apply", "--phases", "mail") == [
            [calls.commands[0][0], SEED, "apply", "--phases", "mail", "--as", "1"]
        ]
        assert (tmp_path / "results.json").is_file()

    def test_a_reseed_cleans_then_applies_its_phases_for_its_personas_in_its_order(
        self, fixtures: Path, tmp_path: Path
    ) -> None:
        calls = Calls(fixtures)
        invites = plan(
            "outlook_respond_to_invite",
            "i1",
            destructive=True,
            external=True,
            reseed=("cal-invites", "cal-answers"),
            reseed_personas=(2, 3, 1),
        )
        _ = execute(
            plan_runs([invites], frozenset(), {}, False),
            UPNS,
            calls,
            calls.sleeps.append,
            tmp_path / "r.json",
        )
        seeded = [c[2:] for c in calls.commands if c[1] == SEED and "--phases" in c]
        phases = ["--phases", "cal-invites,cal-answers"]
        assert seeded == [
            ["cleanup", *phases, "--as", "2"],
            ["cleanup", *phases, "--as", "3"],
            ["cleanup", *phases, "--as", "1"],
            ["apply", *phases, "--as", "2"],
            ["apply", *phases, "--as", "3"],
            ["apply", *phases, "--as", "1"],
        ]

    def test_the_token_reaches_only_the_record_child(self, fixtures: Path, tmp_path: Path) -> None:
        calls = Calls(fixtures)
        _ = execute(
            plan_runs([READ], frozenset(), {}, False),
            UPNS,
            calls,
            calls.sleeps.append,
            tmp_path / "r.json",
        )
        record = [e for c, e in zip(calls.commands, calls.envs, strict=True) if "-m" in c]
        assert record[0]["GRAPH_TOKEN"] == "tok-SECRET"
        assert "GRAPH_TOKEN" not in os.environ
        assert "--allow-writes" not in calls.commands[calls.envs.index(record[0])]

    def test_a_plan_with_a_write_step_before_its_last_read_step_gets_allow_writes(
        self, fixtures: Path, tmp_path: Path
    ) -> None:
        mixed = Plan(
            "m1",
            "rec-tool-m1",
            ({"tool": "outlook_mark_mail"}, {"tool": "outlook_list_mail"}),
            True,
        )
        calls = Calls(fixtures)
        _ = execute(
            plan_runs([mixed], frozenset(), {}, False),
            UPNS,
            calls,
            calls.sleeps.append,
            tmp_path / "r.json",
        )
        assert not runbook.reads(mixed)
        assert any("--allow-writes" in c for c in calls.commands if "-m" in c)

    def test_a_throttled_read_waits_sweeps_and_retries_once(
        self, fixtures: Path, tmp_path: Path
    ) -> None:
        calls = Calls(fixtures, throttle=True)
        results = execute(
            plan_runs([READ], frozenset(), {}, False),
            UPNS,
            calls,
            calls.sleeps.append,
            tmp_path / "r.json",
        )
        assert calls.sleeps == [runbook.WAIT]
        assert results["r1"]["status"] == "recorded"

    def test_a_throttled_write_is_never_sent_again(self, fixtures: Path, tmp_path: Path) -> None:
        calls = Calls(fixtures, throttle=True)
        results = execute(
            plan_runs([WRITE], frozenset(), {}, False),
            UPNS,
            calls,
            calls.sleeps.append,
            tmp_path / "r.json",
        )
        assert calls.sleeps == []
        assert len([c for c in calls.commands if "-m" in c[1:2]]) == 1
        assert results["w1"]["status"] == "refused"

    def test_a_case_with_no_fixture_is_refused_with_the_last_line(
        self, fixtures: Path, tmp_path: Path
    ) -> None:
        calls = Calls(fixtures)

        def refusing(
            command: Sequence[str], env: Mapping[str, str]
        ) -> subprocess.CompletedProcess[str]:
            if "-m" in command[1:2]:
                return subprocess.CompletedProcess(command, 2, "", "refused: nope\n")
            return calls(command, env)

        results = execute(
            plan_runs([READ], frozenset(), {}, False),
            UPNS,
            refusing,
            calls.sleeps.append,
            tmp_path / "r.json",
        )
        assert results["r1"] == {"status": "refused", "note": "refused: nope"}

    def test_a_refusal_with_findings_keeps_the_first_three(
        self, fixtures: Path, tmp_path: Path
    ) -> None:
        calls = Calls(fixtures)
        stderr = "refused: r1: the lint found 4 leak(s), nothing was written:\n" + "".join(
            f"  bodies/x.json at value[{n}].id: a GUID (plain)\n" for n in range(4)
        )

        def refusing(
            command: Sequence[str], env: Mapping[str, str]
        ) -> subprocess.CompletedProcess[str]:
            if "-m" in command[1:2]:
                return subprocess.CompletedProcess(command, 2, "", stderr)
            return calls(command, env)

        results = execute(
            plan_runs([READ], frozenset(), {}, False),
            UPNS,
            refusing,
            calls.sleeps.append,
            tmp_path / "r.json",
        )
        assert results["r1"]["note"].splitlines() == [
            "refused: r1: the lint found 4 leak(s), nothing was written:",
            *(f"  bodies/x.json at value[{n}].id: a GUID (plain)" for n in range(3)),
        ]

    def test_a_failed_silent_sign_in_stops_the_run(self, fixtures: Path, tmp_path: Path) -> None:
        calls = Calls(fixtures, signed_in=False)
        with pytest.raises(SignInRequired, match="record_all.sh login"):
            _ = execute(
                plan_runs([READ], frozenset(), {}, False),
                UPNS,
                calls,
                calls.sleeps.append,
                tmp_path / "r.json",
            )

    def test_an_earlier_result_survives_a_skipped_rerun(
        self, fixtures: Path, tmp_path: Path
    ) -> None:
        calls = Calls(fixtures)
        saved = tmp_path / "r.json"
        _ = saved.write_text('{"r1": {"status": "recorded", "note": "the expect is unmet"}}')
        found = plan_runs([READ], frozenset({READ.fixture}), {}, False)
        assert execute(found, UPNS, calls, calls.sleeps.append, saved)["r1"]["note"] == (
            "the expect is unmet"
        )


@final
class Scripted:
    def __init__(self, calls: Calls, refusals: Sequence[str], timeout: bool = False) -> None:
        self.calls, self.refusals, self.timeout = calls, list(refusals), timeout
        self.attempts = 0

    def __call__(
        self, command: Sequence[str], env: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        if "-m" not in command[1:2]:
            return self.calls(command, env)
        self.attempts += 1
        if self.timeout:
            raise subprocess.TimeoutExpired(command, 600)
        if self.refusals:
            return subprocess.CompletedProcess(command, 2, "", self.refusals.pop(0))
        return self.calls(command, env)


def bind_plan(first: str, second: str = "outlook_list_mail", *, name: str = "b1") -> Plan:
    steps: tuple[Json, ...] = (
        {"tool": first},
        {"tool": second, "bind": {"uri": "$prev.messages[0].uri"}},
    )
    return Plan(name, f"rec-tool-{name}", steps, True)


BINDS = "refused: b1: step 2 binds a value that the earlier answer does not have. Wait.\n"


class TestRetries:
    def test_a_timed_out_case_is_refused_and_the_run_goes_on(
        self, fixtures: Path, tmp_path: Path
    ) -> None:
        calls = Calls(fixtures)
        hung = Scripted(calls, [], timeout=True)
        results = execute(
            plan_runs([READ], frozenset(), {}, False),
            UPNS,
            hung,
            calls.sleeps.append,
            tmp_path / "r",
        )
        assert results["r1"] == {"status": "refused", "note": "timed out after 600 seconds"}
        assert hung.attempts == 1

    def test_a_timed_out_case_does_not_stop_the_next_case(
        self, fixtures: Path, tmp_path: Path
    ) -> None:
        calls = Calls(fixtures)

        def hangs_first(
            command: Sequence[str], env: Mapping[str, str]
        ) -> subprocess.CompletedProcess[str]:
            if "-m" in command[1:2] and command[3] == "r1":
                raise subprocess.TimeoutExpired(command, 600)
            return calls(command, env)

        other = plan("outlook_list_events", "r2")
        found = plan_runs([READ, other], frozenset(), {}, False)
        results = execute(found, UPNS, hangs_first, calls.sleeps.append, tmp_path / "r.json")
        assert (results["r1"]["status"], results["r2"]["status"]) == ("refused", "recorded")

    def test_the_gap_of_a_case_is_slept_before_the_next_case(
        self, fixtures: Path, tmp_path: Path
    ) -> None:
        calls = Calls(fixtures)
        slow = plan("outlook_list_mail", "r1", gap=7)
        found = plan_runs([slow, plan("outlook_list_events", "r2")], frozenset(), {}, False)
        _ = execute(found, UPNS, calls, calls.sleeps.append, tmp_path / "r.json")
        assert calls.sleeps == [7]

    @pytest.mark.parametrize(("header", "slept"), [(0, 60), (5, 60), (120, 120), (9999, 300)])
    def test_the_wait_after_a_throttle_is_bounded_and_never_shorter_than_retry_after(
        self, fixtures: Path, tmp_path: Path, header: int, slept: int
    ) -> None:
        calls = Calls(fixtures)
        throttled = Scripted(
            calls, [f"refused: r1: transient answers ['429 GET']. retry-after {header}\n"]
        )
        _ = execute(
            plan_runs([READ], frozenset(), {}, False),
            UPNS,
            throttled,
            calls.sleeps.append,
            tmp_path / "r",
        )
        assert calls.sleeps == [slept]

    def test_a_search_with_no_hit_is_recorded_again_after_a_wait(
        self, fixtures: Path, tmp_path: Path
    ) -> None:
        calls = Calls(fixtures)
        lagging = Scripted(calls, [BINDS, BINDS])
        results = execute(
            plan_runs([bind_plan("outlook_search_mail")], frozenset(), {}, False),
            UPNS,
            lagging,
            calls.sleeps.append,
            tmp_path / "r.json",
        )
        assert calls.sleeps == [60, 60]
        assert lagging.attempts == 3
        assert results["b1"]["status"] == "recorded"

    @pytest.mark.parametrize(
        ("tool", "attempts"), [("outlook_search_mail", 4), ("teams_search_messages", 6)]
    )
    def test_the_search_retry_stops_after_its_count_of_more_runs(
        self, fixtures: Path, tmp_path: Path, tool: str, attempts: int
    ) -> None:
        calls = Calls(fixtures)
        lagging = Scripted(calls, [BINDS] * 9)
        results = execute(
            plan_runs([bind_plan(tool)], frozenset(), {}, False),
            UPNS,
            lagging,
            calls.sleeps.append,
            tmp_path / "r.json",
        )
        assert lagging.attempts == attempts
        assert results["b1"]["note"] == BINDS.strip()

    @pytest.mark.parametrize("first", ["outlook_list_calendars", "outlook_mark_mail"])
    def test_a_bind_from_a_tool_that_is_not_a_search_is_not_repeated(
        self, fixtures: Path, tmp_path: Path, first: str
    ) -> None:
        calls = Calls(fixtures)
        lagging = Scripted(calls, [BINDS] * 9)
        found = plan_runs([bind_plan(first)], frozenset(), {}, False)
        _ = execute(found, UPNS, lagging, calls.sleeps.append, tmp_path / "r.json")
        assert lagging.attempts == 1
        assert calls.sleeps == []

    def test_a_write_before_the_failing_bind_is_never_repeated_even_after_a_search(
        self, fixtures: Path, tmp_path: Path
    ) -> None:
        calls = Calls(fixtures)
        steps: tuple[Json, ...] = (
            {"tool": "outlook_mark_mail"},
            {"tool": "outlook_search_mail"},
            {"tool": "outlook_list_mail", "bind": {"uri": "$prev.messages[0].uri"}},
        )
        written = Plan("b1", "rec-tool-b1", steps, True)
        lagging = Scripted(calls, [BINDS.replace("step 2", "step 3")] * 9)
        _ = execute(
            plan_runs([written], frozenset(), {}, False),
            UPNS,
            lagging,
            calls.sleeps.append,
            tmp_path / "r.json",
        )
        assert lagging.attempts == 1

    def test_a_late_notebook_list_also_waits(self, fixtures: Path, tmp_path: Path) -> None:
        calls = Calls(fixtures)
        lagging = Scripted(calls, [BINDS])
        found = plan_runs([bind_plan("onenote_list_notebooks")], frozenset(), {}, False)
        results = execute(found, UPNS, lagging, calls.sleeps.append, tmp_path / "r.json")
        assert calls.sleeps == [60]
        assert results["b1"]["status"] == "recorded"

    def test_a_numbered_reference_to_a_search_also_waits(self) -> None:
        steps: tuple[Json, ...] = (
            {"tool": "outlook_find_recipient"},
            {"tool": "outlook_list_calendars"},
            {"tool": "outlook_list_mail", "bind": {"address": "$1.candidates[0].address"}},
        )
        assert runbook.index_lag(Plan("b1", "f", steps), BINDS.replace("step 2", "step 3"))
        assert not runbook.index_lag(Plan("b1", "f", steps), "refused: another reason")


class TestExtraScopes:
    def test_a_case_scope_is_added_to_the_narrow_token(
        self, fixtures: Path, tmp_path: Path
    ) -> None:
        calls = Calls(fixtures)
        wide = plan("outlook_list_group_events", "g1", scopes=("Group.Read.All",))
        _ = execute(
            plan_runs([wide], frozenset(), {}, False),
            UPNS,
            calls,
            calls.sleeps.append,
            tmp_path / "r.json",
        )
        asked = [c for c in calls.commands if c[1].endswith("get_token.py") and "--scopes" in c]
        assert asked[0][-5:] == [
            "--silent",
            "--scopes-for",
            "outlook_list_group_events",
            "--scopes",
            "Group.Read.All",
        ]

    def test_login_asks_for_the_scopes_of_all_cases(self, fixtures: Path) -> None:
        calls = Calls(fixtures)
        assert runbook.login(UPNS, True, calls, ["Group.Read.All"]) == 0
        assert calls.commands[0][-3:] == ["--list-scopes", "--scopes", "Group.Read.All"]


class TestResume:
    def test_a_recorded_fixture_replaces_a_stale_block(
        self, fixtures: Path, tmp_path: Path
    ) -> None:
        calls = Calls(fixtures)
        saved = tmp_path / "r.json"
        _ = saved.write_text('{"r1": {"status": "blocked", "note": "old need"}}')
        found = plan_runs([READ], frozenset({READ.fixture}), {}, False)
        assert execute(found, UPNS, calls, calls.sleeps.append, saved)["r1"] == {
            "status": "recorded",
            "note": "the fixture exists",
        }

    def test_a_blocked_case_replaces_an_earlier_refusal(
        self, fixtures: Path, tmp_path: Path
    ) -> None:
        calls = Calls(fixtures)
        saved = tmp_path / "r.json"
        _ = saved.write_text('{"n1": {"status": "refused", "note": "earlier"}}')
        found = plan_runs([NEEDY], frozenset(), {"k": False}, False)
        assert execute(found, UPNS, calls, calls.sleeps.append, saved)["n1"]["status"] == "blocked"


class TestCommandLine:
    @pytest.mark.usefixtures("fixtures")
    def test_every_mode_in_dry_run_sends_nothing_and_prints_the_report(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(runbook, "STATE", tmp_path / "state")
        assert main(["all", "--dry-run"]) == 0
        out = capsys.readouterr().out
        for mode in ("login", "discover", "seed", "record", "check", "report"):
            assert f"== {mode} (dry run, nothing is sent) ==" in out
        assert "## Refused (0)" in out
        assert "pytest scripts/dogfood/seed -q" in out
        assert "## Would record (dry run) (" in out
        assert "- outlook_move_mail-archive:" in out
        assert not (tmp_path / "state").exists()

    @pytest.mark.usefixtures("fixtures")
    def test_all_reads_the_probe_answers_that_its_discover_mode_just_wrote(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        state = tmp_path / "state"
        monkeypatch.setattr(runbook, "STATE", state)

        def wrote(*_arguments: object) -> None:
            state.mkdir()
            _ = (state / "discover.json").write_text(json.dumps(dict.fromkeys(load().probes, True)))

        monkeypatch.setattr(runbook, "discover", wrote)
        probed = set(load().probes)
        waiting = next(
            case
            for case, _ in case_entries()
            if (needs := resolve(case).needs) and set(needs) <= probed
        )
        assert main(["all", "--dry-run"]) == 0
        blocked = capsys.readouterr().out.split("## Blocked")[1].split("##")[0]
        assert f"- {waiting}:" not in blocked

    @pytest.mark.usefixtures("fixtures")
    def test_case_picks_one_case(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(runbook, "STATE", tmp_path / "state")
        assert main(["report", "--dry-run", "--case", "outlook_list_mail-inbox"]) == 0
        assert "Would record (dry run) (1)" in capsys.readouterr().out

    def test_a_live_mode_needs_the_three_users(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("SEED_UPNS", "only@one.test")
        assert main(["record"]) == 2
        assert "SEED_UPNS must list the three test users" in capsys.readouterr().err

    @pytest.mark.parametrize("key", sorted(load().probes))
    def test_every_probe_passes_the_guard(self, key: str) -> None:
        _, path, _ = load().probes[key]
        request = httpx.Request("GET", f"{GRAPH}{path}")
        assert Guard("probe", frozenset(), False).refuses_request(request, "discover") is None

    def test_a_probe_outside_the_guard_finds_nothing_and_sends_nothing(self) -> None:
        assert runbook.probed("tok", "/organization/secrets") == 0


class TokenScript(Protocol):
    CACHE_PATH: Path
    msal: ModuleType
    scopes_of: Callable[[Sequence[str], Sequence[str]], list[str]]
    main: Callable[[Sequence[str] | None], int]


def token_script() -> TokenScript:
    spec = importlib.util.spec_from_file_location("get_token", SCRIPTS / "get_token.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast("TokenScript", cast("object", module))


class TestGetToken:
    def test_the_union_comes_from_the_server_and_adds_basic_users(self) -> None:
        union = token_script().scopes_of((), ())
        assert "https://graph.microsoft.com/User.ReadBasic.All" in union
        assert "https://graph.microsoft.com/Notes.ReadWrite" in union
        assert len(union) == len(set(union))

    def test_scopes_for_names_only_the_scopes_of_those_tools(self) -> None:
        scopes = token_script().scopes_of(("outlook_move_mail",), ())
        assert "https://graph.microsoft.com/Mail.ReadWrite" in scopes
        assert "https://graph.microsoft.com/Notes.Read" not in scopes
        assert "https://graph.microsoft.com/User.ReadBasic.All" not in scopes

    def test_a_named_permission_is_added_once_to_either_set(self) -> None:
        script = token_script()
        group = "https://graph.microsoft.com/Group.Read.All"
        narrow = script.scopes_of(("outlook_move_mail",), ("Group.Read.All", "Group.Read.All"))
        assert narrow.count(group) == 1
        assert group in script.scopes_of((), ("Group.Read.All",))
        assert group not in script.scopes_of(("outlook_move_mail",), ())

    def test_silent_never_starts_a_device_flow(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        module = token_script()

        class Offline:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def get_accounts(self) -> list[object]:
                return []

            def initiate_device_flow(self, **_: object) -> object:
                raise AssertionError("a silent run started a device flow")

        monkeypatch.setattr(module, "CACHE_PATH", tmp_path / "cache.json")
        monkeypatch.setattr(module.msal, "PublicClientApplication", Offline)
        monkeypatch.setenv("ENTRA_TENANT_ID", "tenant")
        monkeypatch.setenv("ENTRA_CLIENT_ID", "client")
        assert module.main(["tester3@x.test", "--silent"]) == 3


def test_a_seed_marked_probe_counts_only_rows_named_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [{"displayName": "seed-v1 team"}, {"displayName": "someone else's team"}]

    def send(*_: object) -> httpx.Response:
        return httpx.Response(200, json={"value": rows})

    monkeypatch.setattr(httpx.Client, "send", send)
    assert runbook.probed("tok", "/me/joinedTeams") == 2
    assert runbook.probed("tok", "/me/joinedTeams#seed") == 1


def test_a_seed_marked_probe_reads_the_topic_of_a_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [{"topic": "seed-v1 case-teams-unread chat"}, {"topic": "lunch"}, {"topic": None}]

    def send(*_: object) -> httpx.Response:
        return httpx.Response(200, json={"value": rows})

    monkeypatch.setattr(httpx.Client, "send", send)
    assert runbook.probed("tok", "/me/chats#seed") == 1


def test_the_seed_runs_mia_last_so_that_her_copy_of_the_invitation_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[list[str]] = []

    def shell(command: Sequence[str], _env: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
        seen.append(list(command))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(runbook, "shell", shell)
    monkeypatch.setenv("SEED_UPNS", "mia@x.test,anna@x.test,tom@x.test")
    assert runbook.main(["seed"]) == 0
    assert seen[0][-4:] == ["apply", "2", "3", "1"]
    assert seen[1][-5:] == ["--phases", "teams,teams-posts,teams-chats", "1", "2", "3"]
    assert len(seen) == 2
