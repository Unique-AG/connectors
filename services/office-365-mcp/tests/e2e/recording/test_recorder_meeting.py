import json
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import cast, final

import httpx
import pytest

from tests.e2e.recording import runbook, stand_in
from tests.e2e.recording.families import load
from tests.e2e.recording.families.teams import vtt
from tests.e2e.recording.guard import GRAPH_HOST, Guard, Refused
from tests.e2e.recording.lint import lint_files
from tests.e2e.recording.record import GRAPH, resolve
from tests.e2e.recording.runbook import MeetingFailed, main
from tests.e2e.recording.scrub import (
    Hop,
    Identities,
    Recording,
    files_of,
    load_corpus,
    scrub,
)
from tests.e2e.recording.test_recorder_runbook import Calls
from tests.e2e.test_scenarios import Json, mapping

MEETING = "MSo1N2Y5ZGZiYS0wMDAwLTRhYWEtODAwMC0wMDAwMDAwMDAwMDA*0**"
SCRUBBED_MEETING = "MSo1N2Y5ZGZiYS0wMDAwLTRhYWEtODAwMC0wMDAwMDAwMDAwMDA"
TRANSCRIPT = "MSMjMCMjODRlYTI5NTAtMDAwMC00MDAwLTgwMDAtMDAwMDAwMDAwMDAx"
JOIN_URL = "https://teams.microsoft.com/l/meetup-join/19%3ameeting_abc%40thread.v2/0"
SPOKEN = "Welcome everybody, the secret launch plan starts on Monday."
RAW = (
    "﻿WEBVTT\r\n\r\n"
    "7f2c1a9e-5b1d-4e6f-8a9b-0c1d2e3f4a5b/12-0\r\n"
    f"00:00:01.280 --> 00:00:04.560\r\n<v Valerio Real>{SPOKEN}</v>\r\n\r\n"
    "7f2c1a9e-5b1d-4e6f-8a9b-0c1d2e3f4a5b/13-0\r\n"
    "00:00:05.000 --> 00:00:07.250 align:start\r\n<v Anna Meier>Budget &amp; scope.</v>\r\n\r\n"
    "NOTE private note about Valerio\r\n"
)
UPNS = stand_in.UPNS
HEADERS = (("content-type", "text/vtt; charset=utf-8"),)


def kept(value: str) -> str:
    return value


def hop(path: str, body: bytes, headers: tuple[tuple[str, str], ...]) -> Hop:
    asked: Json = {"method": "GET", "host": GRAPH_HOST, "path": path, "query": {}}
    asked |= {"headers": {}, "json": None}
    return Hop(asked, f"https://{GRAPH_HOST}{path}", False, 200, headers, body)


def recording_of(*hops: Hop) -> Recording:
    corpus = load_corpus()
    personas = {UPNS[one.index - 1].casefold(): one.key for one in corpus.personas}
    return Recording(
        "teams",
        "rec-tool-teams",
        "stand-in",
        datetime.now(UTC),
        hops,
        Identities(frozenset(), "token"),
        personas,
        frozenset(),
    )


def members() -> Hop:
    person = {"id": MEMBERSHIP, "displayName": "Valerio Real", "email": UPNS[0]}
    answer = {"value": [{**person, "userId": stand_in.USER_ID}]}
    return hop(f"/v1.0/chats/{CHAT}/members", json.dumps(answer).encode(), JSON)


JSON = (("content-type", "application/json"),)
CHAT = "19:Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MGFi@thread.v2"
MEMBERSHIP = "MCOrVGKkEno5PZQwMpxcZRO8Ka54QYSfVIhyRGUsDdY0BFY8FQIaMNBmToFfELt5YY="
CONTENT = f"/v1.0/me/onlineMeetings/{SCRUBBED_MEETING}/transcripts/{TRANSCRIPT}/content"


