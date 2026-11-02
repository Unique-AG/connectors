"""The runbook behind scripts/dogfood/record_all.sh. It plans the tool cases, records them one by
one through `record.py`, and writes the report. With `--dry-run` it sends no request and writes
no state. State goes to `.record-all/`: `discover.json`, `results.json`, `report.md` and
`meeting.json`. The `meeting` mode holds the one live step: Mia and Anna join a Teams meeting."""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from urllib.parse import quote

import httpx
import yaml

from tests.e2e.recording import stand_in
from tests.e2e.recording.cases import case_entries
from tests.e2e.recording.families import load
from tests.e2e.recording.guard import DEFAULT_CAP, PREFLIGHT, READ_TOOLS, WRITE_TOOLS, Guard
from tests.e2e.recording.record import (
    GRAPH,
    Plan,
    catalogs,
    describe,
    guard_for,
    planned_values,
    resolve,
    tool_of,
)

SERVICE = Path(__file__).resolve().parents[3]
STATE = SERVICE / ".record-all"
FIXTURES = SERVICE / "tests" / "e2e" / "fixtures"
SCRIPTS = SERVICE / "scripts" / "dogfood"
SPOKEN = cast(
    "Mapping[str, Sequence[str]]",
    yaml.safe_load((SCRIPTS / "seed" / "corpus" / "teams.yaml").read_text())["transcript"],
)
PERSONAS = 3
WAIT = 60
MAX_WAIT = 300
BIND_RETRIES = 3
SLOW_INDEX = {"teams_search_messages": 5}
TIMEOUT = 600
MEETING_SUBJECT = "seed-v1 meeting"
TEAM_PHASES = ("teams", "teams-posts", "teams-chats")
MEETING_CASES = (
    "teams_list_meeting_recordings-past",
    "teams_list_meeting_transcripts-past",
    "teams_read_meeting-past",
    "teams_read_transcript-past",
)
MEETING_TOOLS = (
    "teams_list_meeting_transcripts",
    "teams_list_meeting_recordings",
    "teams_read_meeting",
)
MEETING_POLL = 120
MEETING_POLLS = 60
_ASKED_FOR_BIND = re.compile(r"step (\d+) binds a value that the earlier answer does not have")
_REFERENCE = re.compile(r"\$(prev|\d+)")
_SEARCH = re.compile(r"_(?:search|find)_|^onenote_list_")

type Results = dict[str, dict[str, str]]
type Shell = Callable[[Sequence[str], Mapping[str, str]], subprocess.CompletedProcess[str]]


class SignInRequired(Exception):
    pass


class MeetingFailed(Exception):
    pass


@dataclass(frozen=True)
class Run:
    plan: Plan
    status: str
    reason: str = ""


def reads(plan: Plan) -> bool:
    last = tool_of(plan.steps[-1])
    return last in READ_TOOLS or last in load().read_posts


def writes(plan: Plan) -> bool:
    return any(tool_of(step) in WRITE_TOOLS for step in plan.steps)


def index_lag(plan: Plan, refusal: str) -> bool:
    number = int(found[1]) if (found := _ASKED_FOR_BIND.search(refusal)) else 0
    if not 1 < number <= len(plan.steps) or any(
        tool_of(step) in WRITE_TOOLS for step in plan.steps[: number - 1]
    ):
        return False
    given = json.dumps(plan.steps[number - 1])
    sources = {
        number - 1 if one == "prev" else int(one)
        for one in cast("list[str]", _REFERENCE.findall(given))
    }
    return any(_SEARCH.search(tool_of(plan.steps[n - 1])) for n in sources if 0 < n < number)


