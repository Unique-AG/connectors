"""Offline tests for seed.py: a fake Graph (httpx.MockTransport) records every call."""

import base64
import io
import json
import logging
import re
import shutil
import subprocess
import sys
import textwrap
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import seed

UPNS = ("mia@dogfood.test", "anna@dogfood.test", "tom@dogfood.test")
ENV = {"SEED_UPNS": ",".join(UPNS), "GRAPH_TOKEN": "tok-SECRET-0123456789abcdef"}
ANCHOR = ["--anchor", "2026-10-23"]
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
WELL_KNOWN = ("inbox", "sentitems", "drafts", "deleteditems", "archive")


class FakeGraph:
    """A tiny in-memory Graph that answers the calls seed.py makes."""

    def __init__(self, upn: str = UPNS[0]) -> None:
        self.upn = upn
        self.calls: list[tuple[str, str]] = []
        self.next_id = 0
        self.folders: dict[str, dict[str, Any]] = {
            name: {"id": f"wk-{name}", "displayName": name, "parent": "root", "props": {}}
            for name in WELL_KNOWN
        }
        self.messages: dict[str, dict[str, Any]] = {}
        self.events: dict[str, dict[str, Any]] = {}
        self.drive: dict[str, dict[str, Any]] = {
            "root": {"id": "root", "name": "root", "parent": None, "folder": True}
        }
        self.fault = None  # callable(request) -> httpx.Response | None

    # ------------------------------------------------------------ helpers for tests
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def new_id(self, prefix: str) -> str:
        self.next_id += 1
        return f"{prefix}-{self.next_id}"

    def folder_id(self, ref: str) -> str:
        return self.folders[ref]["id"] if ref in self.folders else ref

    def folder_by_id(self, folder_id: str) -> tuple[str, dict[str, Any]]:
        for key, folder in self.folders.items():
            if folder["id"] == folder_id or key == folder_id:
                return key, folder
        raise KeyError(folder_id)

    def writes(self) -> list[tuple[str, str]]:
        return [c for c in self.calls if c[0] in WRITE_METHODS or c[1].endswith("/permanentDelete")]

    def state(self) -> dict[str, Any]:
        folder_name = {f["id"]: f["displayName"] for f in self.folders.values()}
        return {
            "folders": sorted(
                (f["displayName"], folder_name.get(self.folder_id(f["parent"]), f["parent"]))
                for f in self.folders.values()
            ),
            "messages": sorted(
                (m.get("subject") or "", folder_name[m["folder"]], tuple(m["categories"]))
                for m in self.messages.values()
            ),
            "events": sorted(e["subject"] for e in self.events.values()),
            "drive": sorted((i["name"], i.get("size", 0)) for i in self.drive.values()),
        }

    # ------------------------------------------------------------ the fake API
    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v1.0")
        self.calls.append((request.method, path))
        if self.fault:
            faulted = self.fault(request)
            if faulted is not None:
                return faulted
        params = dict(request.url.params)
        body = (
            json.loads(request.content)
            if request.headers.get("content-type") == "application/json"
            else None
        )
        m = request.method

        if path == "/me" and m == "GET":
            return httpx.Response(200, json={"id": "user-guid-1", "userPrincipalName": self.upn})
        if path == "/me/mailFolders" and m == "GET":
            return self.page(
                request,
                [
                    self.folder_json(f, params)
                    for f in self.folders.values()
                    if f["parent"] == "root"
                ],
            )
        if match := re.fullmatch(r"/me/mailFolders/([^/]+)/childFolders", path):
            parent = self.folder_id(match[1])
            if m == "GET":
                return self.page(
                    request,
                    [
                        self.folder_json(f, params)
                        for f in self.folders.values()
                        if self.folder_id(f["parent"]) == parent
                    ],
                )
            return self.create_folder(body, parent)
        if path == "/me/mailFolders" and m == "POST":
            return self.create_folder(body, "root")
        if match := re.fullmatch(r"/me/mailFolders/([^/]+)/permanentDelete", path):
            key, _ = self.folder_by_id(match[1])
            del self.folders[key]
            return httpx.Response(204)
        if match := re.fullmatch(r"/me/mailFolders/([^/]+)/messages", path):
            folder = self.folder_id(match[1])
            mid = self.new_id("msg")
            self.messages[mid] = {
                "id": mid,
                "folder": folder,
                "subject": body.get("subject"),
                "categories": body.get("categories", []),
                "props": self.props(body),
            }
            return httpx.Response(201, json={"id": mid})
        if match := re.fullmatch(r"/me/mailFolders/([^/]+)", path):
            _, folder = self.folder_by_id(match[1])
            total = sum(1 for x in self.messages.values() if x["folder"] == folder["id"])
            children = sum(
                1 for x in self.folders.values() if self.folder_id(x["parent"]) == folder["id"]
            )
            return httpx.Response(
                200,
                json={"id": folder["id"], "totalItemCount": total, "childFolderCount": children},
            )
        for collection, store in (("messages", self.messages), ("events", self.events)):
            if path == f"/me/{collection}" and m == "GET":
                items = list(store.values())
                if "$filter" in params:
                    items = [i for i in items if seed.TAG in i["categories"]]
                return self.page(request, [self.item_json(i, params) for i in items])
            if path == f"/me/{collection}" and m == "POST":
                eid = self.new_id("evt")
                store[eid] = {
                    "id": eid,
                    "subject": body["subject"],
                    "categories": body.get("categories", []),
                    "props": self.props(body),
                    "attendees": body.get("attendees"),
                }
                return httpx.Response(201, json={"id": eid})
            if match := re.fullmatch(rf"/me/{collection}/([^/]+)/permanentDelete", path):
                del store[match[1]]
                return httpx.Response(204)
        if match := re.fullmatch(r"/me/drive/root:/(.+)", path):
            item = next(
                (i for i in self.drive.values() if i["parent"] == "root" and i["name"] == match[1]),
                None,
            )
            if item is None:
                return httpx.Response(
                    404,
                    json={
                        "error": {
                            "code": "itemNotFound",
                            "message": "The resource could not be found.",
                        }
                    },
                )
            return httpx.Response(200, json=self.drive_json(item))
        if path == "/me/drive/root/children" and m == "POST":
            if any(
                i["parent"] == "root" and i["name"] == body["name"] for i in self.drive.values()
            ):
                return httpx.Response(
                    409, json={"error": {"code": "nameAlreadyExists", "message": "exists"}}
                )
            did = self.new_id("drv")
            self.drive[did] = {"id": did, "name": body["name"], "parent": "root", "folder": True}
            return httpx.Response(201, json=self.drive_json(self.drive[did]))
        if match := re.fullmatch(r"/me/drive/items/([^/:]+):/(.+):/content", path):
            did = self.new_id("drv")
            self.drive[did] = {
                "id": did,
                "name": match[2],
                "parent": match[1],
                "folder": False,
                "size": len(request.content),
            }
            return httpx.Response(201, json=self.drive_json(self.drive[did]))
        if match := re.fullmatch(r"/me/drive/items/([^/]+)/children", path):
            return self.page(
                request,
                [self.drive_json(i) for i in self.drive.values() if i["parent"] == match[1]],
            )
        if match := re.fullmatch(r"/me/drive/items/([^/]+)", path):
            if m == "DELETE":
                doomed = {match[1]} | {
                    i["id"] for i in self.drive.values() if i["parent"] == match[1]
                }
                for did in doomed:
                    del self.drive[did]
                return httpx.Response(204)
            return httpx.Response(200, json=self.drive_json(self.drive[match[1]]))
        return httpx.Response(
            400, json={"error": {"code": "fakeUnknownRoute", "message": f"{m} {path}"}}
        )

    def page(self, request: httpx.Request, items: list[dict[str, Any]]) -> httpx.Response:
        top = int(request.url.params.get("$top", "10"))
        skip = int(request.url.params.get("$skip", "0"))
        payload: dict[str, Any] = {"value": items[skip : skip + top]}
        if skip + top < len(items):
            payload["@odata.nextLink"] = str(request.url.copy_set_param("$skip", str(skip + top)))
        return httpx.Response(200, json=payload)

    @staticmethod
    def props(body: dict[str, Any]) -> dict[str, str]:
        return {p["id"]: p["value"] for p in body.get("singleValueExtendedProperties", [])}

    def create_folder(self, body: dict[str, Any], parent: str) -> httpx.Response:
        fid = self.new_id("fld")
        self.folders[fid] = {
            "id": fid,
            "displayName": body["displayName"],
            "parent": parent,
            "props": self.props(body),
        }
        return httpx.Response(201, json={"id": fid, "displayName": body["displayName"]})

    @staticmethod
    def expanded(item: dict[str, Any], params: dict[str, str]) -> dict[str, Any]:
        if "$expand" in params and seed.KEY_PROP in item["props"]:
            return {
                "singleValueExtendedProperties": [
                    {"id": seed.KEY_PROP, "value": item["props"][seed.KEY_PROP]}
                ]
            }
        return {}

    def folder_json(self, folder: dict[str, Any], params: dict[str, str]) -> dict[str, Any]:
        return {
            "id": folder["id"],
            "displayName": folder["displayName"],
            **self.expanded(folder, params),
        }

    def item_json(self, item: dict[str, Any], params: dict[str, str]) -> dict[str, Any]:
        return {
            "id": item["id"],
            "subject": item.get("subject"),
            "categories": item["categories"],
            **self.expanded(item, params),
        }

    def drive_json(self, item: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": item["id"],
            "name": item["name"],
            "size": item.get("size", 0),
        }
        if item["folder"]:
            result["folder"] = {
                "childCount": sum(1 for i in self.drive.values() if i["parent"] == item["id"])
            }
        return result


