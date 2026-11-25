import datetime as dt
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import docgen
import yaml
from model import ConfigError, Context, Step

if TYPE_CHECKING:
    from seed import Graph

TAG = "seed-v1"
CASE = f"{TAG} case-"
OWNER = "mia"
PHASE = "todo"
FILES_PHASE = "todo-files"
PHASES: tuple[str, ...] = (PHASE, FILES_PHASE)
OPT_IN: tuple[str, ...] = (FILES_PHASE,)
LISTS = "/me/todo/lists"
DEFAULT_LIST = "defaultList"
DEFAULT_KEY = f"{PHASE}:{DEFAULT_LIST}"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
CORPUS = Path(__file__).resolve().parents[1] / "corpus" / "outlook-tasks.yaml"
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

type Spec = Mapping[str, Any]


def _corpus() -> Spec:
    return cast("Spec", yaml.safe_load(CORPUS.read_text(encoding="utf-8")))


def _named(name: str) -> str:
    return f"{TAG} {name}"


def _key(name: str) -> str:
    return f"{PHASE}:{_named(name)}"


def _ref(key: str) -> str:
    return "{" + key + "}"


def _lookup(
    path: str, fields: str | None = None, lookup: str = "named", key: str | None = None
) -> Step:
    query = () if fields is None else (("$select", fields),)
    return Step(PHASE, "lookup", "GET", path, query, key=key, lookup=lookup)


def _moment(day: dt.date, time: str) -> dict[str, str]:
    return {"dateTime": f"{day.isoformat()}T{time}", "timeZone": "UTC"}


def task_body(task: Spec, anchor: dt.date) -> dict[str, Any]:
    body: dict[str, Any] = {
        "title": _named(task["title"]),
        "categories": [TAG],
        "body": {"content": task["notes"], "contentType": "text"},
    }
    if "priority" in task:
        body["importance"] = task["priority"]
    if "status" in task:
        body["status"] = task["status"]
    if "due_days" in task:
        due = anchor + dt.timedelta(days=task["due_days"])
        body["dueDateTime"] = _moment(due, "00:00:00")
        if task.get("repeat") == "weekly":
            body["recurrence"] = {
                "pattern": {
                    "type": "weekly",
                    "interval": 1,
                    "daysOfWeek": [WEEKDAYS[due.weekday()]],
                },
                "range": {"type": "noEnd", "startDate": due.isoformat()},
            }
    if "reminder_days" in task:
        body["isReminderOn"] = True
        body["reminderDateTime"] = _moment(
            anchor + dt.timedelta(days=task["reminder_days"]), "09:00:00"
        )
    if "links" in task:
        body["linkedResources"] = [
            {
                "displayName": _named(link["title"]),
                "webUrl": link["url"],
                "applicationName": link["application"],
            }
            for link in task["links"]
        ]
    return body


def attachment_bytes(attachment: Spec) -> bytes:
    return docgen.docx(attachment["paragraphs"], {"title": _named(attachment["name"])})


ASSETS: Mapping[str, bytes] = {
    _named(attachment["name"]): attachment_bytes(attachment)
    for one in _corpus()["lists"]
    for task in one["tasks"]
    for attachment in task.get("attachments", [])
}


def _upload_session(attachment: Spec) -> dict[str, dict[str, str | int]]:
    return {
        "attachmentInfo": {
            "attachmentType": "file",
            "name": _named(attachment["name"]),
            "contentType": DOCX,
            "size": len(attachment_bytes(attachment)),
        }
    }


def _task_steps(tasks_path: str, task: Spec, anchor: dt.date, *, files: bool) -> list[Step]:
    key = _key(task["title"])
    path = f"{tasks_path}/{_ref(key)}"
    found = [Step(PHASE, "create", "POST", tasks_path, body=task_body(task, anchor), key=key)]
    if task.get("steps"):
        found.append(_lookup(f"{path}/checklistItems"))
        found += [
            Step(
                PHASE,
                "create",
                "POST",
                f"{path}/checklistItems",
                body={"displayName": _named(one["text"]), "isChecked": bool(one.get("checked"))},
                key=_key(one["text"]),
            )
            for one in task["steps"]
        ]
    if files and task.get("attachments"):
        found.append(_lookup(f"{path}/attachments", "id,name", "attachments", key))
        found += [
            Step(
                FILES_PHASE,
                "upload-with-token",
                "POST",
                f"{path}/attachments/createUploadSession",
                body=_upload_session(one),
                key=f"attachment:{key}:{_named(one['name'])}",
                payload=attachment_bytes(one),
            )
            for one in task["attachments"]
        ]
    return found