def plan_runs(
    plans: Sequence[Plan], existing: frozenset[str], discovered: Mapping[str, bool], force: bool
) -> list[Run]:
    def order(plan: Plan) -> tuple[int, bool, int, str]:
        group = 0 if reads(plan) else 2 if plan.destructive else 1
        return group, plan.external, plan.persona, plan.scenario

    found: list[Run] = []
    for plan in sorted(plans, key=order):
        missing = [key for key in plan.needs if not discovered.get(key, False)]
        if plan.fixture in existing and not force:
            found.append(Run(plan, "skip", "the fixture exists"))
        elif missing:
            found.append(Run(plan, "blocked", " ".join(load().needs.get(k, k) for k in missing)))
        else:
            found.append(Run(plan, "run"))
    return found


def report(results: Results) -> str:
    unrecorded = sorted(load().unrecorded.items())

    def section(title: str, status: str) -> list[str]:
        rows = [
            f"- {name}: {one['note']}"
            for name, one in sorted(results.items())
            if one["status"] == status
        ]
        return [f"## {title} ({len(rows)})", *rows, ""]

    blocked = {one["note"] for one in results.values() if one["status"] == "blocked"}
    unrecorded_by_a_person = {
        text for text in load().needs.values() if any(why.startswith(text) for _, why in unrecorded)
    }
    human = [
        "Sign in the three test users once: record_all.sh login.",
        "If login fails with AADSTS65001 or AADSTS90094, an admin grants consent once.",
        *sorted(blocked | unrecorded_by_a_person),
    ]
    return "\n".join(
        [
            *section("Recorded", "recorded"),
            *section("Refused", "refused"),
            *section("Blocked", "blocked"),
            *section("Would record (dry run)", "would-record"),
            f"## Not recorded ({len(unrecorded)})",
            *(f"- {tool}: {why}" for tool, why in unrecorded),
            "",
            "## Simulated or human steps",
            *(f"- {line}" for line in human),
            "",
        ]
    )


def shell(command: Sequence[str], env: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        cwd=SERVICE,
        env={**os.environ, "PYTHONWARNINGS": "ignore", **env},
        timeout=TIMEOUT,
    )


def _python(*arguments: str) -> list[str]:
    return [sys.executable, *arguments]


def _extra(names: Sequence[str]) -> list[str]:
    return ["--scopes", *names] if names else []


def token(sh: Shell, upn: str, tools: Sequence[str] = (), extra: Sequence[str] = ()) -> str:
    scoped = ["--scopes-for", *tools] if tools else []
    command = _python(str(SCRIPTS / "get_token.py"), upn, "--silent", *scoped, *_extra(extra))
    done = sh(command, {})
    if done.returncode != 0:
        raise SignInRequired(f"no silent token for persona {upn}: run record_all.sh login")
    return done.stdout.strip()


def seed(sh: Shell, upns: Sequence[str], indexes: Sequence[int], *arguments: str) -> None:
    for index in indexes:
        env = {"GRAPH_TOKEN": token(sh, upns[index - 1]), "SEED_UPNS": ",".join(upns)}
        _ = sh(_python(str(SCRIPTS / "seed" / "seed.py"), *arguments, "--as", str(index)), env)


def sweep(sh: Shell, upns: Sequence[str], indexes: Sequence[int]) -> None:
    seed(sh, upns, indexes, "cleanup", "--cases")


def reseed(sh: Shell, upns: Sequence[str], plan: Plan, wide: Sequence[int]) -> None:
    order = plan.reseed_personas or wide
    chosen = ["--phases", ",".join(plan.reseed)] if plan.reseed else []
    if chosen:
        seed(sh, upns, order, "cleanup", *chosen)
    seed(sh, upns, order, "apply", *chosen)


def _once(
    sh: Shell, upns: Sequence[str], plan: Plan
) -> tuple[subprocess.CompletedProcess[str], bool]:
    tools = tuple(dict.fromkeys(tool_of(step) for step in plan.steps))
    command = _python("-m", "tests.e2e.recording.record", plan.scenario, "--target", "graph")
    command += ["--max-requests", str(plan.cap or DEFAULT_CAP)]
    command += [] if reads(plan) else ["--allow-writes"]
    started = time.time()
    env = {
        "GRAPH_TOKEN": token(sh, upns[plan.persona - 1], tools, plan.scopes),
        "SEED_UPNS": ",".join(upns),
    }
    try:
        done = sh(command, env)
    except subprocess.TimeoutExpired as expired:
        stalled = f"timed out after {int(expired.timeout)} seconds"
        return subprocess.CompletedProcess(command, 124, "", stalled), False
    written = FIXTURES / f"{plan.fixture}.json"
    return done, written.is_file() and written.stat().st_mtime >= started