def run(
    argv: list[str], fake: FakeGraph | None = None, env: dict[str, str] | None = None, **kwargs: Any
) -> int:
    return seed.main(
        [*argv, *ANCHOR],
        transport=fake.transport() if fake else None,
        env=ENV if env is None else env,
        sleep=kwargs.pop("sleep", lambda _: None),
        **kwargs,
    )


def corpus_with(tmp_path: Path, edit) -> Path:
    target = tmp_path / "corpus"
    shutil.copytree(seed.CORPUS_DIR, target)
    mail = yaml.safe_load((target / "mail.yaml").read_text())
    edit(mail)
    (target / "mail.yaml").write_text(yaml.safe_dump(mail, sort_keys=False))
    return target


# ---------------------------------------------------------------- plan


def test_plan_is_deterministic_and_makes_no_call(capsys: pytest.CaptureFixture[str]) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"plan sent {request.method} {request.url}")

    outputs = []
    for _ in range(2):
        code = seed.main(
            ["plan", *ANCHOR],
            transport=httpx.MockTransport(refuse),
            env={"SEED_UPNS": ENV["SEED_UPNS"]},
        )
        outputs.append(capsys.readouterr().out)
        assert code == 0
    assert outputs[0] == outputs[1]
    assert "-- total for --as 1:" in outputs[0] and "-- total for --as 3:" in outputs[0]
    assert ENV["GRAPH_TOKEN"] not in outputs[0]


