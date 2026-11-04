"""Offline tests for the core of seed.py: the guard allow-list, the caps for each phase, the upload
session, the extra addresses, the phase hooks and the exact-size generators."""

import datetime as dt
import hashlib
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import docgen
import seed
from model import ConfigError, Context, Step
from test_seed import ANCHOR, ENV, UPNS, FakeGraph, run

TEAM = "11111111-2222-4333-8444-555555555555"
OTHER = "99999999-2222-4333-8444-555555555555"
CHAT = "19:abc@thread.v2"
SHARED = "shared@dogfood.test"
EXTRAS = {name: f"{name.lower()}@dogfood.test" for name in seed.EXTRA_ENV} | {
    seed.SHARED_ENV: SHARED
}


def graph(sent: list[httpx.Request] | None = None, **fields: Any) -> seed.Graph:
    def answer(request: httpx.Request) -> httpx.Response:
        if sent is not None:
            sent.append(request)
        return httpx.Response(200, json={})

    made = seed.Graph("tok", transport=httpx.MockTransport(answer), **fields)
    made.me_id = "me-1"
    return made


def corpus_dir(tmp_path: Path, **edits: Any) -> Path:
    target = tmp_path / "corpus"
    shutil.copytree(seed.CORPUS_DIR, target)
    for name, edit in edits.items():
        loaded = yaml.safe_load((target / f"{name}.yaml").read_text())
        edit(loaded)
        (target / f"{name}.yaml").write_text(yaml.safe_dump(loaded, sort_keys=False))
    return target


def context(extras: dict[str, str] | None = None, corpus: Path = seed.CORPUS_DIR) -> Context:
    return Context(seed.load_corpus(corpus), UPNS, dt.date(2026, 10, 23), "extprops", extras or {})


class TestMemberPaths:
    ALLOWED = (
        ("GET", f"/teams/{TEAM}/channels"),
        ("POST", f"/teams/{TEAM}/channels/c1/messages/m1/replies"),
        ("GET", f"/groups/{TEAM}/events"),
        ("GET", f"/groups/{TEAM}/calendar"),
        ("GET", f"/groups/{TEAM}/calendarView"),
        ("GET", f"/groups/{TEAM}/drive"),
        ("GET", f"/groups/{TEAM}/members"),
        ("POST", f"/groups/{TEAM}/members/$ref"),
        ("POST", f"/groups/{TEAM}/onenote/notebooks"),
        ("GET", "/drives/b!drive/items/i1"),
        ("POST", f"/chats/{CHAT}/messages"),
    )

    def learned(self, sent: list[httpx.Request] | None = None) -> seed.Graph:
        made = graph(sent)
        made.learn("team", TEAM)
        made.learn("drive", "b!drive")
        made.learn("chat", CHAT)
        return made

    @pytest.mark.parametrize(("method", "path"), ALLOWED)
    def test_a_path_of_a_learned_member_id_goes_through(self, method: str, path: str) -> None:
        sent: list[httpx.Request] = []
        assert self.learned(sent).request(method, path).status_code == 200
        assert len(sent) == 1

    @pytest.mark.parametrize(("method", "path"), ALLOWED)
    def test_the_same_path_is_refused_before_the_id_is_learned(
        self, method: str, path: str
    ) -> None:
        sent: list[httpx.Request] = []
        with pytest.raises(seed.Refused):
            graph(sent).request(method, path)
        assert sent == []

    @pytest.mark.parametrize(
        "path",
        [
            f"/teams/{OTHER}/channels",
            f"/groups/{OTHER}/events",
            "/drives/b!other/items/i1",
            "/chats/19:other@thread.v2/messages",
            f"/teams/{TEAM}/members",
            f"/groups/{OTHER}/members",
            f"/groups/{TEAM}",
            f"/chats/{CHAT}/members",
            f"/teams/{TEAM}",
        ],
    )
    def test_an_id_of_a_non_member_and_a_path_outside_the_list_are_refused(self, path: str) -> None:
        sent: list[httpx.Request] = []
        with pytest.raises(seed.Refused):
            self.learned(sent).request("GET", path)
        assert sent == []

    def test_another_host_is_refused_even_with_a_learned_id(self) -> None:
        with pytest.raises(seed.Refused):
            self.learned().request("GET", f"https://evil.example/v1.0/teams/{TEAM}/channels")

    def test_a_lookup_or_a_create_that_learns_opens_the_path(self) -> None:
        steps = [
            Step("teams", "lookup", "GET", "/me/joinedTeams", lookup="named", learns="team"),
            Step(
                "teams",
                "lookup",
                "GET",
                "/groups/{teams:seed-v1 team}/drive",
                key="drive:team",
                lookup="single",
                learns="drive",
            ),
            Step("teams", "create", "POST", "/drives/{drive:team}/root/children", key="made"),
        ]
        seen: list[str] = []

        def answer(request: httpx.Request) -> httpx.Response:
            seen.append(f"{request.method} {request.url.path}")
            if request.url.path.endswith("/joinedTeams"):
                return httpx.Response(
                    200, json={"value": [{"id": TEAM, "displayName": "seed-v1 team"}]}
                )
            if request.url.path.endswith("/drive"):
                return httpx.Response(200, json={"id": "b!drive"})
            return httpx.Response(201, json={"id": "new"})

        made = seed.Graph("t", transport=httpx.MockTransport(answer))
        made.me_id = "me-1"
        assert seed.apply(made, steps, context(), lambda _: None) == (1, 0)
        assert seen[-1] == "POST /v1.0/drives/b!drive/root/children"