def record_one(
    sh: Shell, upns: Sequence[str], plan: Plan, sleep: Callable[[float], None]
) -> dict[str, str]:
    done, recorded = _once(sh, upns, plan)
    wait = re.search(r"retry-after (\d+)", done.stderr)
    if wait and not recorded and not writes(plan):
        sleep(min(max(int(wait[1]), WAIT), MAX_WAIT))
        sweep(sh, upns, range(1, PERSONAS + 1))
        done, recorded = _once(sh, upns, plan)
    retries = max(BIND_RETRIES, *(SLOW_INDEX.get(tool_of(step), 0) for step in plan.steps))
    for _ in range(retries):
        if recorded or not index_lag(plan, done.stderr):
            break
        sleep(WAIT)
        done, recorded = _once(sh, upns, plan)
    if recorded:
        return {
            "status": "recorded",
            "note": "the expect is unmet" if done.returncode == 1 else "ok",
        }
    lines = [line for line in done.stderr.splitlines() if line.strip()]
    heads = [n for n, line in enumerate(lines) if line.endswith("nothing was written:")]
    if heads:
        return {"status": "refused", "note": "\n".join(lines[heads[0] : heads[0] + 4])}
    return {"status": "refused", "note": lines[-1] if lines else f"exit {done.returncode}"}


def _settled(run: Run) -> dict[str, str]:
    return {"status": "recorded" if run.status == "skip" else run.status, "note": run.reason}


def execute(
    found: Sequence[Run], upns: Sequence[str], sh: Shell, sleep: Callable[[float], None], path: Path
) -> Results:
    results = cast("Results", json.loads(path.read_text())) if path.is_file() else {}
    everyone = range(1, PERSONAS + 1)
    sweep(sh, upns, everyone)
    pause = 0
    for run in found:
        plan = run.plan
        if run.status != "run":
            earlier = results.get(plan.scenario, {}).get("status")
            if (
                run.status == "blocked"
                or (run.status == "skip" and earlier != "recorded")
                or plan.scenario not in results
            ):
                results[plan.scenario] = _settled(run)
            continue
        if pause:
            sleep(pause)
        results[plan.scenario] = record_one(sh, upns, plan, sleep)
        pause = plan.gap
        if not reads(plan):
            wide = everyone if plan.external else [plan.persona]
            sweep(sh, upns, wide)
            if plan.destructive:
                reseed(sh, upns, plan, wide)
        _ = path.write_text(json.dumps(results, indent=2, sort_keys=True))
    sweep(sh, upns, everyone)
    _ = path.write_text(json.dumps(results, indent=2, sort_keys=True))
    return results


def login(upns: Sequence[str], dry: bool, sh: Shell, extra: Sequence[str] = ()) -> int:
    listing = _python(str(SCRIPTS / "get_token.py"), "--list-scopes", *_extra(extra))
    scopes = sh(listing, {}).stdout.split()
    print(f"{len(scopes)} scopes for {len(upns)} test users")
    for upn in () if dry else upns:
        command = _python(str(SCRIPTS / "get_token.py"), upn, *_extra(extra))
        if code := subprocess.run(
            command, stdout=subprocess.DEVNULL, check=False, cwd=SERVICE
        ).returncode:
            return code
    return 0


def meeting_state() -> Mapping[str, str] | None:
    saved = STATE / "meeting.json"
    return cast("Mapping[str, str]", json.loads(saved.read_text())) if saved.is_file() else None


