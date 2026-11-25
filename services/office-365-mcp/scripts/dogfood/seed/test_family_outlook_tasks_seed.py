import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, override

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import seed
from families import outlook_tasks
from model import Context, Step
from test_seed import UPNS, FakeGraph, run

CTX = Context(seed.load_corpus(seed.CORPUS_DIR), UPNS, dt.date(2026, 10, 23), "extprops")
PHASES = {"todo"}
CORPUS = outlook_tasks._corpus()  # pyright: ignore[reportPrivateUsage]


def plan(phases: set[str] = PHASES) -> list[Step]:
    return outlook_tasks.steps(CTX, "mia", phases)


def creates(phases: set[str] = PHASES) -> dict[str, Step]:
    return {str(step.key): step for step in plan(phases) if step.kind == "create"}


class TodoFake(FakeGraph):
    """Answers the To Do calls of the seed: a store of rows for each collection path."""

    def __init__(self, *, stores_uploads: bool = True, upload_owner: str = "/me") -> None:
        super().__init__()
        self.stores_uploads = stores_uploads
        self.upload_owner = upload_owner
        self.sessions: dict[str, dict[str, Any]] = {}
        self.rows: dict[str, list[dict[str, Any]]] = {
            "/me/todo/lists": [
                {"id": "default", "displayName": "Tasks", "wellknownListName": "defaultList"},
                {"id": "flagged", "displayName": "Flagged", "wellknownListName": "flaggedEmails"},
                {"id": "mine", "displayName": "Holiday", "wellknownListName": "none"},
            ],
            "/me/todo/lists/default/tasks": [{"id": "own-task", "title": "Buy milk"}],
            "/me/todo/lists/mine/tasks": [],
        }

    def names(self, path: str, field: str) -> list[str]:
        return sorted(str(row[field]) for row in self.rows.get(path, []))

    @override
    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v1.0")
        if not path.startswith("/me/todo/"):
            return super().handle(request)
        self.calls.append((request.method, path))
        if request.method == "DELETE":
            parent, _, gone = path.rpartition("/")
            self.rows[parent] = [row for row in self.rows[parent] if row["id"] != gone]
            for key in [key for key in self.rows if key.startswith(f"{path}/")]:
                del self.rows[key]
            return httpx.Response(204)
        if request.method == "GET":
            return self.page(request, self.rows.setdefault(path, []))
        if request.method == "PUT":
            return self.chunk(request, path)
        body = json.loads(request.content)
        if path.endswith("/attachments/createUploadSession"):
            return self.session(path.removesuffix("/createUploadSession"), body)
        made = {"id": self.new_id("todo"), **body}
        self.rows.setdefault(path, []).append(made)
        return httpx.Response(201, json=made)

    def session(self, attachments: str, body: dict[str, Any]) -> httpx.Response:
        task = attachments.removesuffix("/attachments")
        owned = task.replace("/me/", f"{self.upload_owner}/", 1)
        url = f"https://graph.microsoft.com/v1.0{owned}/attachmentSessions/{self.new_id('s')}"
        self.sessions[f"{task}/attachmentSessions/{url.rpartition('/')[2]}/content"] = {
            "attachments": attachments,
            **body["attachmentInfo"],
        }
        return httpx.Response(201, json={"uploadUrl": url})

    def chunk(self, request: httpx.Request, path: str) -> httpx.Response:
        assert request.headers["authorization"].startswith("Bearer ")
        opened = self.sessions[path]
        assert len(request.content) == opened["size"]
        if self.stores_uploads:
            self.rows.setdefault(opened["attachments"], []).append(
                {"id": self.new_id("file"), "name": opened["name"], "size": opened["size"]}
            )
        return httpx.Response(500, json={"error": {"code": "generalException"}})


def test_only_mia_gets_to_do_data_and_only_in_its_phase() -> None:
    assert outlook_tasks.steps(CTX, "anna", PHASES) == []
    assert outlook_tasks.steps(CTX, "tom", PHASES) == []
    assert outlook_tasks.steps(CTX, "mia", {"mail"}) == []
    assert "todo" in seed.PHASES
    assert "todo" not in seed.OPT_IN


def test_a_parent_is_created_before_its_children_and_every_name_is_tagged() -> None:
    made = {outlook_tasks.DEFAULT_KEY}
    for step in plan():
        for ref in re.findall(r"\{([^}]+)\}", step.path):
            assert ref in made, f"{step.path} comes before {ref}"
        if step.kind == "create":
            made.add(str(step.key))
    for step in creates().values():
        name = step.body.get("title") or step.body.get("displayName") or step.body.get("name")
        assert str(name).startswith("seed-v1 ")
        assert step.method == "POST"