def steps(ctx: Context, owner: str, phases: set[str]) -> list[Step]:
    if owner != OWNER or not phases & {PHASE, FILES_PHASE}:
        return []
    corpus = _corpus()
    found = [
        _lookup(LISTS),
        _lookup(LISTS, None, "default-list", DEFAULT_KEY),
    ]
    for one in corpus["lists"]:
        key = _key(one["name"])
        tasks = f"{LISTS}/{_ref(key)}/tasks"
        found += [
            Step(
                PHASE, "create", "POST", LISTS, body={"displayName": _named(one["name"])}, key=key
            ),
            _lookup(tasks),
        ]
        for task in one["tasks"]:
            found += _task_steps(tasks, task, ctx.anchor, files=FILES_PHASE in phases)
    tasks = f"{LISTS}/{_ref(DEFAULT_KEY)}/tasks"
    found.append(_lookup(tasks))
    for task in corpus["default_tasks"]:
        found += _task_steps(tasks, task, ctx.anchor, files=FILES_PHASE in phases)
    made = [step.key for step in found if step.kind != "lookup"]
    if len(made) != len(set(made)):
        raise ConfigError("two To Do items of the corpus have the same name; rename one")
    return found


def _tasks(graph: Graph, list_id: str) -> Iterator[dict[str, Any]]:
    return graph.get_all(f"{LISTS}/{list_id}/tasks", {})


def sweep(graph: Graph, owner: str) -> Iterator[tuple[str, str]]:
    if owner != OWNER:
        return
    seeded = {_named(one["name"]) for one in _corpus()["lists"]}
    for found in graph.get_all(LISTS, {}):
        name = str(found.get("displayName") or "")
        if CASE in name:
            yield "DELETE", f"{LISTS}/{found['id']}"
        elif name in seeded or found.get("wellknownListName") == DEFAULT_LIST:
            for task in _tasks(graph, str(found["id"])):
                if CASE in str(task.get("title") or ""):
                    yield "DELETE", f"{LISTS}/{found['id']}/tasks/{task['id']}"


def cleanup(
    graph: Graph, ctx: Context, owner: str, phases: set[str]
) -> Iterator[tuple[str, str, None]]:
    if owner != OWNER or not phases & {PHASE, FILES_PHASE}:
        return
    if PHASE not in phases:
        yield from _file_cleanup(graph)
        return
    corpus = _corpus()
    seeded = {_named(one["name"]) for one in corpus["lists"]}
    titles = {_named(task["title"]) for task in corpus["default_tasks"]}
    for found in graph.get_all(LISTS, {}):
        if found.get("displayName") in seeded:
            yield "DELETE", f"{LISTS}/{found['id']}", None
        elif found.get("wellknownListName") == DEFAULT_LIST:
            for task in _tasks(graph, str(found["id"])):
                if task.get("title") in titles and TAG in (task.get("categories") or []):
                    yield "DELETE", f"{LISTS}/{found['id']}/tasks/{task['id']}", None


def _file_cleanup(graph: Graph) -> Iterator[tuple[str, str, None]]:
    corpus = _corpus()
    seeded = {_named(one["name"]) for one in corpus["lists"]}
    files = {
        _named(task["title"]): {_named(one["name"]) for one in task.get("attachments", [])}
        for one in corpus["lists"]
        for task in one["tasks"]
    }
    for found in graph.get_all(LISTS, {}):
        if found.get("displayName") not in seeded:
            continue
        for task in _tasks(graph, str(found["id"])):
            names = files.get(str(task.get("title") or ""), set())
            if not names:
                continue
            path = f"{LISTS}/{found['id']}/tasks/{task['id']}/attachments"
            for attachment in graph.get_all(path, {"$select": "id,name"}):
                if attachment.get("name") in names:
                    yield "DELETE", f"{path}/{attachment['id']}", None
