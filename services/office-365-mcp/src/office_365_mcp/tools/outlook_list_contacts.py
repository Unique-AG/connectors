from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.users.item.contacts.contacts_request_builder import ContactsRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import MAX_SCANNED_ITEMS, collect_pages, graph_errors
from office_365_mcp.shared.contacts import SUMMARY_FIELDS, ContactSummary
from office_365_mcp.shared.immutable_ids import immutable_id_headers
from office_365_mcp.shared.mail import ONE_ADDRESS
from office_365_mcp.shared.odata import odata_literal
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "outlook_list_contacts"

STEP = "contacts"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Contacts.Read",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {}

_ContactsQuery = ContactsRequestBuilder.ContactsRequestBuilderGetQueryParameters

_AGAIN = "If you call this tool again with the same arguments, the call will fail the same way."

_DESCRIPTION = """\
Lists the contacts in the default Contacts folder of the signed-in user. Each row gives the \
names, the email addresses, the telephone numbers, the company, and the job title of one \
contact. To read one contact in full, give the `uri` of its row to outlook_read_contact.

Notes:
- This tool reads only the default Contacts folder. A contact in another contact folder can be \
missing from the list.
- If `capped` is true, more contacts can match beyond this result. Before you decide that no \
contact matches, make sure that `capped` is false.
"""

_NOT_ONE_ADDRESS = (
    "outlook_list_contacts takes one SMTP address in `address`, such as `alexw@example.com`. A "
    + f"name is not an address. This tool read nothing. {_AGAIN}"
)


class Contacts(BaseModel):
    contacts: list[ContactSummary] = Field(
        description=(
            "The contacts that matched, in the order that Graph returns them. The list is empty "
            + "when no contact matched. Read `capped` before you report that the list is complete."
        )
    )
    capped: bool = Field(
        description=(
            "True when the listing stopped early and more contacts remain. To see more, raise "
            + "`limit`. False means that the answer holds every contact that matched."
        )
    )


async def list_contacts(
    client: GraphServiceClient, *, address: str | None = None, limit: int
) -> Contacts:
    assert 1 <= limit <= MAX_SCANNED_ITEMS, (
        f"limit must be within 1..{MAX_SCANNED_ITEMS}, got {limit}"
    )
    trimmed = address.strip() if address is not None else None
    if trimmed is not None and ONE_ADDRESS.match(trimmed) is None:
        raise ToolError(_NOT_ONE_ADDRESS)

    headers = immutable_id_headers()
    with graph_errors(TOOL_NAME, step=STEP):
        first_page = await client.me.contacts.get(
            request_configuration=RequestConfiguration[_ContactsQuery](
                query_parameters=_ContactsQuery(
                    filter=_holding(trimmed), select=list(SUMMARY_FIELDS), top=limit
                ),
                headers=headers,
            )
        )
        assert first_page is not None, "Graph answered a contact listing with no collection"
        collected = await collect_pages(first_page, client, limit=limit, headers=headers)

    return Contacts(
        contacts=[ContactSummary.from_contact(contact) for contact in collected.items],
        capped=collected.capped,
    )


def _holding(address: str | None) -> str | None:
    if address is None:
        return None
    return f"emailAddresses/any(a:a/address eq '{odata_literal(address)}')"


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="List Contacts",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def outlook_list_contacts(
        address: Annotated[
            str | None,
            Field(
                min_length=1,
                description=(
                    "One SMTP address, such as `alexw@example.com`, to list only the contacts "
                    + "that hold this address. Microsoft 365 matches the whole address, not a "
                    + "part of it. To find a contact by name, omit `address` and read the names "
                    + "in the list."
                ),
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_SCANNED_ITEMS,
                description=(
                    "How many contacts to return. The answer is the whole result of this call. A "
                    + "second call with the same `limit` returns the same contacts, not the next "
                    + "contacts. Raise `limit` to see more."
                ),
            ),
        ] = 50,
        client: GraphServiceClient = graph,
    ) -> Contacts:
        return await list_contacts(client, address=address, limit=limit)