def discover(
    upns: Sequence[str],
    dry: bool,
    sh: Shell,
    get: Callable[[str, str], int],
    only: Sequence[str] = (),
) -> None:
    known = STATE / "discover.json"
    found = (
        cast("dict[str, bool]", json.loads(known.read_text())) if only and known.is_file() else {}
    )
    meeting = meeting_state()
    for key, (persona, path, minimum) in sorted(load().probes.items()):
        if only and key not in only:
            continue
        print(f"probe {key}: persona {persona} GET {path}, at least {minimum}")
        if not dry:
            asked = (
                path
                if meeting is None
                else path.replace("{meeting}", quote(meeting["id"], safe=""))
            )
            found[key] = (
                "{meeting}" not in asked and get(token(sh, upns[persona - 1]), asked) >= minimum
            )
    if not dry:
        STATE.mkdir(exist_ok=True)
        _ = known.write_text(json.dumps(found, indent=2, sort_keys=True))


def check(dry: bool) -> int:
    commands = [
        _python("-m", "pytest", "tests/e2e", "tests/tools", "tests/test_use_cases.py", "-q"),
        _python("-m", "pytest", "scripts/dogfood/seed", "-q"),
        _python("-m", "ruff", "check", "."),
        _python("-m", "basedpyright"),
        ["pnpm", "exec", "biome", "check", "--write", "services/office-365-mcp/tests/e2e"],
    ]
    failed = 0
    for command in commands:
        print("$", " ".join(command))
        root = SERVICE.parents[1] if command[0] == "pnpm" else SERVICE
        if not dry and subprocess.run(command, check=False, cwd=root).returncode:
            failed += 1
    return failed


def dry_results(found: Sequence[Run], upns: Sequence[str]) -> Results:
    results: Results = {}
    for run in found:
        lines = describe(
            run.plan, guard_for(upns, run.plan, True, DEFAULT_CAP), planned_values(upns)
        )
        refused = [line.strip() for line in lines if "REFUSED" in line]
        if run.status == "run":
            results[run.plan.scenario] = {
                "status": "refused" if refused else "would-record",
                "note": refused[0] if refused else "",
            }
        else:
            results[run.plan.scenario] = _settled(run)
    return results


def probed(token_: str, path: str) -> int:
    path, _, seed_only = path.partition("#")
    request = httpx.Request("GET", f"{GRAPH}{path}", headers={"authorization": f"Bearer {token_}"})
    guard = Guard("probe", frozenset(), False)
    if guard.refuses_request(request, "discover") is not None:
        return 0
    with httpx.Client() as client:
        answer = client.send(request)
    body = (
        cast("Mapping[str, list[Mapping[str, object]]]", answer.json())
        if answer.is_success
        else None
    )
    rows = body["value"] if body and "value" in body else []
    if seed_only:
        rows = [
            row
            for row in rows
            if str(row.get("displayName") or row.get("topic") or "").startswith("seed-v1")
        ]
    return len(rows)


def graph(
    method: str, path: str, token_: str, tool: str, upns: Sequence[str], body: object = None
) -> Mapping[str, str]:
    request = httpx.Request(
        method, f"{GRAPH}{path}", headers={"authorization": f"Bearer {token_}"}, json=body
    )
    guard = Guard(upns[0], frozenset(one.casefold() for one in upns), method != "GET")
    if (refusal := guard.refuses_request(request, tool)) is not None:
        raise MeetingFailed(f"the guard refused {method} {path}: {refusal}")
    with httpx.Client() as client:
        answer = client.send(request)
    if not answer.is_success:
        raise MeetingFailed(f"{method} {path} answered {answer.status_code}")
    return cast("Mapping[str, str]", answer.json())


