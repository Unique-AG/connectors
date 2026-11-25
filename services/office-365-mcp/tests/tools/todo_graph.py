from collections.abc import Mapping, Sequence
from typing import Literal, cast

import httpx
import respx
from respx.models import Call

from office_365_mcp.shared.handles import TaskHandle, TaskListHandle, TaskPartHandle

type Entity = Literal["list", "task", "step", "link", "file"]

LIST_ID = "AAMkSYNTHETIC-list-0001"
TASK_ID = "AAMkSYNTHETIC-task-0001"
ETAG = 'W/"SYNTHETIC-etag-1"'

TASK_LIST_URI = TaskListHandle(LIST_ID).uri
TASK_URI = TaskHandle(LIST_ID, TASK_ID).uri
STEP_URI = TaskPartHandle("steps", LIST_ID, TASK_ID, "SYNTHETIC-step-0001").uri
LINK_URI = TaskPartHandle("links", LIST_ID, TASK_ID, "SYNTHETIC-link-0001").uri
FILE_URI = TaskPartHandle("attachments", LIST_ID, TASK_ID, "SYNTHETIC-file-0001").uri

OTHER_TASK_LIST_URI = TaskListHandle("AAMkSYNTHETIC-list-0002").uri
OTHER_TASK_URI = TaskHandle(LIST_ID, "AAMkSYNTHETIC-task-0002").uri
OTHER_STEP_URI = TaskPartHandle("steps", LIST_ID, TASK_ID, "SYNTHETIC-step-0002").uri
OTHER_LINK_URI = TaskPartHandle("links", LIST_ID, TASK_ID, "SYNTHETIC-link-0002").uri
OTHER_FILE_URI = TaskPartHandle("attachments", LIST_ID, TASK_ID, "SYNTHETIC-file-0002").uri

_ONE_LIST = r"/me/todo/lists/[^/]+$"
_ONE_TASK = r"/me/todo/lists/[^/]+/tasks/[^/]+$"
_TASK_PART = r"/me/todo/lists/[^/]+/tasks/[^/]+/{}/[^/]+$"

PATHS: Mapping[Entity, str] = {
    "list": _ONE_LIST,
    "task": _ONE_TASK,
    "step": _TASK_PART.format("checklistItems"),
    "link": _TASK_PART.format("linkedResources"),
    "file": _TASK_PART.format("attachments"),
}

SEEN: Mapping[Entity, Mapping[str, object]] = {
    "list": {"id": LIST_ID, "displayName": "Team launch", "isShared": True},
    "task": {
        "id": TASK_ID,
        "title": "Book the venue",
        "dueDateTime": {"dateTime": "2026-11-29T23:00:00.0000000", "timeZone": "UTC"},
        "@odata.etag": ETAG,
    },
    "step": {"id": "SYNTHETIC-step-0001", "displayName": "Call the hotel", "isChecked": False},
    "link": {
        "id": "SYNTHETIC-link-0001",
        "displayName": "Q3 report",
        "webUrl": "https://example.invalid/q3",
        "applicationName": "Outlook",
    },
    "file": {"id": "SYNTHETIC-file-0001", "name": "Agenda.pdf"},
}

WRITTEN: Mapping[str, object] = {
    "id": "SYNTHETIC-written-0001",
    "title": "Book the venue",
    "displayName": "Team launch",
}


def todo_graph(
    graph: respx.MockRouter,
    *,
    changed: Mapping[Entity, Mapping[str, object]] | None = None,
    missing: Entity | None = None,
) -> None:
    for entity, path in PATHS.items():
        seen = {**SEEN[entity], **(changed or {}).get(entity, {})}
        answer = httpx.Response(404) if entity == missing else httpx.Response(200, json=seen)
        _ = graph.route(method="GET", path__regex=path).mock(return_value=answer)


def written(graph: respx.MockRouter, *, status: int = 200) -> None:
    for method in ("PATCH", "POST"):
        _ = graph.route(method=method, path__regex=r"/me/todo/").mock(
            return_value=httpx.Response(status, json=WRITTEN if status < 400 else {})
        )
    _ = graph.route(method="DELETE", path__regex=r"/me/todo/").mock(
        return_value=httpx.Response(204 if status < 400 else status)
    )


def writes(graph: respx.MockRouter) -> list[Call]:
    return [call for call in cast("Sequence[Call]", graph.calls) if call.request.method != "GET"]


def reads(graph: respx.MockRouter) -> list[str]:
    return [
        call.request.url.path
        for call in cast("Sequence[Call]", graph.calls)
        if call.request.method == "GET"
    ]