class TestTheVttScrub:
    def test_it_keeps_the_timing_and_numbers_the_cues(self) -> None:
        out = vtt(kept, RAW).splitlines()
        assert out[:4] == ["WEBVTT", "", "cue-1", "00:00:01.280 --> 00:00:04.560"]
        assert "00:00:05.000 --> 00:00:07.250" in out
        assert "cue-2" in out

    def test_it_drops_cue_settings_notes_and_raw_identifiers(self) -> None:
        out = vtt(kept, RAW)
        for dropped in ("align:start", "NOTE", "7f2c1a9e", "/12-0"):
            assert dropped not in out

    def test_it_passes_each_speaker_and_each_spoken_line_through_the_text_callback(self) -> None:
        seen: list[str] = []

        def spy(value: str) -> str:
            seen.append(value)
            return value

        _ = vtt(spy, RAW)
        assert seen == [SPOKEN, "Valerio Real", "Budget & scope.", "Anna Meier"]

    def test_a_line_with_no_speaker_stays_a_plain_line(self) -> None:
        raw = "WEBVTT\n\nid\n00:00:01.000 --> 00:00:02.000\nhello <c.loud>there</c>\n"
        assert vtt(kept, raw).endswith("\nhello there\n")

    def test_a_cue_with_no_words_is_dropped(self) -> None:
        raw = "WEBVTT\n\nid\n00:00:01.000 --> 00:00:02.000\n<v A></v>\n"
        assert vtt(kept, raw) == "WEBVTT\n"

    def test_the_scrubbed_text_scrubs_to_itself(self) -> None:
        once = vtt(kept, RAW)
        assert vtt(kept, once) == once


class TestTheVttBodyOfARecording:
    def scrubbed(self) -> tuple[dict[str, bytes], str]:
        fixture = scrub(recording_of(members(), hop(CONTENT, RAW.encode(), HEADERS)))
        return files_of(fixture), fixture.bodies["rec-tool-teams.02.vtt"].decode()

    def test_the_spoken_words_become_synthetic_text_and_the_timing_stays(self) -> None:
        _, body = self.scrubbed()
        assert SPOKEN not in body
        assert "synthetic text" in body
        assert "00:00:01.280 --> 00:00:04.560" in body

    def test_a_speaker_that_a_member_list_named_becomes_the_persona(self) -> None:
        _, body = self.scrubbed()
        assert "<v Mia Keller>" in body
        assert "Valerio" not in body

    def test_the_fixture_serves_the_body_with_its_media_type_and_passes_the_lint(self) -> None:
        files, _ = self.scrubbed()
        interactions = cast(
            "list[dict[str, object]]", json.loads(files["fixtures/rec-tool-teams.json"])
        )
        assert interactions[1]["body"] == "rec-tool-teams.02.vtt"
        assert interactions[1]["response_headers"] == {"content-type": "text/vtt; charset=utf-8"}
        assert lint_files(files) == []

    def test_a_media_type_that_has_no_scrub_still_stops_as_a_binary(self) -> None:
        other = hop(CONTENT, RAW.encode(), (("content-type", "application/octet-stream"),))
        with pytest.raises(Refused, match="binary body"):
            _ = scrub(recording_of(other))

    @pytest.mark.parametrize(
        ("old", "new", "finding"),
        [
            ("synthetic text 02", SPOKEN, "not corpus text"),
            ("cue-1", "7f2c1a9e-5b1d-4e6f-8a9b-0c1d2e3f4a5b/12-0", "not a cue identifier"),
            ("WEBVTT\n", "WEBVTT\nNOTE Valerio\n", "not a cue identifier"),
        ],
    )
    def test_the_lint_refuses_a_body_that_the_scrub_would_change(
        self, old: str, new: str, finding: str
    ) -> None:
        files, body = self.scrubbed()
        files["bodies/rec-tool-teams.02.vtt"] = body.replace(old, new, 1).encode()
        assert any(finding in one for one in lint_files(files))


class TestTheTranscriptGuard:
    def guard(self) -> Guard:
        return Guard(UPNS[0], frozenset(UPNS), True, me_id=stand_in.USER_ID)

    def ask(self, method: str, path: str) -> httpx.Request:
        return httpx.Request(method, f"{GRAPH}{path}")

    def test_the_tool_is_a_read_tool(self) -> None:
        assert "teams_read_transcript" in load().read_tools
        assert self.guard().refuses_call("teams_read_transcript", {"uri": "x"}) is None

    def test_the_content_of_the_users_own_transcript_may_be_read(self) -> None:
        path = f"/me/onlineMeetings/{MEETING}/transcripts/{TRANSCRIPT}/content"
        assert self.guard().refuses_request(self.ask("GET", path), "teams_read_transcript") is None

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("GET", f"/users/someone-else/onlineMeetings/{MEETING}/transcripts/{TRANSCRIPT}"),
            ("GET", f"/communications/onlineMeetings/{MEETING}/transcripts"),
            ("POST", f"/me/onlineMeetings/{MEETING}/transcripts/{TRANSCRIPT}/content"),
            ("DELETE", f"/me/onlineMeetings/{MEETING}/transcripts/{TRANSCRIPT}"),
            ("PATCH", f"/me/onlineMeetings/{MEETING}/transcripts/{TRANSCRIPT}"),
        ],
    )
    def test_any_other_path_or_a_write_is_refused(self, method: str, path: str) -> None:
        request = self.ask(method, path)
        assert self.guard().refuses_request(request, "teams_read_transcript") is not None