def instructions(join_url: str) -> str:
    lines = [
        f"Join URL: {join_url}",
        "Join as Mia in the Teams app. Join as Anna in a private window.",
        "Join as Tom in a second private window.",
        "Mia: choose More > Record and transcribe > Start.",
        "Say these lines. Each person says the lines of that person, in this order:",
        *(f"{name.title()}: {line}" for name, said in SPOKEN.items() for line in said),
        "Then stop the recording and leave the meeting.",
        "The Teams meeting policy must allow recording and transcription.",
        "The admin runbook sets that policy.",
    ]
    width = max(len(line) for line in lines)
    rule = f"+{'-' * (width + 2)}+"
    return "\n".join([rule, *(f"| {line:<{width}} |" for line in lines), rule])


def meeting_start(upns: Sequence[str], dry: bool, sh: Shell, force: bool) -> None:
    held = meeting_state()
    if dry or (held is not None and not force):
        print(instructions(held["join_url"] if held else "(the join URL of the new meeting)"))
        print(
            f"{'would POST' if dry else 'kept'} {MEETING_SUBJECT}: "
            + "Mia organizes, Anna and Tom attend"
        )
        return
    token_ = token(sh, upns[0], ("teams_create_meeting",), ("User.ReadBasic.All",))
    others = [
        {
            "upn": upn,
            "identity": {
                "user": {
                    "id": graph("GET", f"/users/{upn}?$select=id", token_, PREFLIGHT, upns)["id"]
                }
            },
        }
        for upn in upns[1:]
    ]
    opens = datetime.now(UTC)
    body = {
        "externalId": f"seed-v1-meeting-{int(opens.timestamp())}",
        "subject": MEETING_SUBJECT,
        "startDateTime": opens.isoformat(timespec="seconds"),
        "endDateTime": (opens + timedelta(hours=2)).isoformat(timespec="seconds"),
        "participants": {"attendees": others},
    }
    made = graph(
        "POST", "/me/onlineMeetings/createOrGet", token_, "teams_create_meeting", upns, body
    )
    STATE.mkdir(exist_ok=True)
    saved = {"id": made["id"], "join_url": made["joinWebUrl"], "subject": MEETING_SUBJECT}
    _ = (STATE / "meeting.json").write_text(json.dumps(saved, indent=2, sort_keys=True))
    print(instructions(saved["join_url"]))


def meeting_wait(
    upns: Sequence[str],
    dry: bool,
    sh: Shell,
    get: Callable[[str, str], int],
    sleep: Callable[[float], None],
) -> int:
    held = meeting_state()
    if held is None and not dry:
        raise MeetingFailed("no .record-all/meeting.json: run record_all.sh meeting start")
    base = f"/me/onlineMeetings/{quote(held['id'], safe='') if held else '{meeting}'}"
    kinds = ("transcripts", "recordings", "attendanceReports")
    if dry:
        print(f"would poll every {MEETING_POLL} seconds, {MEETING_POLLS} times, GET {base}/<kind>")
        print(f"kinds: {', '.join(kinds)}; ready when a transcript and a recording exist")
        return 0
    for number in range(1, MEETING_POLLS + 1):
        asked = token(sh, upns[0], MEETING_TOOLS)
        counts = {kind: get(asked, f"{base}/{kind}") for kind in kinds}
        print(f"poll {number}/{MEETING_POLLS}: " + ", ".join(f"{k} {n}" for k, n in counts.items()))
        if counts["transcripts"] and counts["recordings"]:
            return 0
        if number < MEETING_POLLS:
            sleep(MEETING_POLL)
    print("timeout: no transcript and recording after 120 minutes", file=sys.stderr)
    return 3


def meeting(
    step: str, upns: Sequence[str], dry: bool, force: bool, found: Callable[[bool], list[Run]]
) -> int:
    for one in ("start", "wait", "record") if step == "all" else (step,):
        print(f"== meeting {one}{' (dry run, nothing is sent)' if dry else ''} ==")
        if one == "start":
            meeting_start(upns, dry, shell, force)
        elif one == "wait":
            if code := meeting_wait(upns, dry, shell, probed, time.sleep):
                return code
        else:
            discover(upns, dry, shell, probed, ("teams-meeting",))
            if dry:
                results = dry_results(found(True), upns)
            else:
                STATE.mkdir(exist_ok=True)
                results = execute(found(False), upns, shell, time.sleep, STATE / "results.json")
            for name, one_result in sorted(results.items()):
                print(f"{name}: {one_result['status']} {one_result['note']}".rstrip())
            if any(
                one_result["status"] in ("refused", "blocked") for one_result in results.values()
            ):
                return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return _main(argv)
    except SignInRequired as stop:
        print(stop, file=sys.stderr)
        return 3
    except MeetingFailed as stop:
        print(stop, file=sys.stderr)
        return 1


