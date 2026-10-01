from collections.abc import Mapping
from typing import Literal, Self

import httpx
from fastmcp import FastMCP
from msgraph.generated.models.inference_classification_override import (
    InferenceClassificationOverride,
)
from msgraph.generated.models.inference_classification_type import InferenceClassificationType
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import MAX_SCANNED_ITEMS, collect_pages, graph_errors
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "outlook_list_focused_overrides"

STEP = "focused_overrides"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Mail.Read",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {}

type ClassifyAs = Literal["focused", "other"]

_DESCRIPTION = """\
Lists the senders for which the signed-in user chose a fixed inbox tab in Outlook, Focused or \
Other. Each row gives one sender address and the tab for that sender. \
outlook_set_focused_override adds a sender or changes a row.

Notes:
- Outlook puts every future message from a listed sender in the tab of `classify_as`. A sender \
that is not listed has no fixed tab, and Outlook decides the tab for its mail.
- An empty list means that the user fixed no sender. A listed sender has exactly one row.
"""


class FocusedOverride(BaseModel):
    sender_address: str = Field(
        description=(
            "The SMTP address of the sender. Each address has at most one row. Use this value "
            "as `sender` in outlook_set_focused_override."
        )
    )
    sender_name: str | None = Field(
        description=(
            "The display name that Outlook stores with the address. It is null when Graph gives "
            "no name."
        )
    )
    classify_as: ClassifyAs | None = Field(
        description=(
            "The tab that holds all future mail from this sender. `focused` means the Focused "
            "tab. `other` means the Other tab. It is null when Graph gives none."
        )
    )

    @classmethod
    def from_override(cls, override: InferenceClassificationOverride) -> Self:
        sender = override.sender_email_address
        assert sender is not None and sender.address is not None, (
            "Graph returned an override with no sender address"
        )
        return cls(
            sender_address=sender.address,
            sender_name=sender.name,
            classify_as=_reported(override.classify_as),
        )


class FocusedOverrides(BaseModel):
    overrides: list[FocusedOverride] = Field(
        description=(
            "The senders that have a fixed tab, in the order that Graph returned them. "
            "The list is empty when the user fixed no sender."
        )
    )
    capped: bool = Field(
        description=(
            "True when the listing stopped early and more senders remain. False means that the "
            "list holds every sender that has a fixed tab."
        )
    )


async def list_focused_overrides(client: GraphServiceClient) -> FocusedOverrides:
    with graph_errors(TOOL_NAME, step=STEP):
        first_page = await client.me.inference_classification.overrides.get()
        assert first_page is not None, "Graph answered an override listing with no collection"
        collected = await collect_pages(first_page, client, limit=MAX_SCANNED_ITEMS)

    return FocusedOverrides(
        overrides=[FocusedOverride.from_override(override) for override in collected.items],
        capped=collected.capped,
    )


def _reported(classify_as: InferenceClassificationType | None) -> ClassifyAs | None:
    match classify_as:
        case None:
            return None
        case InferenceClassificationType.Focused:
            return "focused"
        case InferenceClassificationType.Other:
            return "other"


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="List Focused Inbox Overrides",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def outlook_list_focused_overrides(
        client: GraphServiceClient = graph,
    ) -> FocusedOverrides:
        return await list_focused_overrides(client)