@final
class FakeGraph:
    def __init__(self, answers: Mapping[str, object]) -> None:
        self.answers: dict[str, object] = dict(answers)
        self.sent: list[httpx.Request] = []

    def __call__(self, request: httpx.Request, **_: object) -> httpx.Response:
        self.sent.append(request)
        answer = self.answers.get(f"{request.method} {request.url.path}")
        return httpx.Response(404 if answer is None else 200, json=answer or {})

    @property
    def lines(self) -> list[str]:
        return [f"{one.method} {one.url.path}" for one in self.sent]


def meeting_paths(kind: str) -> str:
    return f"GET /v1.0/me/onlineMeetings/{MEETING.replace('*', '%2A')}/{kind}"


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(runbook, "STATE", tmp_path / "state")
    monkeypatch.setattr(runbook, "FIXTURES", tmp_path / "fixtures")
    (tmp_path / "fixtures").mkdir()
    return tmp_path / "state"


def held(state: Path) -> None:
    state.mkdir()
    saved = {"id": MEETING, "join_url": JOIN_URL, "subject": runbook.MEETING_SUBJECT}
    _ = (state / "meeting.json").write_text(json.dumps(saved))


class TestStart:
    def graph(self, monkeypatch: pytest.MonkeyPatch) -> FakeGraph:
        fake = FakeGraph(
            {
                f"GET /v1.0/users/{UPNS[1]}": {"id": "anna-id"},
                f"GET /v1.0/users/{UPNS[2]}": {"id": "tom-id"},
                "POST /v1.0/me/onlineMeetings/createOrGet": {"id": MEETING, "joinWebUrl": JOIN_URL},
            }
        )
        monkeypatch.setattr(httpx.Client, "send", fake)
        return fake

    def test_it_creates_the_meeting_with_anna_and_writes_its_id_and_join_url(
        self, state: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake = self.graph(monkeypatch)
        runbook.meeting_start(UPNS, False, Calls(state), False)
        posted = mapping(cast("object", json.loads(fake.sent[2].content)))
        assert posted["subject"] == "seed-v1 meeting"
        assert mapping(posted["participants"])["attendees"] == [
            {"upn": UPNS[1], "identity": {"user": {"id": "anna-id"}}},
            {"upn": UPNS[2], "identity": {"user": {"id": "tom-id"}}},
        ]
        assert json.loads((state / "meeting.json").read_text()) == {
            "id": MEETING,
            "join_url": JOIN_URL,
            "subject": "seed-v1 meeting",
        }
        out = capsys.readouterr().out
        assert JOIN_URL in out
        assert "Join as Mia in the Teams app. Join as Anna in a private window." in out
        assert "More > Record and transcribe > Start" in out
        assert "meeting policy must allow recording" in out
        assert "Join as Tom in a second private window." in out
        assert "Anna: Anna sends the budget file by Friday." in out
        assert out.count(": ") >= 8

    def test_it_asks_for_the_scopes_of_the_create_tool_only(
        self, state: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _ = self.graph(monkeypatch)
        calls = Calls(state)
        runbook.meeting_start(UPNS, False, calls, False)
        assert calls.commands[0][-5:] == [
            "--silent",
            "--scopes-for",
            "teams_create_meeting",
            "--scopes",
            "User.ReadBasic.All",
        ]

    def test_a_second_start_keeps_the_meeting_unless_forced(
        self, state: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake = self.graph(monkeypatch)
        held(state)
        runbook.meeting_start(UPNS, False, Calls(state), False)
        assert fake.sent == []
        assert JOIN_URL in capsys.readouterr().out
        runbook.meeting_start(UPNS, False, Calls(state), True)
        assert fake.lines[-1] == "POST /v1.0/me/onlineMeetings/createOrGet"

    def test_a_failed_answer_stops_and_writes_nothing(
        self, state: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(httpx.Client, "send", FakeGraph({}))
        with pytest.raises(MeetingFailed, match="answered 404"):
            runbook.meeting_start(UPNS, False, Calls(state), False)
        assert not (state / "meeting.json").exists()

    def test_the_guard_refuses_an_attendee_who_is_not_a_test_user(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeGraph({})
        monkeypatch.setattr(httpx.Client, "send", fake)
        body = {"participants": {"attendees": [{"upn": "ceo@evil.example"}]}}
        with pytest.raises(MeetingFailed, match="the guard refused"):
            _ = runbook.graph(
                "POST", "/me/onlineMeetings/createOrGet", "t", "teams_create_meeting", UPNS, body
            )
        assert fake.sent == []

    def test_the_guard_refuses_another_write_path_for_the_create_tool(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(httpx.Client, "send", FakeGraph({}))
        with pytest.raises(MeetingFailed, match="the guard refused"):
            _ = runbook.graph("POST", "/me/chats", "t", "teams_create_meeting", UPNS, {})


def no_rows(*_: object) -> int:
    return 0


def one_row(*_: object) -> int:
    return 1


def never(*_: object) -> int:
    raise AssertionError("a request was sent")


class Clock:
    def __init__(self) -> None:
        self.slept: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.slept.append(seconds)


def counting(*rounds: tuple[int, int, int]) -> Callable[[str, str], int]:
    queue = [n for one in rounds for n in one]

    def get(_token: str, _path: str) -> int:
        return queue.pop(0)

    return get


class TestWait:
    def test_it_polls_every_two_minutes_until_a_transcript_and_a_recording_exist(
        self, state: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        held(state)
        clock = Clock()
        get = counting((0, 0, 0), (1, 0, 0), (1, 1, 1))
        assert runbook.meeting_wait(UPNS, False, Calls(state), get, clock) == 0
        assert clock.slept == [120, 120]
        out = capsys.readouterr().out
        assert "poll 1/60: transcripts 0, recordings 0, attendanceReports 0" in out
        assert "poll 3/60: transcripts 1, recordings 1, attendanceReports 1" in out

    def test_it_asks_for_the_artifacts_of_the_stored_meeting_with_a_fresh_token(
        self, state: Path
    ) -> None:
        held(state)
        calls = Calls(state)
        asked: list[str] = []

        def get(token: str, path: str) -> int:
            asked.append(f"{token} {path}")
            return 1

        assert runbook.meeting_wait(UPNS, False, calls, get, Clock()) == 0
        quoted = MEETING.replace("*", "%2A")
        assert asked == [
            f"tok-SECRET /me/onlineMeetings/{quoted}/{k}"
            for k in ("transcripts", "recordings", "attendanceReports")
        ]
        assert "teams_read_meeting" in calls.commands[0]

    def test_it_exits_3_after_120_minutes(
        self, state: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        held(state)
        clock = Clock()
        assert runbook.meeting_wait(UPNS, False, Calls(state), no_rows, clock) == 3
        assert len(clock.slept) == 59
        assert sum(clock.slept) == 118 * 60
        assert "timeout" in capsys.readouterr().err

    def test_a_transcript_alone_is_not_enough(self, state: Path) -> None:
        held(state)
        clock = Clock()
        only_a_transcript = counting(*([(1, 0, 1)] * 60))
        assert runbook.meeting_wait(UPNS, False, Calls(state), only_a_transcript, clock) == 3

    def test_it_stops_when_no_meeting_was_started(self, state: Path) -> None:
        with pytest.raises(MeetingFailed, match="meeting start"):
            _ = runbook.meeting_wait(UPNS, False, Calls(state), one_row, Clock())


class TestProbe:
    def test_the_meeting_need_reads_the_stored_meeting_and_its_transcripts(
        self, state: Path
    ) -> None:
        held(state)
        asked: list[str] = []

        def get(_token: str, path: str) -> int:
            asked.append(path)
            return 1

        runbook.discover(UPNS, False, Calls(state), get, ("teams-meeting",))
        assert asked == [f"/me/onlineMeetings/{MEETING.replace('*', '%2A')}/transcripts"]
        assert json.loads((state / "discover.json").read_text()) == {"teams-meeting": True}

    def test_with_no_stored_meeting_it_sends_nothing_and_the_need_stays_open(
        self, state: Path
    ) -> None:
        state.mkdir()
        _ = (state / "discover.json").write_text('{"teams-team": true}')
        runbook.discover(UPNS, False, Calls(state), never, ("teams-meeting",))
        assert json.loads((state / "discover.json").read_text()) == {
            "teams-meeting": False,
            "teams-team": True,
        }

    def test_the_probe_keeps_the_answers_of_the_other_probes(self, state: Path) -> None:
        held(state)
        _ = (state / "discover.json").write_text('{"teams-chat": false, "teams-team": true}')
        runbook.discover(UPNS, False, Calls(state), no_rows, ("teams-meeting",))
        assert json.loads((state / "discover.json").read_text()) == {
            "teams-chat": False,
            "teams-meeting": False,
            "teams-team": True,
        }


class TestCommandLine:
    @pytest.mark.parametrize("step", ["start", "wait", "record", "all"])
    def test_every_step_in_dry_run_sends_nothing_and_writes_nothing(
        self,
        step: str,
        state: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(httpx.Client, "send", never)
        assert main(["meeting", step, "--dry-run"]) == 0
        out = capsys.readouterr().out
        assert (
            f"== meeting {'start' if step == 'all' else step} (dry run, nothing is sent) ==" in out
        )
        assert not state.exists()

    @pytest.mark.usefixtures("state")
    def test_all_prints_the_instruction_box_once_and_would_record_the_four_cases(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["meeting", "all", "--dry-run"]) == 0
        out = capsys.readouterr().out
        assert out.count("Join as Mia in the Teams app") == 1
        for case in runbook.MEETING_CASES:
            assert f"{case}: would-record" in out
        assert "teams_list_message_replies" not in out

    def test_the_four_cases_exist_and_read_the_held_meeting(self) -> None:
        for case in runbook.MEETING_CASES:
            assert resolve(case).needs == ("teams-meeting",)

    @pytest.mark.parametrize("argv", [["meeting"], ["record", "start"], ["all", "wait"]])
    def test_a_step_belongs_to_the_meeting_mode_only(
        self, argv: list[str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as stop:
            _ = main(argv)
        assert stop.value.code == 2
        assert "meeting takes one step" in capsys.readouterr().err


class TestRecord:
    def run(
        self, state: Path, monkeypatch: pytest.MonkeyPatch, *, ready: bool
    ) -> tuple[int, Calls]:
        calls = Calls(state.parent / "fixtures")
        monkeypatch.setattr(runbook, "shell", calls)
        monkeypatch.setattr(runbook, "probed", one_row if ready else no_rows)
        monkeypatch.setattr(time, "sleep", Clock())
        monkeypatch.setenv("SEED_UPNS", ",".join(UPNS))
        return main(["meeting", "record"]), calls

    def test_the_cases_unblock_when_the_stored_meeting_has_a_transcript(
        self, state: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        held(state)
        code, calls = self.run(state, monkeypatch, ready=True)
        out = capsys.readouterr().out
        assert code == 0
        recorded = [c[3] for c in calls.commands if c[2:3] == ["tests.e2e.recording.record"]]
        assert set(recorded) == set(runbook.MEETING_CASES)
        for case in runbook.MEETING_CASES:
            assert f"{case}: recorded" in out

    def test_the_cases_stay_blocked_with_their_sentence_when_no_transcript_exists(
        self, state: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        held(state)
        code, calls = self.run(state, monkeypatch, ready=False)
        assert code == 1
        assert load().needs["teams-meeting"] in capsys.readouterr().out
        assert not [c for c in calls.commands if c[2:3] == ["tests.e2e.recording.record"]]

    def test_only_the_meeting_cases_run(self, state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        held(state)
        _, calls = self.run(state, monkeypatch, ready=True)
        names = {c[3] for c in calls.commands if c[2:3] == ["tests.e2e.recording.record"]}
        assert names <= set(runbook.MEETING_CASES)
