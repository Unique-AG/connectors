from collections.abc import Mapping
from contextlib import suppress
from typing import Annotated, Literal

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.checklist_item import ChecklistItem
from msgraph.generated.users.item.todo.lists.item.tasks.item.checklist_items.item.checklist_item_item_request_builder import (  # noqa: E501
    ChecklistItemItemRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import (
    GraphNotFound,
    graph_errors,
    graph_step,
    no_retry,
    not_graph,
)
from office_365_mcp.shared.handles import task_part_handle
from office_365_mcp.shared.outlook.tasks import ListAudience, bad_step_handle, list_audience
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Confirm,
    confirmation_digest,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "outlook_delete_task_step"

PRESETS: tuple[str, ...] = ("outlook-tasks-delete",)

STEP_TASK = "task"

STEP_READ = "task_step"

STEP_DELETE = "delete_task_step"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Tasks.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "step": (
        "outlook:///tasks/AAMkAGI2SYNTHETIC-list-0001%3D/AAMkAGI2SYNTHETIC-task-0001%3D"
        + "/steps/SYNTHETIC-step-0001"
    ),
}

_AGREE = "delete the step"
_DECLINE = "keep the step"
_NOTHING_DELETED = "The step was not deleted."

_AGAIN = "If you call this tool again with the same arguments, the call will fail the same way."


_DESCRIPTION = """\
Deletes one checklist step from a Microsoft To Do task, given the `steps[].uri` of an \
outlook_read_task answer. The task and its other steps stay. To check a step off and keep it, \
use outlook_update_task_step.

Notes:
- This tool always asks the user to agree, because this connector cannot bring a deleted step \
back. The question names the step and its task.
- This call is safe to repeat after a timeout. A second call finds no step and answers \
`not_found`.
"""


Outcome = Literal["deleted", "not_found"]


class DeletedTaskStep(BaseModel):
    text: str | None = Field(
        description=(
            "The words of the step, as this tool read them just before the delete. The value is "
            + "null when the step had no words, or when Microsoft 365 found no step to read."
        )
    )
    outcome: Outcome = Field(
        description=(
            "What this call did. `deleted`: Microsoft 365 accepted the delete, and this call "
            + "deleted the step. `not_found`: Microsoft 365 found no such step, before the "
            + "question or at the delete. The step was deleted before, or the user cannot see "
            + "it now. This call deleted nothing. When the value is `not_found`, do not tell the "
            + "user that this call deleted the step."
        )
    )


async def delete_task_step(
    client: GraphServiceClient, *, step: str, confirm: Confirm
) -> DeletedTaskStep | InputRequiredResult:
    handle = task_part_handle("steps", step)
    if handle is None:
        raise ToolError(bad_step_handle(TOOL_NAME, nothing_happened=_NOTHING_DELETED))

    asked: InputRequiredResult | None = None
    refused: str | None = None
    outcome: Outcome = "not_found"
    with graph_errors():
        task_builder = client.me.todo.lists.by_todo_task_list_id(
            handle.list_id
        ).tasks.by_todo_task_id(handle.task_id)
        step_builder = task_builder.checklist_items.by_checklist_item_id(handle.part_id)
        try:
            audience = await list_audience(client, handle.list_id)
            with graph_step(STEP_TASK):
                task = await task_builder.get()
        except GraphNotFound:
            return DeletedTaskStep(text=None, outcome="not_found")
        assert task is not None, "Graph answered a task read with no task"
        item = await _step(step_builder)
        if item is None:
            return DeletedTaskStep(text=None, outcome="not_found")
        question = _question(item.display_name, task.title, audience)
        about = confirmation_digest(
            TOOL_NAME, handle.uri, question, item.display_name or "", task.title or ""
        )
        with not_graph():
            answer = await confirm(question, about)
        asked = answer if isinstance(answer, InputRequiredResult) else None
        refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with suppress(GraphNotFound), graph_step(STEP_DELETE):
                await step_builder.delete(
                    request_configuration=RequestConfiguration[QueryParameters](options=no_retry())
                )
                outcome = "deleted"

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    return DeletedTaskStep(text=item.display_name, outcome=outcome)


async def _step(step_builder: ChecklistItemItemRequestBuilder) -> ChecklistItem | None:
    try:
        with graph_step(STEP_READ):
            item = await step_builder.get()
    except GraphNotFound:
        return None
    assert item is not None, "Graph answered a checklist item read with no item"
    return item


def _question(text: str | None, title: str | None, audience: ListAudience) -> str:
    step = repr(cut_for_a_question(text)) if text else "with no words"
    task = repr(cut_for_a_question(title)) if title else "with no title"
    shared = (
        ""
        if not audience.reaches_others
        else (
            " Other people share the list of this task, and they lose the step too."
            if audience.is_shared
            else " Microsoft 365 did not report the list of this task as private. Other people "
            + "can lose the step too."
        )
    )
    return (
        f"Delete the step {step} from the task {task}?{shared} This connector cannot undo the "
        + "delete."
    )


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_AGREE, decline=_DECLINE, nothing_happened=_NOTHING_DELETED)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Outlook: Delete a Step of a Task",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE_IDEMPOTENT,
    )
    async def outlook_delete_task_step(
        step: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The handle of the step to delete, from a `steps[].uri` of an "
                    + "outlook_read_task answer. Copy it word for word."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> DeletedTaskStep | InputRequiredResult:
        return await delete_task_step(client, step=step, confirm=a_person_agrees(ctx))