class TestSending:
    def test_only_the_send_phase_sends_and_twelve_sends_at_most(self) -> None:
        sent: list[httpx.Request] = []
        made = graph(sent)
        with pytest.raises(seed.Refused, match="only the mail-people phase sends"):
            made.request("POST", "/me/sendMail", body={})
        made.phase = seed.SEND_PHASE
        for _ in range(seed.MAX_SENDS):
            assert made.request("POST", "/me/sendMail", body={}).status_code == 200
        with pytest.raises(seed.Refused, match="12 at most"):
            made.request("POST", "/me/sendMail", body={})
        assert len(sent) == seed.MAX_SENDS

    def test_a_recipient_outside_the_personas_is_refused_even_when_it_is_an_extra(self) -> None:
        body = {"message": {"toRecipients": [{"emailAddress": {"address": SHARED}}]}}
        steps = [Step("mail-people", "create", "POST", "/me/sendMail", body=body)]
        with pytest.raises(seed.Refused, match="not in SEED_UPNS"):
            seed.check_recipients(steps, UPNS, EXTRAS)
        other = [Step("mail", "create", "POST", "/me/messages", body=body)]
        seed.check_recipients(other, UPNS, EXTRAS)
        with pytest.raises(seed.Refused):
            seed.check_recipients(other, UPNS)


class TestSharedMailbox:
    def test_the_shared_mailbox_is_open_for_its_folders_only(self) -> None:
        sent: list[httpx.Request] = []
        made = graph(sent, shared_upn=SHARED)
        assert made.request("GET", f"/users/{SHARED}/mailFolders/inbox/messages").status_code == 200
        for path in (f"/users/{SHARED}/messages", "/users/anna@dogfood.test/mailFolders/inbox"):
            with pytest.raises(seed.Refused):
                made.request("GET", path)
        assert len(sent) == 1

    def test_without_the_variable_the_shared_mailbox_is_refused(self) -> None:
        with pytest.raises(seed.Refused):
            graph().request("GET", f"/users/{SHARED}/mailFolders/inbox/messages")