def test_the_seed_list_holds_a_due_a_completed_a_stepped_a_linked_and_two_filed_tasks() -> None:
    tasks = {
        key: step.body
        for key, step in creates().items()
        if step.path == "/me/todo/lists/{todo:seed-v1 Launch plan}/tasks"
    }
    assert len(tasks) == 6
    assert all(body["categories"] == ["seed-v1"] for body in tasks.values())
    assert [key for key, body in tasks.items() if "dueDateTime" in body] == [
        "todo:seed-v1 Launch plan>seed-v1 Book the launch room"
    ]
    assert tasks["todo:seed-v1 Launch plan>seed-v1 Book the launch room"]["dueDateTime"] == {
        "dateTime": "2026-10-30T00:00:00",
        "timeZone": "UTC",
    }
    assert [key for key, body in tasks.items() if body.get("status") == "completed"] == [
        "todo:seed-v1 Launch plan>seed-v1 Send the press note"
    ]
    links = tasks["todo:seed-v1 Launch plan>seed-v1 Read the launch site"]["linkedResources"]
    assert [link["displayName"] for link in links] == ["seed-v1 Launch site"]
    stepped = [s for s in creates().values() if s.path.endswith("/checklistItems")]
    assert [(s.body["displayName"], s.body["isChecked"]) for s in stepped] == [
        ("seed-v1 Check the logo", False),
        ("seed-v1 Check the dates", True),
    ]
    assert not [s for s in plan() if "/attachments" in s.path and s.kind != "lookup"]
    with_files = [
        s for s in plan({*PHASES, outlook_tasks.FILES_PHASE}) if s.kind == "upload-with-token"
    ]
    assert [s.path.rsplit("/", 2)[-2:] for s in with_files] == [
        ["attachments", "createUploadSession"],
        ["attachments", "createUploadSession"],
    ]
    assert [s.body["attachmentInfo"]["name"] for s in with_files] == [
        "seed-v1 Launch brief.docx",
        "seed-v1 Old brief.docx",
    ]
    assert all(
        s.payload == outlook_tasks.ASSETS[s.body["attachmentInfo"]["name"]]
        and s.body["attachmentInfo"]["size"] == len(s.payload)
        for s in with_files
    )


def test_the_built_in_list_gets_a_reminded_task_and_a_weekly_task_on_its_due_day() -> None:
    tasks = {
        key: step.body
        for key, step in creates().items()
        if step.path == "/me/todo/lists/{todo:defaultList}/tasks"
    }
    assert set(tasks) == {
        "todo:defaultList>seed-v1 Renew the parking permit",
        "todo:defaultList>seed-v1 Water the office plants",
    }
    permit = tasks["todo:defaultList>seed-v1 Renew the parking permit"]
    assert permit["isReminderOn"] is True
    assert permit["reminderDateTime"]["dateTime"] == "2026-11-05T09:00:00"
    plants = tasks["todo:defaultList>seed-v1 Water the office plants"]
    assert plants["dueDateTime"]["dateTime"] == "2026-10-26T00:00:00"
    assert plants["recurrence"]["pattern"]["daysOfWeek"] == ["monday"]
    assert plants["recurrence"]["range"] == {"type": "noEnd", "startDate": "2026-10-26"}


def test_no_step_names_an_address() -> None:
    seed.check_recipients(plan(), UPNS)


def test_the_manifest_holds_the_texts_and_the_hash_of_each_file() -> None:
    manifest = seed.corpus_manifest(CTX)
    strings = set(manifest["strings"])
    assert {"seed-v1 Launch plan", "seed-v1 Check the logo", "The slides need the new logo."} <= (
        strings
    )
    for attachment in CORPUS["lists"][0]["tasks"][4]["attachments"]:
        raw = outlook_tasks.attachment_bytes(attachment)
        found = next(
            b for b in manifest["binaries"] if b["name"] == f"seed-v1 {attachment['name']}"
        )
        assert found["sha256"] == hashlib.sha256(raw).hexdigest()


def test_apply_creates_the_corpus_and_a_second_apply_creates_nothing() -> None:
    fake = TodoFake()
    assert run(["apply", "--as", "1", "--phases", "todo"], fake) == 0
    lists = fake.names("/me/todo/lists", "displayName")
    assert lists == ["Flagged", "Holiday", "Tasks", "seed-v1 Launch plan"]
    seeded = next(
        r for r in fake.rows["/me/todo/lists"] if r["displayName"] == "seed-v1 Launch plan"
    )
    assert len(fake.rows[f"/me/todo/lists/{seeded['id']}/tasks"]) == 6
    assert fake.names("/me/todo/lists/default/tasks", "title") == [
        "Buy milk",
        "seed-v1 Renew the parking permit",
        "seed-v1 Water the office plants",
    ]
    writes = len(fake.writes())
    assert run(["apply", "--as", "1", "--phases", "todo"], fake) == 0
    assert len(fake.writes()) == writes


