from collections.abc import Mapping
from contextlib import suppress
from typing import Annotated, Literal

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from mcp.types import InputRequiredResult
from msgraph.generated.users.item.outlook.master_categories.master_categories_request_builder import (  # noqa: E501
    MasterCategoriesRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import (
    MAX_SCANNED_ITEMS,
    GraphNotFound,
    collect_pages,
    graph_errors,
    graph_step,
    not_graph,
)
from office_365_mcp.shared.categories import CategoryName
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Confirm,
    confirmation_digest,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "outlook_delete_category"

STEP_FIND = "categories"

STEP_DELETE = "delete_category"

GRAPH_PERMISSIONS: tuple[str, ...] = ("MailboxSettings.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"name": "Synthetic category"}

_AGREE = "delete the category"
_DECLINE = "keep the category"
_NOTHING_DELETED = "The category was not deleted."

_CategoriesQuery = MasterCategoriesRequestBuilder.MasterCategoriesRequestBuilderGetQueryParameters

_DESCRIPTION = """\
Deletes one category from the signed-in user's own list of categories, by its name. A message, \
event, or contact that carries the name keeps it as plain text, with no color. \
outlook_list_categories lists the names.

Notes:
- This tool always asks the user to agree, and the question names the category. This tool does \
not take the name off any message.
- To rename a category, use this tool last. If this deployment exposes outlook_create_category \
and outlook_mark_mail, create the new category, move the messages to it with outlook_mark_mail, \
and then delete the old category.
- This call is safe to repeat after a timeout. A second call finds no category and reports that.
"""

_NOT_A_CATEGORY = (
    "outlook_delete_category found no category with that name in the list of categories, so "
    + "nothing was deleted. If this deployment exposes outlook_list_categories, call it and use "
    + "a name from its result, exactly as it appears. If you call this tool again with the same "
    + "arguments, the call will fail the same way."
)


class DeletedCategory(BaseModel):
    name: str = Field(
        description=(
            "The name of the category, as Microsoft 365 reported it immediately before the "
            "delete. The category is gone, so no tool can find it by this name any more."
        )
    )
    deleted: Literal[True] = Field(
        description=(
            "Always true, because this tool answers only when the category is gone. It is also "
            "true when Graph found no category to delete after this call read the list."
        )
    )


async def delete_category(
    client: GraphServiceClient, *, name: str, confirm: Confirm
) -> DeletedCategory | InputRequiredResult:
    asked: InputRequiredResult | None = None
    refused: str | None = None
    found_name = name
    with graph_errors():
        with graph_step(STEP_FIND):
            first_page = await client.me.outlook.master_categories.get(
                request_configuration=RequestConfiguration[_CategoriesQuery](
                    query_parameters=_CategoriesQuery(select=["id", "displayName"])
                )
            )
        assert first_page is not None, "Graph answered a category listing with no collection"
        collected = await collect_pages(first_page, client, limit=MAX_SCANNED_ITEMS)
        found = next(
            (
                one
                for one in collected.items
                if one.display_name is not None and one.display_name.casefold() == name.casefold()
            ),
            None,
        )
        if found is None:
            refused = _NOT_A_CATEGORY
        else:
            assert found.id is not None and found.display_name is not None, (
                "Graph listed a category with no id or no display name"
            )
            found_name = found.display_name
            question = _question(found_name)
            about = confirmation_digest(TOOL_NAME, found.id, question)
            with not_graph():
                answer = await confirm(question, about)
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
            if refused is None and asked is None:
                with suppress(GraphNotFound), graph_step(STEP_DELETE):
                    await client.me.outlook.master_categories.by_outlook_category_id(
                        found.id
                    ).delete()

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    return DeletedCategory(name=found_name, deleted=True)


def _question(name: str) -> str:
    return (
        f"Delete the category {cut_for_a_question(name)!r} from your list of categories? Mail "
        + "and events that carry it keep the name as plain text, with no color. To get the "
        + "category back, someone must create it again."
    )


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_AGREE, decline=_DECLINE, nothing_happened=_NOTHING_DELETED)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Outlook: Delete a Category",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE_IDEMPOTENT,
    )
    async def outlook_delete_category(
        name: Annotated[
            CategoryName,
            Field(
                description=(
                    "The name of the category to delete, as outlook_list_categories reports it. "
                    "The match ignores letter case. The category is removed from the list of "
                    "categories only, and no message is changed."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> DeletedCategory | InputRequiredResult:
        return await delete_category(client, name=name, confirm=a_person_agrees(ctx))