class TestUploadSession:
    def upload_graph(self, calls: list[httpx.Request]) -> seed.Graph:
        def answer(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if request.method == "POST":
                return httpx.Response(200, json={"uploadUrl": "https://up.example/s/1?x=1"})
            done = request.headers["content-range"].endswith(f"-{self.size - 1}/{self.size}")
            return httpx.Response(201 if done else 202, json={"id": "up-1"} if done else {})

        made = seed.Graph("tok", transport=httpx.MockTransport(answer))
        made.me_id = "me-1"
        return made

    size = 10 * 1024 * 1024

    def test_the_chunks_go_to_the_returned_url_without_the_token(self) -> None:
        calls: list[httpx.Request] = []
        made = self.upload_graph(calls)
        payload = docgen.filler(self.size, "t")
        steps = [
            Step(
                "files",
                "upload",
                "POST",
                "/me/drive/root:/seed-v1 Big.bin:/createUploadSession",
                body={"item": {}},
                key="file:seed-v1 Big.bin",
                payload=payload,
            )
        ]
        assert seed.apply(made, steps, context(), lambda _: None) == (1, 0)
        puts = [c for c in calls if c.method == "PUT"]
        assert len(puts) == 3
        assert [c.headers["content-range"].split("/")[0] for c in puts][:2] == [
            f"bytes 0-{seed.CHUNK - 1}",
            f"bytes {seed.CHUNK}-{2 * seed.CHUNK - 1}",
        ]
        assert b"".join(c.content for c in puts) == payload
        assert all("authorization" not in c.headers for c in puts)
        assert all(len(c.content) <= 4 * 1024 * 1024 for c in puts)
        assert all(c.url.host == "up.example" for c in puts)
        assert calls[0].headers["authorization"] == "Bearer tok"

    def test_the_url_is_open_for_one_put_session_only(self) -> None:
        sent: list[httpx.Request] = []
        made = graph(sent)
        made._upload_url = "https://up.example/s/1"  # pyright: ignore[reportPrivateUsage]
        assert made.request("PUT", "https://up.example/s/1").status_code == 200
        for method, url in (
            ("PUT", "https://up.example/s/2"),
            ("GET", "https://up.example/s/1"),
            ("PUT", "https://evil.example/s/1"),
        ):
            with pytest.raises(seed.Refused):
                made.request(method, url)
        made._upload_url = None  # pyright: ignore[reportPrivateUsage]
        with pytest.raises(seed.Refused):
            made.request("PUT", "https://up.example/s/1")
        assert len(sent) == 1

    def test_an_answer_without_an_https_url_is_refused(self) -> None:
        with pytest.raises(seed.GraphError, match="no https uploadUrl"):
            _ = graph().upload({"uploadUrl": "http://up.example/s"}, b"x")

    def test_a_large_file_of_the_corpus_becomes_an_upload_step_and_a_second_run_sends_nothing(
        self, tmp_path: Path
    ) -> None:
        spec = {"id": "big", "name": "Big.bin", "kind": "filler", "size": self.size, "label": "big"}
        corpus = corpus_dir(tmp_path, files=lambda files: files["files"].append(spec))
        ctx = context(corpus=corpus)
        steps = seed.file_steps(ctx, "mia", {"files"})
        upload = next(step for step in steps if step.kind == "upload")
        assert upload.path.endswith(":/createUploadSession")
        assert upload.generated == ("filler", self.size, "big")
        assert upload.payload is not None
        assert (
            hashlib.sha256(upload.payload).hexdigest()
            == hashlib.sha256(docgen.filler(self.size, "big")).hexdigest()
        )
        small = [s for s in steps if s.kind == "create" and s.method == "PUT"]
        assert small and all(isinstance(s.body, bytes) for s in small)
        manifest = seed.corpus_manifest(ctx)
        entry = next(b for b in manifest["binaries"] if b["name"] == "seed-v1 Big.bin")
        assert entry["size"] == self.size
        assert entry["sha256"] == hashlib.sha256(docgen.filler(self.size, "big")).hexdigest()
        assert (entry["generator"], entry["label"]) == ("filler", "big")
        assert "payload" not in entry and "contentBytes" not in str(entry)
        shown = "\n".join(seed.render_plan(ctx, 1, steps))
        assert f"upload <{self.size} bytes sha256=" in shown

    def test_a_large_attachment_is_left_out_of_the_message_and_uploaded_after_it(
        self, tmp_path: Path
    ) -> None:
        huge = {
            "id": "huge",
            "name": "Huge.bin",
            "kind": "filler",
            "size": self.size + 1,
            "label": "huge",
            "content_type": "application/octet-stream",
        }

        def attach(mail: dict[str, Any]) -> None:
            mail["messages"][0]["attachments"] = ["huge"]

        corpus = corpus_dir(
            tmp_path, files=lambda files: files["attachments"].append(huge), mail=attach
        )
        ctx = context(corpus=corpus)
        first = ctx.corpus["mail"]["messages"][0]
        assert "attachments" not in seed.message_body(first, ctx)
        steps = seed.attachment_steps(first, ctx)
        assert [s.kind for s in steps] == ["lookup", "upload"]
        assert steps[0].lookup == "attachments"
        assert steps[1].body["AttachmentItem"]["size"] == self.size + 1
        assert steps[1].key == f"attachment:{first['id']}:Huge.bin"
        assert steps[1].payload == docgen.filler(self.size + 1, "huge")


class TestPhases:
    def test_the_cap_counts_for_each_phase(self) -> None:
        made = graph(max_requests=2)
        for phase in ("a", "b"):
            made.phase = phase
            made.request("GET", "/me")
            made.request("GET", "/me")
        made.phase = "a"
        with pytest.raises(seed.CapReached, match="phase a"):
            made.request("GET", "/me")
        assert made.count == 4

    def test_an_unknown_phase_is_refused_before_any_call(self) -> None:
        fake = FakeGraph()
        assert run(["apply", "--as", "1", "--phases", "files,nope"], fake) == ConfigError.code
        assert fake.calls == []

    def test_a_phase_list_selects_the_phases(self) -> None:
        fake = FakeGraph()
        assert run(["apply", "--as", "1", "--phases", "folders,files"], fake) == 0
        assert fake.messages == {} and fake.events == {}
        assert fake.drive.keys() - {"root"}

    def test_cleanup_calls_the_hook_of_a_family_for_its_phases_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        asked: list[set[str]] = []

        def hook(
            _graph: object, _ctx: object, owner: str, phases: set[str]
        ) -> Iterator[tuple[str, str, Any]]:
            asked.append(phases)
            yield (
                "PATCH",
                "/me/mailboxSettings",
                {"automaticRepliesSetting": {"status": "disabled"}},
            )
            yield "DELETE", f"/me/events/{owner}", None

        family = SimpleNamespace(
            PHASES=("cal-x", "cal-y"), steps=lambda *_: [], sweep=lambda *_: iter(()), cleanup=hook
        )
        monkeypatch.setattr(seed, "FAMILIES", (family,))
        monkeypatch.setattr(seed, "PHASES", (*seed.PHASES, "cal-x", "cal-y"))
        fake = FakeGraph()
        sent: list[tuple[str, str, bytes]] = []
        original = fake.handle

        def spy(request: httpx.Request) -> httpx.Response:
            if request.method in ("PATCH", "DELETE") and "/me/" in request.url.path:
                sent.append((request.method, request.url.path, request.content))
                return httpx.Response(204)
            return original(request)

        fake.handle = spy  # type: ignore[method-assign]
        assert run(["cleanup", "--as", "1", "--phases", "cal-x,mail"], fake) == 0
        assert asked == [{"cal-x"}]
        assert sent[0][0:2] == ("PATCH", "/v1.0/me/mailboxSettings")
        assert b'"disabled"' in sent[0][2]
        assert sent[1][:2] == ("DELETE", "/v1.0/me/events/mia")
        sent.clear()
        assert run(["cleanup", "--as", "1", "--phases", "mail"], fake) == 0
        assert sent == [] and asked == [{"cal-x"}]

    def test_a_sweep_may_name_a_body_and_a_two_part_tuple_still_works(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        swept = [
            ("PATCH", "/me/mailboxSettings", {"workingHours": {"x": 1}}),
            ("DELETE", "/me/events/e1"),
        ]
        family = SimpleNamespace(PHASES=(), steps=lambda *_: [], sweep=lambda *_: iter(swept))
        monkeypatch.setattr(seed, "FAMILIES", (family,))
        sent: list[tuple[str, bytes]] = []
        fake = FakeGraph()
        original = fake.handle

        def spy(request: httpx.Request) -> httpx.Response:
            if request.method in ("PATCH", "DELETE"):
                sent.append((request.method, request.content))
                return httpx.Response(204)
            return original(request)

        fake.handle = spy  # type: ignore[method-assign]
        assert run(["cleanup", "--cases", "--as", "1"], fake) == 0
        assert sent == [("PATCH", b'{"workingHours":{"x":1}}'), ("DELETE", b"")]


class TestFolders:
    def test_two_folders_with_one_name_at_different_levels_are_two_folders_and_one_run_makes_them_once(
        self, tmp_path: Path
    ) -> None:
        def edit(folders: dict[str, Any]) -> None:
            folders["folders"] += [
                {"key": "top-archive", "name": "Archive"},
                {"key": "deep-archive", "name": "Archive", "parent": "top-archive"},
            ]

        corpus = corpus_dir(tmp_path, folders=edit)
        fake = FakeGraph()
        argv = ["apply", "--as", "1", "--phases", "folders", "--corpus", str(corpus)]
        assert run(argv, fake) == 0
        names = [f["displayName"] for f in fake.folders.values()]
        assert names.count("seed-v1 Archive") == 4
        before = len(fake.folders)
        assert run(argv, fake) == 0
        assert len(fake.folders) == before

    def test_a_message_may_sit_in_the_junk_or_the_deleted_folder(self) -> None:
        assert {"junkemail", "deleteditems"} <= seed.WELL_KNOWN_FOLDERS


class TestExtras:
    def test_the_four_addresses_come_from_the_environment_and_must_all_differ(self) -> None:
        found = seed.read_extras({**ENV, **EXTRAS}, UPNS, required=True)
        assert found == EXTRAS
        assert seed.read_extras(ENV, UPNS, required=True) == {}
        placeholders = seed.read_extras(ENV, UPNS, required=False)
        assert set(placeholders) == set(seed.EXTRA_ENV)
        assert all(value.endswith("@seed.invalid") for value in placeholders.values())
        for bad in (
            {"SEED_ROOM_UPN": UPNS[0]},
            {"SEED_ROOM_UPN": "a@b.test", "SEED_GUEST_UPN": "a@b.test"},
        ):
            with pytest.raises(ConfigError, match="must all differ"):
                _ = seed.read_extras(bad, UPNS, required=True)
        for bad in ("nobody", "a@b@c.test", "@x.test", "a@x.test,b@x.test"):
            with pytest.raises(ConfigError, match="must hold one address"):
                _ = seed.read_extras({"SEED_GUEST_UPN": bad}, UPNS, required=True)

    def test_an_env_placeholder_is_an_address_and_a_missing_variable_is_named(self) -> None:
        ctx = context(EXTRAS)
        assert ctx.address("env:SEED_ROOM_UPN") == {
            "emailAddress": {"address": EXTRAS["SEED_ROOM_UPN"]}
        }
        with pytest.raises(ConfigError, match="SEED_GUEST_UPN"):
            _ = context().address("env:SEED_GUEST_UPN")

    def test_an_extra_address_in_a_path_passes_the_recipient_check(self) -> None:
        step = Step("mail-shared", "lookup", "GET", f"/users/{SHARED}/mailFolders/inbox/messages")
        seed.check_recipients([step], UPNS, EXTRAS)
        with pytest.raises(seed.Refused):
            seed.check_recipients([step], UPNS)

    def test_apply_with_a_malformed_variable_sends_nothing(self) -> None:
        fake = FakeGraph()
        env = {**ENV, "SEED_ROOM_UPN": "room"}
        assert run(["apply", "--as", "1", "--phases", "files"], fake, env=env) == ConfigError.code
        assert fake.calls == []


class TestGenerators:
    @pytest.mark.parametrize("size", [10485760, 10485761, 2000, 1000000])
    def test_a_generator_gives_the_exact_size_and_the_same_bytes_every_time(
        self, size: int
    ) -> None:
        for generator in ("filler", "filler-text"):
            first = docgen.generate(generator, size, "label")
            assert len(first) == size
            assert first == docgen.generate(generator, size, "label")
            assert first != docgen.generate(generator, size, "other")
        assert docgen.generate("filler-text", size, "label").decode("ascii").isprintable()

    def test_the_hash_of_a_generated_file_is_stable(self) -> None:
        raw = docgen.generate("filler", 10485760, "seed-v1 filler")
        assert (
            hashlib.sha256(raw).hexdigest()
            == "9117ba669ded1925250fb4c4770a2b54de25a18ab22e2f16725b1b16525d58ff"
        )
        text = docgen.generate("filler-text", 2000, "seed-v1 text")
        assert (
            hashlib.sha256(text).hexdigest()
            == "724bc6fc8d27268ac1c856645b130139509119adc1322158817f364afa68dd7b"
        )

    def test_a_page_has_the_exact_size_and_a_title_and_a_name_with_no_generator_is_refused(
        self,
    ) -> None:
        page = docgen.generate("onenote-html", 900_000, "seed-v1 Big page")
        assert len(page) == 900_000
        assert page.startswith(b"<!DOCTYPE html><html><head><title>seed-v1 Big page</title>")
        with pytest.raises(ValueError, match="at least"):
            _ = docgen.generate("onenote-html", 10, "x")
        with pytest.raises(ValueError, match="no generator named"):
            _ = docgen.generate("zip", 10, "x")


class TestRunAll:
    def run(self, tmp_path: Path, *arguments: str) -> list[str]:
        scripts = tmp_path / "scripts" / "dogfood"
        scripts.mkdir(parents=True)
        shutil.copy(HERE.parent / "run_all.sh", scripts / "run_all.sh")
        python = tmp_path / ".venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.write_text(f'#!/bin/sh\necho "$@" >> {tmp_path}/calls\necho token\n')
        python.chmod(0o755)
        env = {
            **os.environ,
            "ENTRA_TENANT_ID": "t",
            "ENTRA_CLIENT_ID": "c",
            "SEED_UPNS": ",".join(UPNS),
        }
        done = subprocess.run(
            ["bash", str(scripts / "run_all.sh"), *arguments],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        assert done.returncode == 0, done.stderr
        return [line for line in (tmp_path / "calls").read_text().splitlines() if "seed.py" in line]

    def test_the_phases_and_the_order_of_the_indexes_reach_the_seed(self, tmp_path: Path) -> None:
        calls = self.run(tmp_path, "cleanup", "--phases", "cal-invites,cal-answers", "2", "3", "1")
        assert [call.rpartition("seed.py ")[2] for call in calls] == [
            f"cleanup --as {index} --phases cal-invites,cal-answers" for index in (2, 3, 1)
        ]

    def test_without_phases_nothing_is_added_and_the_indexes_default_to_all_three(
        self, tmp_path: Path
    ) -> None:
        calls = self.run(tmp_path, "apply")
        assert [call.rpartition("seed.py ")[2] for call in calls] == [
            f"apply --as {index}" for index in (1, 2, 3)
        ]

    def test_cleanup_cases_deletes_the_cases_and_takes_no_phases(self, tmp_path: Path) -> None:
        calls = self.run(tmp_path, "cleanup-cases", "2")
        assert [call.rpartition("seed.py ")[2] for call in calls] == ["cleanup --as 2 --cases"]


class TestChatsAndAnswers:
    def test_a_chat_is_created_and_nothing_else_of_chats_is_written(self) -> None:
        sent: list[httpx.Request] = []
        assert graph(sent).request("POST", "/chats").status_code == 200
        for method, path in (
            ("POST", f"/chats/{CHAT}/members"),
            ("POST", "/chats/"),
            ("GET", "/chats"),
            ("PATCH", "/chats"),
            ("DELETE", f"/chats/{CHAT}"),
        ):
            with pytest.raises(seed.Refused):
                graph(sent).request(method, path)
        with pytest.raises(seed.Refused):
            graph(sent).request("POST", "https://evil.example/v1.0/chats")
        assert len(sent) == 1

    def test_an_answer_with_no_body_or_no_id_lets_the_next_step_run(self) -> None:
        seen: list[str] = []

        def answer(request: httpx.Request) -> httpx.Response:
            seen.append(f"{request.method} {request.url.path}")
            if request.url.path.endswith("/accept"):
                return httpx.Response(202)
            return httpx.Response(200, json={"automaticRepliesSetting": {}})

        steps = [
            Step("x", "create", "POST", "/me/events/e1/accept", key="accepted"),
            Step("x", "create", "PATCH", "/me/mailboxSettings", key="settings"),
            Step("x", "create", "POST", "/me/things/{accepted}/{settings}", key="done"),
        ]
        made = seed.Graph("tok", transport=httpx.MockTransport(answer))
        made.me_id = "me-1"
        assert seed.apply(made, steps, context(), lambda _: None) == (3, 0)
        assert seen[-1] == "POST /v1.0/me/things/accepted/settings"

    def test_the_opt_in_phases_are_left_out_unless_they_are_named(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert seed.main(["plan", *ANCHOR], env=ENV) == 0
        default = capsys.readouterr().out
        assert seed.main(["plan", *ANCHOR, "--phases", "teams-posts"], env=ENV) == 0
        named = capsys.readouterr().out
        assert {"teams", "teams-posts", "teams-chats"} <= seed.OPT_IN
        assert "teams-posts" not in default and "seed-v1 post" not in default
        assert "teams-posts" in named

    def test_a_cleanup_hook_may_yield_a_pair(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def hook(
            _graph: object, _ctx: object, owner: str, _phases: set[str]
        ) -> Iterator[tuple[str, str]]:
            yield "DELETE", f"/me/events/{owner}"

        family = SimpleNamespace(
            PHASES=("pair-x",), steps=lambda *_: [], sweep=lambda *_: iter(()), cleanup=hook
        )
        monkeypatch.setattr(seed, "FAMILIES", (family,))
        out: list[str] = []
        sent: list[httpx.Request] = []
        deleted = seed.cleanup(graph(sent), context(), 1, {"pair-x"}, False, out.append)
        assert (deleted, out) == (1, ["delete DELETE /me/events/mia"])
        assert [(r.method, r.content) for r in sent] == [("DELETE", b"")]


class TestPathsThatLeaveTheOwnData:
    @pytest.mark.parametrize(
        "path",
        [
            "/me/../users/x/messages",
            "/me/./../users/x",
            "/me/%2e%2e/users/x",
            "/me/%2E%2E/users/x",
            "/me/..%2fusers/x",
            "/me/%252e%252e/users/x",
            "/me/..%5cusers/x",
            "/me//messages",
            "/me/messages/",
            "/me/messages/1/send",
            "/me/messages/1/forward",
            "/me/messages/1/reply",
            "/me/messages/1/replyAll",
            "/me/mailFolders/inbox/messages/1/send",
            "/me/events/1/forward",
            "/users/me-1/messages/1/send",
            "/users('me-1')/events/1/forward",
        ],
    )
    def test_a_dot_segment_an_empty_segment_or_a_send_endpoint_is_refused(self, path: str) -> None:
        sent: list[httpx.Request] = []
        with pytest.raises(seed.Refused):
            graph(sent).request("POST", path)
        assert sent == []

    @pytest.mark.parametrize("path", ["/me/sendMail", "/users/me-1/sendMail"])
    def test_every_spelling_of_sendmail_stays_inside_the_send_phase_and_its_limit(
        self, path: str
    ) -> None:
        sent: list[httpx.Request] = []
        outside = graph(sent)
        outside.phase = "mail"
        with pytest.raises(seed.Refused):
            outside.request("POST", path)
        inside = graph(sent)
        inside.phase = seed.SEND_PHASE
        for _ in range(seed.MAX_SENDS):
            assert inside.request("POST", path).status_code == 200
        with pytest.raises(seed.Refused):
            inside.request("POST", path)
        assert len(sent) == seed.MAX_SENDS

    @pytest.mark.parametrize(
        "path",
        [
            "/me/events/1/cancel",
            "/me/events/1/accept",
            "/me/mailFolders/inbox/messages",
            "/me/drive/root:/seed-v1 Seed Files:/children",
            "/me/messages/1/attachments",
            "/me/onenote/pages/1-a!1-b/content",
        ],
    )
    def test_the_neighbors_that_the_seed_uses_still_go_through(self, path: str) -> None:
        assert graph().request("POST", path).status_code == 200