def _main(argv: Sequence[str] | None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = ["login", "discover", "seed", "record", "check", "report"]
    parser.add_argument("mode", choices=[*modes, "all", "meeting"])
    parser.add_argument("step", nargs="?", choices=["start", "wait", "record", "all"])
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args(argv)
    chosen = cast("str", arguments.mode)
    step = cast("str | None", arguments.step)
    if (chosen == "meeting") != (step is not None):
        parser.error("meeting takes one step: start, wait, record or all; no other mode does")
    dry = cast("bool", arguments.dry_run)
    upns = stand_in.UPNS if dry else tuple(os.environ.get("SEED_UPNS", "").split(","))
    if not dry and len(upns) != PERSONAS:
        print("SEED_UPNS must list the three test users: Mia, Anna, Tom.", file=sys.stderr)
        return 2
    wanted = cast("list[str]", arguments.case) or (list(MEETING_CASES) if step else [])
    loaded = catalogs()
    every = [resolve(case, loaded=loaded) for case, _ in case_entries()]
    plans = [one for one in every if not wanted or one.scenario in wanted]

    def found(assume_meeting: bool = False) -> list[Run]:
        known = STATE / "discover.json"
        discovered = cast(
            "Mapping[str, bool]", json.loads(known.read_text()) if known.is_file() else {}
        )
        discovered = {**discovered, "teams-meeting": True} if assume_meeting else discovered
        stored = frozenset(one.stem for one in FIXTURES.glob("*.json"))
        return plan_runs(plans, stored, discovered, cast("bool", arguments.force))

    results: Results = {}
    if step:
        return meeting(step, upns, dry, cast("bool", arguments.force), found)
    for mode in modes if chosen == "all" else [chosen]:
        print(f"== {mode}{' (dry run, nothing is sent)' if dry else ''} ==")
        code = 0
        if mode == "login":
            code = login(upns, dry, shell, sorted({name for one in every for name in one.scopes}))
        elif mode == "discover":
            discover(upns, dry, shell, probed)
        elif mode == "seed":
            apply = [str(SCRIPTS / "run_all.sh"), "apply"]
            commands = (
                [_python(str(SCRIPTS / "seed" / "seed.py"), "plan")]
                if dry
                else [
                    [*apply, "2", "3", "1"],
                    [*apply, "--phases", ",".join(TEAM_PHASES), "1", "2", "3"],
                ]
            )
            for command in commands:
                done = shell(command, {"SEED_UPNS": ",".join(upns)})
                lines = done.stdout.splitlines()
                print("\n".join(lines[-4:] if dry else lines))
                print(done.stderr, end="", file=sys.stderr)
                code = done.returncode
                if code:
                    break
        elif mode == "record":
            if dry:
                results = dry_results(found(), upns)
            else:
                STATE.mkdir(exist_ok=True)
                results = execute(found(False), upns, shell, time.sleep, STATE / "results.json")
        elif mode == "check":
            code = check(dry)
        else:
            saved = STATE / "results.json"
            if not results and not dry and saved.is_file():
                results = cast("Results", json.loads(saved.read_text()))
            text = report(results or dry_results(found(), upns))
            print(text)
            if not dry:
                STATE.mkdir(exist_ok=True)
                _ = (STATE / "report.md").write_text(text)
        if code:
            return code
    return 0


if __name__ == "__main__":
    sys.exit(main())
