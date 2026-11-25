from dataclasses import dataclass
from typing import ClassVar, Literal

from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from kiota_abstractions.headers_collection import HeadersCollection
from kiota_abstractions.serialization import Parsable
from mcp.types import InputRequiredResult
from msgraph.generated.models.checklist_item import ChecklistItem
from msgraph.generated.models.linked_resource import LinkedResource
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, ConfigDict

from office_365_mcp.graph_client import GraphNotFound, graph_errors, graph_step
from office_365_mcp.shared.handles import TaskHandle, TaskListHandle, TaskPartHandle
from office_365_mcp.shared.outlook.tasks import (
    AGAIN,
    ListAudience,
    TaskPart,
    list_audience,
    named_in_question,
    read_task,
    read_task_part,
    todo_request,
)
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import Approval, Question, Refusal, approved_write

STEP_DELETE = "delete_todo_item"

type Outcome = Literal["deleted", "not_found"]

type Target = TaskListHandle | TaskHandle | TaskPartHandle

_UNDONE = "This connector cannot undo the delete."


@dataclass(frozen=True, slots=True)
class Removed:
    name: str | None
    outcome: Outcome


class Deletion(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)


def _built_in(nothing_happened: str) -> str:
    return (
        "This handle names a built-in list of To Do: the Tasks list or the list of flagged "
        + "messages. Microsoft To Do does not delete these lists. To remove tasks from it, delete "
        + f"each task with outlook_delete_task. {nothing_happened} {AGAIN}"
    )


def _part_named(part: TaskPart) -> str:
    if isinstance(part, ChecklistItem):
        return named_in_question("step", part.display_name, missing="with no words")
    if isinstance(part, LinkedResource):
        link = named_in_question("link", part.display_name, missing="with no title")
        return f"{link}, which opens {cut_for_a_question(part.web_url or '')!r},"
    return named_in_question("file", part.name, missing="with no name")


def _name_of(part: TaskPart) -> str | None:
    if isinstance(part, ChecklistItem | LinkedResource):
        return part.display_name
    return part.name


def _question(
    audience: ListAudience, task_title: str | None, part: TaskPart | None, *, whole_task: bool
) -> str:
    task = named_in_question("task", task_title, missing="with no title")
    if part is None and not whole_task:
        return (
            f"Delete {audience.named} and every task in it?"
            + f"{audience.sharing_note('lose the list too')} {_UNDONE}"
        )
    if part is None:
        return (
            f"Delete {task} from {audience.named}?"
            + f"{audience.sharing_note('lose the task too')} {_UNDONE}"
        )
    kept = (
        " The item that the link opens does not change." if isinstance(part, LinkedResource) else ""
    )
    return (
        f"Delete {_part_named(part)} from {task} in {audience.named}?"
        + f"{audience.sharing_note('lose it too')}{kept} {_UNDONE}"
    )


async def delete_todo_item(
    client: GraphServiceClient, target: Target, *, approval: Approval
) -> Removed | InputRequiredResult | Refusal:
    named: str | None = None

    async def prepare(_must_ask: bool) -> Question | Refusal:
        nonlocal named
        audience = await list_audience(client, target.list_id)
        if isinstance(target, TaskListHandle):
            if audience.is_built_in:
                return Refusal(_built_in(approval.nothing_happened))
            named = audience.task_list.display_name
            question = _question(audience, None, None, whole_task=False)
            return Question(question, (audience.task_list,))
        task_handle = target if isinstance(target, TaskHandle) else target.task
        task = await read_task(client, task_handle)
        part = await read_task_part(client, target) if isinstance(target, TaskPartHandle) else None
        named = task.title if part is None else _name_of(part)
        shown: tuple[Parsable, ...] = (audience.task_list, task, *(() if part is None else (part,)))
        return Question(_question(audience, task.title, part, whole_task=True), shown)

    async def write(_headers: HeadersCollection) -> Removed:
        with graph_step(STEP_DELETE):
            await _sent_delete(client, target)
        return Removed(named, "deleted")

    with graph_errors():
        try:
            return await approved_write(approval, prepare=prepare, write=write)
        except GraphNotFound:
            return Removed(named, "not_found")


async def _sent_delete(client: GraphServiceClient, target: Target) -> None:
    once: RequestConfiguration[QueryParameters] = todo_request(
        safe_to_repeat=False, task_times=False
    )
    task_list = client.me.todo.lists.by_todo_task_list_id(target.list_id)
    if isinstance(target, TaskListHandle):
        await task_list.delete(request_configuration=once)
        return
    task = task_list.tasks.by_todo_task_id(target.task_id)
    if isinstance(target, TaskHandle):
        await task.delete(request_configuration=once)
    elif target.kind == "steps":
        await task.checklist_items.by_checklist_item_id(target.part_id).delete(
            request_configuration=once
        )
    elif target.kind == "links":
        await task.linked_resources.by_linked_resource_id(target.part_id).delete(
            request_configuration=once
        )
    else:
        await task.attachments.by_attachment_base_id(target.part_id).delete(
            request_configuration=once
        )