def test_plan_without_seed_upns_uses_placeholders(capsys: pytest.CaptureFixture[str]) -> None:
    assert seed.main(["plan", "--as", "1", *ANCHOR], env={}) == 0
    assert "mia@seed.invalid" in capsys.readouterr().out


# ---------------------------------------------------------------- apply


@pytest.mark.parametrize("index", [1, 2, 3])
def test_apply_twice_gives_the_same_state_and_the_second_run_creates_nothing(
    index: int, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeGraph(upn=UPNS[index - 1])
    assert run(["apply", "--as", str(index)], fake) == 0
    first_state, first_writes = fake.state(), len(fake.writes())
    assert first_writes > 0
    fake.calls.clear()
    assert run(["apply", "--as", str(index)], fake) == 0
    assert fake.writes() == []
    assert fake.state() == first_state
    assert "0 created" in capsys.readouterr().out


def test_apply_as_mia_creates_the_whole_corpus() -> None:
    fake = FakeGraph()
    assert run(["apply", "--as", "1"], fake) == 0
    folders = [
        f["displayName"] for f in fake.folders.values() if f["displayName"].startswith(seed.TAG)
    ]
    assert sorted(folders) == [
        "seed-v1 Archive",
        "seed-v1 Handled",
        "seed-v1 Projects",
        "seed-v1 Website Relaunch",
    ]
    assert len(fake.messages) == 43
    assert all(seed.TAG in m["categories"] for m in fake.messages.values())
    assert all(
        m["props"][seed.KEY_PROP].startswith("seed-v1:mail:") for m in fake.messages.values()
    )
    assert len(fake.events) == 8 and all(e["attendees"] is None for e in fake.events.values())
    files = sorted(
        i["name"] for i in fake.drive.values() if i["parent"] != "root" and i["id"] != "root"
    )
    assert files == [
        "seed-v1 Brochure Proof.pdf",
        "seed-v1 Budget Overview.xlsx",
        "seed-v1 Meeting Notes.txt",
        "seed-v1 Project Plan.docx",
    ]
    assert len(fake.calls) < seed.MAX_REQUESTS


def test_apply_resumes_after_a_partial_run() -> None:
    fake = FakeGraph()
    assert run(["apply", "--as", "1", "--phase", "folders"], fake) == 0
    assert fake.messages == {}
    assert run(["apply", "--as", "1"], fake) == 0
    full = FakeGraph()
    assert run(["apply", "--as", "1"], full) == 0
    assert fake.state() == full.state()


def test_mail_phase_alone_needs_the_folders() -> None:
    fake = FakeGraph()
    assert run(["apply", "--as", "1", "--phase", "mail"], fake) == seed.ConfigError.code
    assert fake.messages and len(fake.messages) < 43


def test_retry_after_is_honoured_on_429() -> None:
    fake = FakeGraph()
    waits: list[float] = []
    state = {"sent": False}

    def throttle_once(request: httpx.Request) -> httpx.Response | None:
        if request.method == "POST" and not state["sent"]:
            state["sent"] = True
            return httpx.Response(429, headers={"Retry-After": "7"})
        return None

    fake.fault = throttle_once
    assert run(["apply", "--as", "1", "--phase", "folders"], fake, sleep=waits.append) == 0
    assert waits == [7.0]
    assert len([f for f in fake.folders.values() if f["displayName"].startswith(seed.TAG)]) == 4


def test_a_write_is_not_retried_on_503() -> None:
    fake = FakeGraph()
    fake.fault = lambda r: httpx.Response(503) if r.method == "POST" else None
    assert run(["apply", "--as", "1", "--phase", "folders"], fake) == seed.GraphError.code
    assert len([c for c in fake.calls if c[0] == "POST"]) == 1


# ---------------------------------------------------------------- cleanup


def test_cleanup_removes_only_what_the_seed_can_prove_it_created(
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = FakeGraph()
    assert run(["apply", "--as", "1"], fake) == 0
    inbox = fake.folders["inbox"]["id"]
    fake.messages["user-1"] = {
        "id": "user-1",
        "folder": inbox,
        "subject": "A real mail",
        "categories": [],
        "props": {},
    }
    fake.messages["orphan-1"] = {
        "id": "orphan-1",
        "folder": inbox,
        "subject": "Tagged by hand",
        "categories": [seed.TAG],
        "props": {},
    }
    fake.messages["forged-1"] = {
        "id": "forged-1",
        "folder": inbox,
        "subject": "Unknown key",
        "categories": [seed.TAG],
        "props": {seed.KEY_PROP: "seed-v1:mail:zz99"},
    }
    fake.folders["personal"] = {
        "id": "fld-personal",
        "displayName": "Personal",
        "parent": "root",
        "props": {},
    }
    fake.folders["lookalike"] = {
        "id": "fld-look",
        "displayName": "seed-v1 Handled",
        "parent": "root",
        "props": {},
    }
    seeded = next(
        m for m in fake.messages.values() if m["props"].get(seed.KEY_PROP) == "seed-v1:mail:m30"
    )
    seeded["folder"] = fake.folders["deleteditems"]["id"]
    projects = next(f for f in fake.folders.values() if f["displayName"] == "seed-v1 Projects")
    projects["parent"] = "deleteditems"
    seed_folder = next(i for i in fake.drive.values() if i["name"] == "seed-v1 Seed Files")
    fake.drive["hand"] = {
        "id": "hand",
        "name": "notes-by-hand.txt",
        "parent": seed_folder["id"],
        "folder": False,
        "size": 3,
    }
    fake.drive["holiday"] = {
        "id": "holiday",
        "name": "Holiday.jpg",
        "parent": "root",
        "folder": False,
        "size": 9,
    }
    capsys.readouterr()

    assert run(["cleanup", "--as", "1"], fake) == 0
    out = capsys.readouterr().out
    assert sorted(m["subject"] for m in fake.messages.values()) == [
        "A real mail",
        "Tagged by hand",
        "Unknown key",
    ]
    assert sorted(f["displayName"] for f in fake.folders.values()) == sorted(
        [*WELL_KNOWN, "Personal", "seed-v1 Handled"]
    )
    assert fake.folders["lookalike"]["id"] == "fld-look"
    assert fake.events == {}
    assert sorted(i["name"] for i in fake.drive.values()) == [
        "Holiday.jpg",
        "notes-by-hand.txt",
        "root",
        "seed-v1 Seed Files",
    ]
    assert "orphan kept (messages): 'Tagged by hand'" in out
    assert "kept drive:folder" in out


def test_cleanup_dry_run_deletes_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeGraph()
    assert run(["apply", "--as", "1"], fake) == 0
    before = fake.state()
    fake.calls.clear()
    assert run(["cleanup", "--as", "1", "--dry-run"], fake) == 0
    assert fake.writes() == []
    assert fake.state() == before
    assert "would delete mail:m01" in capsys.readouterr().out


# ---------------------------------------------------------------- refusals


def external_recipient(mail: dict[str, Any]) -> None:
    mail["messages"][1]["to"] = ["someone@outside.example"]


def test_a_recipient_outside_seed_upns_is_refused_before_any_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    corpus = corpus_with(tmp_path, external_recipient)
    fake = FakeGraph()
    assert run(["apply", "--as", "1", "--corpus", str(corpus)], fake) == seed.Refused.code
    assert fake.calls == []
    assert "not in SEED_UPNS" in capsys.readouterr().err
    assert run(["plan", "--corpus", str(corpus)]) == seed.Refused.code


def test_an_address_hidden_in_body_text_is_refused(tmp_path: Path) -> None:
    def hide(mail: dict[str, Any]) -> None:
        mail["messages"][0]["body"]["content"] = "Write to boss%40outside.example please"

    fake = FakeGraph()
    assert (
        run(["apply", "--as", "1", "--corpus", str(corpus_with(tmp_path, hide))], fake)
        == seed.Refused.code
    )
    assert fake.calls == []


def test_running_as_a_user_outside_seed_upns_is_refused() -> None:
    fake = FakeGraph(upn="ceo@dogfood.test")
    assert run(["apply", "--as", "1"], fake) == seed.Refused.code
    assert fake.calls == [("GET", "/me")]


def test_running_as_the_wrong_persona_is_refused() -> None:
    fake = FakeGraph(upn=UPNS[1])
    assert run(["cleanup", "--as", "1"], fake) == seed.Refused.code
    assert fake.calls == [("GET", "/me")]


def test_the_guard_refuses_other_users_and_other_hosts() -> None:
    fake = FakeGraph()
    graph = seed.Graph("t", transport=fake.transport())
    with pytest.raises(seed.Refused):
        graph.request("GET", "/users/anna@dogfood.test/messages")
    with pytest.raises(seed.Refused):
        graph.request("GET", "https://evil.example/v1.0/me/messages")
    with pytest.raises(seed.Refused):
        graph.request("GET", "/meeting")
    assert fake.calls == []


def test_the_request_cap_stops_a_runaway() -> None:
    fake = FakeGraph()

    def endless(request: httpx.Request) -> httpx.Response | None:
        if request.url.path.endswith("/me/messages"):
            return httpx.Response(
                200,
                json={
                    "value": [],
                    "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?$skip=1",
                },
            )
        return None

    fake.fault = endless
    assert run(["apply", "--as", "1", "--phase", "mail"], fake) == seed.CapReached.code
    assert len(fake.calls) == seed.MAX_REQUESTS
    assert (
        run(["apply", "--as", "1", "--max-requests", "301"], FakeGraph()) == seed.ConfigError.code
    )


def test_the_token_never_appears_in_output_logs_or_errors(
    capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    token = ENV["GRAPH_TOKEN"]
    caplog.set_level(logging.DEBUG)
    fake = FakeGraph()

    def echo(request: httpx.Request) -> httpx.Response | None:
        if request.method == "POST":
            return httpx.Response(
                500,
                json={
                    "error": {"code": "boom", "message": f"echo {request.headers['Authorization']}"}
                },
            )
        return None

    fake.fault = echo
    assert run(["apply", "--as", "1"], fake) == seed.GraphError.code
    captured = capsys.readouterr()
    text = captured.out + captured.err + caplog.text
    assert "boom" in captured.err
    assert token not in text
    assert token not in repr(seed.Graph(token))
    assert run(["apply", "--as", "1"], FakeGraph(upn="x@dogfood.test")) == seed.Refused.code
    assert token not in capsys.readouterr().err


def test_apply_without_a_token_is_refused() -> None:
    fake = FakeGraph()
    assert (
        run(["apply", "--as", "1"], fake, env={"SEED_UPNS": ENV["SEED_UPNS"]})
        == seed.ConfigError.code
    )
    assert fake.calls == []


def test_safety_checks_hold_under_python_dash_o(tmp_path: Path) -> None:
    corpus = corpus_with(tmp_path, external_recipient)
    driver = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(HERE)!r})
        import seed, test_seed
        env = {ENV!r}
        wrong = test_seed.FakeGraph(upn="ceo@dogfood.test")
        a = seed.main(["apply", "--as", "1"], transport=wrong.transport(), env=env)
        outside = test_seed.FakeGraph()
        b = seed.main(["apply", "--as", "1", "--corpus", {str(corpus)!r}], transport=outside.transport(), env=env)
        runaway = test_seed.FakeGraph()
        c = seed.main(["apply", "--as", "1", "--max-requests", "5"], transport=runaway.transport(), env=env)
        print(__debug__, a, len(wrong.calls), b, len(outside.calls), c, len(runaway.calls))
        """
    )
    result = subprocess.run(
        [sys.executable, "-O", "-c", driver], capture_output=True, text=True, check=True
    )
    assert result.stdout.splitlines()[-1].split() == ["False", "3", "1", "3", "0", "5", "5"]
    assert ENV["GRAPH_TOKEN"] not in result.stdout + result.stderr


# ---------------------------------------------------------------- content


def ctx(mode: str = "extprops") -> seed.Context:
    import datetime as dt

    return seed.Context(seed.load_corpus(seed.CORPUS_DIR), UPNS, dt.date(2026, 10, 23), mode)


def bodies(context: seed.Context) -> dict[str, dict[str, Any]]:
    return {
        s.key: s.body for s in seed.build_steps(context, 1, set(seed.PHASES)) if s.kind == "create"
    }


def test_mail_bodies_carry_the_planned_quirks() -> None:
    mail = bodies(ctx())
    props = {
        k: {p["id"]: p["value"] for p in b["singleValueExtendedProperties"]}
        for k, b in mail.items()
        if k.startswith("mail:")
    }
    assert props["mail:m01"][seed.FLAGS_PROP] == "1"
    assert props["mail:m10"][seed.FLAGS_PROP] == "0"
    assert props["mail:m12"][seed.DELIVERY_PROP] == "2026-10-22T13:50:00Z"
    assert seed.FLAGS_PROP not in props["mail:m43"]
    assert "subject" not in mail["mail:m28"]
    assert mail["mail:m29"]["body"] == {"contentType": "text", "content": ""}
    assert mail["mail:m27"]["body"]["contentType"] == "html"
    index_1 = base64.b64decode(props["mail:m01"][seed.CONV_INDEX_PROP])
    index_12 = base64.b64decode(props["mail:m12"][seed.CONV_INDEX_PROP])
    assert len(index_1) == 22 and len(index_12) == 22 + 11 * 5 and index_12[:22] == index_1
    draft_mode = bodies(ctx("draft"))
    assert all(
        seed.FLAGS_PROP not in {p["id"] for p in b["singleValueExtendedProperties"]}
        for k, b in draft_mode.items()
        if k.startswith("mail:")
    )


def test_events_use_windows_zones_an_all_day_day_and_a_weekly_series() -> None:
    events = {k: b for k, b in bodies(ctx()).items() if k.startswith("event:")}
    assert events["event:e02"]["isAllDay"] and events["event:e02"]["start"]["dateTime"].endswith(
        "T00:00:00"
    )
    assert {e["start"]["timeZone"] for e in events.values()} >= {
        "W. Europe Standard Time",
        "Eastern Standard Time",
        "India Standard Time",
    }
    series = events["event:e01"]
    assert series["recurrence"]["pattern"]["daysOfWeek"] == ["monday"]
    assert series["start"]["dateTime"] == "2026-10-26T09:00:00"
    assert all("attendees" not in e for e in events.values())


def test_generated_files_are_valid_stable_and_carry_persona_properties() -> None:
    first, second = bodies(ctx()), bodies(ctx())
    docx = first["file:seed-v1 Project Plan.docx"]
    assert docx == second["file:seed-v1 Project Plan.docx"]
    core = zipfile.ZipFile(io.BytesIO(docx)).read("docProps/core.xml").decode()
    assert (
        "<dc:creator>Mia Keller</dc:creator>" in core
        and "<cp:lastModifiedBy>Anna Meier</cp:lastModifiedBy>" in core
    )
    app = (
        zipfile.ZipFile(io.BytesIO(first["file:seed-v1 Budget Overview.xlsx"]))
        .read("docProps/app.xml")
        .decode()
    )
    assert "<Company>Lakeside Demo AG</Company>" in app
    pdf = first["file:seed-v1 Brochure Proof.pdf"]
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
    startxref = int(pdf.rsplit(b"startxref\n", 1)[1].split(b"\n")[0])
    assert pdf[startxref:].startswith(b"xref")
    assert b"/Author (Tom Berger)" in pdf


def test_corpus_manifest_lists_every_string_and_binary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "corpus.generated.json"
    assert seed.main(["corpus", "--out", str(out), *ANCHOR], env=ENV) == 0
    manifest = json.loads(out.read_text())
    counts = json.loads(capsys.readouterr().err)
    assert counts == {
        "mails": 47,
        "mails_unread_inbox_mia": 17,
        "threads": 4,
        "longest_thread": 12,
        "events": 9,
        "files": 5,
        "attachments": 3,
        "folders": 4,
    }
    assert "Website relaunch: launch checklist" in manifest["strings"]
    assert "seed-v1 Website Relaunch" in manifest["strings"]
    assert not any("@" in s for s in manifest["strings"])
    assert not any(re.match(r"\d{4}-\d{2}-\d{2}", s) for s in manifest["strings"])
    other_day = tmp_path / "other.json"
    assert seed.main(["corpus", "--out", str(other_day), "--anchor", "2027-03-01"], env=ENV) == 0
    assert other_day.read_text() == out.read_text()
    assert len(manifest["binaries"]) == 8
    created = {b["name"] for b in manifest["binaries"]}
    assert {"seed-v1 Project Plan.docx", "q3-numbers.csv"} <= created