def test_cleanup_deletes_the_seed_list_and_the_seed_tasks_and_keeps_the_rest() -> None:
    fake = TodoFake()
    assert run(["apply", "--as", "1", "--phases", "todo"], fake) == 0
    look_alike = {"id": "look-alike", "title": "seed-v1 Renew the parking permit"}
    fake.rows["/me/todo/lists/default/tasks"].append(look_alike)
    assert run(["cleanup", "--as", "1", "--phases", "todo"], fake) == 0
    assert fake.names("/me/todo/lists", "displayName") == ["Flagged", "Holiday", "Tasks"]
    assert fake.names("/me/todo/lists/default/tasks", "title") == [
        "Buy milk",
        "seed-v1 Renew the parking permit",
    ]


def test_the_sweep_names_case_lists_and_case_tasks_only() -> None:
    fake = TodoFake()
    assert run(["apply", "--as", "1", "--phases", "todo"], fake) == 0
    fake.rows["/me/todo/lists"].append({"id": "case-list", "displayName": "seed-v1 case-x"})
    fake.rows["/me/todo/lists/default/tasks"].append({"id": "case-task", "title": "seed-v1 case-y"})
    fake.rows["/me/todo/lists/mine/tasks"].append({"id": "kept", "title": "seed-v1 case-z"})
    graph = seed.Graph("token", transport=fake.transport())
    assert list(outlook_tasks.sweep(graph, "mia")) == [
        ("DELETE", "/me/todo/lists/default/tasks/case-task"),
        ("DELETE", "/me/todo/lists/case-list"),
    ]
    assert list(outlook_tasks.sweep(graph, "anna")) == []


def test_a_file_upload_that_graph_answers_with_500_counts_when_the_file_is_listed() -> None:
    fake = TodoFake()
    phases = ["apply", "--as", "1", "--phases", "todo,todo-files"]
    assert run(phases, fake) == 0
    filed = sorted(
        str(row["name"])
        for key, rows in fake.rows.items()
        if key.endswith("/attachments")
        for row in rows
    )
    assert filed == ["seed-v1 Launch brief.docx", "seed-v1 Old brief.docx"]
    before = len(fake.calls)
    assert run(phases, fake) == 0
    assert not [call for call in fake.calls[before:] if call[0] in ("POST", "PUT")]


def test_a_file_upload_that_stores_nothing_stops_the_run() -> None:
    fake = TodoFake(stores_uploads=False)
    assert run(["apply", "--as", "1", "--phases", "todo,todo-files"], fake) != 0


def test_a_file_upload_to_another_user_is_refused() -> None:
    fake = TodoFake(upload_owner="/users/someone-else")
    assert run(["apply", "--as", "1", "--phases", "todo,todo-files"], fake) != 0
    assert not [call for call in fake.calls if call[0] == "PUT"]


def test_the_file_phase_alone_adds_only_files_to_the_tasks_that_todo_made() -> None:
    fake = TodoFake()
    assert run(["apply", "--as", "1", "--phases", "todo"], fake) == 0
    before = len(fake.calls)
    assert run(["apply", "--as", "1", "--phases", "todo-files"], fake) == 0
    written = [call for call in fake.calls[before:] if call[0] in ("POST", "PUT")]
    assert {path.rsplit("/", 1)[-1] for _, path in written} == {"createUploadSession", "content"}


def test_the_file_phase_alone_makes_the_missing_tasks_first() -> None:
    fake = TodoFake()
    assert run(["apply", "--as", "1", "--phases", "todo-files"], fake) == 0
    filed = sorted(
        str(row["name"])
        for key, rows in fake.rows.items()
        if key.endswith("/attachments")
        for row in rows
    )
    assert filed == ["seed-v1 Launch brief.docx", "seed-v1 Old brief.docx"]


def test_a_seed_task_moved_to_another_list_is_made_again_in_its_own_list() -> None:
    fake = TodoFake()
    assert run(["apply", "--as", "1", "--phases", "todo"], fake) == 0
    launch = next(
        key
        for key in fake.rows
        if key.endswith("/tasks")
        and "default" not in key
        and key.count("/") == 5
        and any(row.get("title") == "seed-v1 Book the launch room" for row in fake.rows[key])
    )
    moved = {"id": "moved", "title": "seed-v1 Renew the parking permit", "categories": ["seed-v1"]}
    fake.rows[launch].append(moved)
    fake.rows["/me/todo/lists/default/tasks"] = [
        row
        for row in fake.rows["/me/todo/lists/default/tasks"]
        if row.get("title") != "seed-v1 Renew the parking permit"
    ]
    assert run(["apply", "--as", "1", "--phases", "todo"], fake) == 0
    assert "seed-v1 Renew the parking permit" in fake.names("/me/todo/lists/default/tasks", "title")
