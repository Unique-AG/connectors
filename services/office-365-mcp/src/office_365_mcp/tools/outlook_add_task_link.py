from collections.abc import Mapping
from typing import Annotated, ClassVar
from urllib.parse import urlsplit

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.headers_collection import HeadersCollection
from mcp.types import InputRequiredResult
from msgraph.generated.models.linked_resource import LinkedResource
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, ConfigDict, Field

from office_365_mcp.graph_client import graph_errors, graph_step
from office_365_mcp.shared.handles import task_handle
from office_365_mcp.shared.outlook.tasks import (
    AGAIN,
    TaskLink,
    bad_handle,
    list_audience,
    named_in_question,
    read_task,
    todo_request,
)
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    WRITE_ADDITIVE,
    Approval,
    Confirm,
    Question,
    answer_pending,
    answered,
    approved_write,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "outlook_add_task_link"

PRESETS: tuple[str, ...] = ("outlook-tasks-write", "outlook-tasks-delete")

STEP_ADD_LINK = "add_task_link"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Tasks.ReadWrite",)

CHANGE_SHOWN_BY: tuple[str, ...] = ("outlook_read_task",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "outlook:///tasks/AAMkAGI2SYNTHETIC-list-0001%3D/AAMkAGI2SYNTHETIC-task-0001%3D",
    "web_url": "https://outlook.office365.com/owa/?ItemID=AAMkAGI2SYNTHETIC-message-0001",
    "title": "Q3 report from Anna",
}

_DEFAULT_APPLICATION = "Outlook"

_NOTHING_ADDED = "No link was added."
_ADD = "add the link"
_DO_NOT_ADD = "do not add the link"

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return this task, and no link was added. The handle is well formed, "
    + "so this is not a bad argument. The task was most likely deleted, or moved to another "
    + "list, which gives it a new handle: find it again with outlook_list_tasks and take a fresh "
    + "`uri`. If its list was deleted or is no longer shared with the user, call "
    + f"outlook_list_task_lists again instead. {AGAIN}"
)

_NOT_HTTPS = (
    "outlook_add_task_link takes an `https` address in `web_url`, such as the `web_link` that "
    + "outlook_read_mail returns, and this is not one. Use an address that the user gave or that "
    + "a tool returned, and copy it word for word. Do not make an address. "
    + f"{_NOTHING_ADDED} {AGAIN}"
)

_DESCRIPTION = """\
Adds one link to a Microsoft To Do task of the signed-in user, given the `uri` of an \
outlook_list_tasks row. A link opens an item that the task is about, such as the message that \
the task came from. To Do and Outlook show the link on the task.

Notes:
- Use an `https` address that the user gave or that a tool returned, such as the `web_link` of \
outlook_read_mail. This tool refuses every other kind of address.
- This tool asks the user to agree before it changes a task in a list that other people share, \
because they see the new link. A task in the user's own unshared list changes without a question.
- If a call times out, do not call this tool again first. Before you call again, make sure that \
outlook_read_task does not show the new link.
"""


def _is_https(address: str) -> bool:
    try:
        parts = urlsplit(address)
    except ValueError:
        return False
    return parts.scheme == "https" and bool(parts.hostname)


class _NewLink(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    web_url: str
    title: str
    application: str


async def add_task_link(
    client: GraphServiceClient,
    *,
    uri: str,
    web_url: str,
    title: str,
    application: str = _DEFAULT_APPLICATION,
    confirm: Confirm,
    answer_pending: bool = False,
) -> TaskLink | InputRequiredResult:
    handle = task_handle(uri)
    if handle is None:
        raise ToolError(
            bad_handle(TOOL_NAME, "task", argument="uri", nothing_happened=_NOTHING_ADDED)
        )
    if not _is_https(web_url):
        raise ToolError(_NOT_HTTPS)

    async def prepare(must_ask: bool) -> Question | None:
        audience = await list_audience(client, handle.list_id)
        if not (must_ask or audience.reaches_others):
            return None
        task = await read_task(client, handle)
        named = named_in_question("task", task.title, missing="with no title")
        question = (
            f"Add the link {cut_for_a_question(title)!r}, which opens "
            + f"{cut_for_a_question(web_url)!r} in {cut_for_a_question(application)!r}, to "
            + f"{named} in {audience.named}?{audience.sharing_note('see the new link')}"
        )
        return Question(question, (audience.task_list, task))

    async def write(headers: HeadersCollection) -> TaskLink:
        with graph_step(STEP_ADD_LINK):
            created = (
                await client.me.todo.lists.by_todo_task_list_id(handle.list_id)
                .tasks.by_todo_task_id(handle.task_id)
                .linked_resources.post(
                    LinkedResource(
                        web_url=web_url, display_name=title, application_name=application
                    ),
                    request_configuration=todo_request(
                        safe_to_repeat=False, task_times=False, headers=headers
                    ),
                )
            )
        assert created is not None, "Graph answered a new task link with no link"
        return TaskLink.from_resource(created, task=handle)

    approval = Approval(
        TOOL_NAME,
        handle.uri,
        _NewLink(web_url=web_url, title=title, application=application),
        confirm,
        answer_pending,
        _NOTHING_ADDED,
    )
    with graph_errors():
        result = await approved_write(approval, prepare=prepare, write=write)
    return answered(result)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Outlook: Add a Link to a Task",
        description=_DESCRIPTION,
        annotations=WRITE_ADDITIVE,
    )
    async def outlook_add_task_link(
        uri: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The handle of the task, from the `uri` of an outlook_list_tasks row. Copy "
                    + "it word for word."
                ),
            ),
        ],
        web_url: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The `https` address that the link opens. Use an address that the user gave "
                    + "or that a tool returned, such as the `web_link` of a mail or an event. Copy "
                    + "it word for word."
                ),
            ),
        ],
        title: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The words that To Do shows for the link, such as the subject of the message."
                ),
            ),
        ],
        ctx: Context,
        application: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The name of the app that holds the item, such as `Outlook`, `Teams`, or "
                    + "`SharePoint`. To Do shows it with the link. The default is `Outlook`."
                ),
            ),
        ] = _DEFAULT_APPLICATION,
        client: GraphServiceClient = graph,
    ) -> TaskLink | InputRequiredResult:
        return await add_task_link(
            client,
            uri=uri,
            web_url=web_url,
            title=title,
            application=application,
            confirm=person_confirms(
                ctx, agree=_ADD, decline=_DO_NOT_ADD, nothing_happened=_NOTHING_ADDED
            ),
            answer_pending=answer_pending(ctx),
        )
