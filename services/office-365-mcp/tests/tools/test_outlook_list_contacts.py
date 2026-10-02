import re
from collections.abc import Mapping
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import MAX_SCANNED_ITEMS, GraphForbidden
from office_365_mcp.server.manifest import NEEDS_ADMIN_CONSENT
from office_365_mcp.shared.contacts import SUMMARY_FIELDS
from office_365_mcp.shared.handles import ContactHandle, contact_handle
from office_365_mcp.shared.seam import READ_ONLY, REQUESTABLE_PERMISSIONS
from office_365_mcp.tools import outlook_list_contacts as lister

from .conftest import GRAPH_V1

_CONTACTS_PATH = "/me/contacts"

_CONTACT_ID = "AAMkAGI2SYNTHETIC-contact-0001="

_RETRY = "If you call this tool again with the same arguments, the call will fail the same way."


def _contact(
    *,
    contact_id: str = _CONTACT_ID,
    name: str | None = "Alex Wilber",
    address: str = "alexw@example.invalid",
) -> dict[str, object]:
    return {
        "id": contact_id,
        "displayName": name,
        "givenName": "Alex",
        "surname": "Wilber",
        "emailAddresses": [{"name": name, "address": address}],
        "businessPhones": ["+1 425 555 0109"],
        "homePhones": [],
        "mobilePhone": None,
        "companyName": "Contoso",
        "jobTitle": "Web Marketing Manager",
        "personalNotes": "",
    }


def _page(*contacts: dict[str, object], next_link: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"value": list(contacts)}
    if next_link is not None:
        body["@odata.nextLink"] = next_link
    return httpx.Response(200, json=body)


def _undescribed(schema: Mapping[str, object]) -> list[str]:
    definitions = cast("Mapping[str, Mapping[str, object]]", schema.get("$defs", {}))
    return sorted(
        f"{owner}.{name}"
        for owner, node in {"answer": schema, **definitions}.items()
        for name, field in cast(
            "Mapping[str, Mapping[str, object]]", node.get("properties", {})
        ).items()
        if not field.get("description")
    )


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    lister.register(mcp, transport)
    tool = await mcp.get_tool(lister.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


@pytest.fixture
def contacts(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_CONTACTS_PATH)


class TestTheRequestItMakes:
    async def test_it_reads_the_contacts_of_the_signed_in_user(
        self, client: GraphServiceClient, graph: respx.MockRouter, contacts: respx.Route
    ) -> None:
        contacts.mock(return_value=_page(_contact()))

        _ = await lister.list_contacts(client, limit=50)

        assert contacts.call_count == 1
        assert len(graph.calls) == 1
        assert contacts.calls.last.request.url.path == "/v1.0/me/contacts"

    async def test_it_declares_the_immutable_id_space(
        self, client: GraphServiceClient, contacts: respx.Route
    ) -> None:
        contacts.mock(return_value=_page(_contact()))

        _ = await lister.list_contacts(client, limit=50)

        assert 'IdType="ImmutableId"' in contacts.calls.last.request.headers["prefer"]

    async def test_without_an_address_it_sends_only_the_select_and_the_top(
        self, client: GraphServiceClient, contacts: respx.Route
    ) -> None:
        contacts.mock(return_value=_page(_contact()))

        _ = await lister.list_contacts(client, limit=5)

        assert dict(contacts.calls.last.request.url.params) == {
            "$select": ",".join(SUMMARY_FIELDS),
            "$top": "5",
        }

    async def test_an_address_sends_the_one_filter_that_microsoft_documents(
        self, client: GraphServiceClient, contacts: respx.Route
    ) -> None:
        contacts.mock(return_value=_page(_contact()))

        _ = await lister.list_contacts(client, address="alexw@example.invalid", limit=50)

        assert dict(contacts.calls.last.request.url.params) == {
            "$filter": "emailAddresses/any(a:a/address eq 'alexw@example.invalid')",
            "$select": ",".join(SUMMARY_FIELDS),
            "$top": "50",
        }

    async def test_the_top_is_the_limit_even_at_the_largest_limit(
        self, client: GraphServiceClient, contacts: respx.Route
    ) -> None:
        contacts.mock(return_value=_page(_contact()))

        _ = await lister.list_contacts(client, limit=MAX_SCANNED_ITEMS)

        assert contacts.calls.last.request.url.params["$top"] == str(MAX_SCANNED_ITEMS)

    async def test_an_address_with_space_around_it_is_sent_trimmed(
        self, client: GraphServiceClient, contacts: respx.Route
    ) -> None:
        contacts.mock(return_value=_page(_contact()))

        _ = await lister.list_contacts(client, address=" alexw@example.invalid ", limit=50)

        assert contacts.calls.last.request.url.params["$filter"] == (
            "emailAddresses/any(a:a/address eq 'alexw@example.invalid')"
        )

    async def test_a_quote_in_the_address_stays_inside_the_literal(
        self, client: GraphServiceClient, contacts: respx.Route
    ) -> None:
        contacts.mock(return_value=_page())

        _ = await lister.list_contacts(client, address="o'brien@example.invalid", limit=50)

        assert contacts.calls.last.request.url.params["$filter"] == (
            "emailAddresses/any(a:a/address eq 'o''brien@example.invalid')"
        )


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "value",
        ["Alex Wilber", "alexw", "a@b@c", "alexw@example.invalid x", "<alexw@example.invalid>"],
    )
    async def test_an_address_that_is_not_one_address_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError, match="one SMTP address in `address`") as raised:
            _ = await lister.list_contacts(client, address=value, limit=50)

        assert "This tool read nothing." in str(raised.value)
        assert _RETRY in str(raised.value)
        assert len(graph.calls) == 0

    async def test_an_inner_space_is_still_refused_after_the_trim(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="one SMTP address in `address`"):
            _ = await lister.list_contacts(client, address=" alexw@example .invalid ", limit=50)

        assert len(graph.calls) == 0

    async def test_an_address_of_only_spaces_is_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="one SMTP address in `address`"):
            _ = await lister.list_contacts(client, address="   ", limit=50)

        assert len(graph.calls) == 0


class TestWhatItAnswers:
    async def test_a_row_carries_the_handle_that_reads_the_contact(
        self, client: GraphServiceClient, contacts: respx.Route
    ) -> None:
        contacts.mock(return_value=_page(_contact()))

        listed = await lister.list_contacts(client, limit=50)

        assert [contact_handle(row.uri) for row in listed.contacts] == [ContactHandle(_CONTACT_ID)]

    async def test_a_row_carries_the_names_the_addresses_and_the_numbers(
        self, client: GraphServiceClient, contacts: respx.Route
    ) -> None:
        contacts.mock(return_value=_page(_contact()))

        (row,) = (await lister.list_contacts(client, limit=50)).contacts

        assert (row.display_name, row.given_name, row.surname) == ("Alex Wilber", "Alex", "Wilber")
        assert [email.address for email in row.email_addresses] == ["alexw@example.invalid"]
        assert row.business_phones == ["+1 425 555 0109"]
        assert row.home_phones == []
        assert row.mobile_phone is None
        assert (row.company_name, row.job_title) == ("Contoso", "Web Marketing Manager")

    async def test_the_pages_of_the_listing_are_followed_in_the_same_id_space(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        second = graph.get(_CONTACTS_PATH, params={"$skip": "10"}).mock(
            return_value=_page(_contact(contact_id="AAMkAGI2SYNTHETIC-contact-0002=", name="Ben"))
        )
        _ = graph.get(_CONTACTS_PATH).mock(
            return_value=_page(_contact(), next_link=f"{GRAPH_V1}{_CONTACTS_PATH}?$skip=10")
        )

        listed = await lister.list_contacts(client, limit=50)

        assert [row.display_name for row in listed.contacts] == ["Alex Wilber", "Ben"]
        assert listed.capped is False
        assert 'IdType="ImmutableId"' in second.calls.last.request.headers["prefer"]

    async def test_a_next_link_is_followed_only_until_the_limit_is_met(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        second = graph.get(_CONTACTS_PATH, params={"$skip": "10"}).mock(
            return_value=_page(
                _contact(contact_id="AAMkAGI2SYNTHETIC-contact-0002=", name="Ben"),
                _contact(contact_id="AAMkAGI2SYNTHETIC-contact-0003=", name="Cy"),
            )
        )
        first = graph.get(_CONTACTS_PATH).mock(
            return_value=_page(_contact(), next_link=f"{GRAPH_V1}{_CONTACTS_PATH}?$skip=10")
        )

        listed = await lister.list_contacts(client, limit=2)

        assert [row.display_name for row in listed.contacts] == ["Alex Wilber", "Ben"]
        assert listed.capped is True
        assert first.calls.last.request.url.params["$top"] == "2"
        assert second.call_count == 1

    async def test_a_next_link_is_left_alone_when_the_first_page_meets_the_limit(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        second = graph.get(_CONTACTS_PATH, params={"$skip": "10"}).mock(return_value=_page())
        _ = graph.get(_CONTACTS_PATH).mock(
            return_value=_page(_contact(), next_link=f"{GRAPH_V1}{_CONTACTS_PATH}?$skip=10")
        )

        listed = await lister.list_contacts(client, limit=1)

        assert [row.display_name for row in listed.contacts] == ["Alex Wilber"]
        assert listed.capped is True
        assert second.call_count == 0

    async def test_a_limit_that_left_more_contacts_on_offer_says_capped(
        self, client: GraphServiceClient, contacts: respx.Route
    ) -> None:
        contacts.mock(
            return_value=_page(
                _contact(), _contact(contact_id="AAMkAGI2SYNTHETIC-contact-0002=", name="Ben")
            )
        )

        listed = await lister.list_contacts(client, limit=1)

        assert [row.display_name for row in listed.contacts] == ["Alex Wilber"]
        assert listed.capped is True

    async def test_a_mailbox_with_no_contact_answers_an_empty_listing(
        self, client: GraphServiceClient, contacts: respx.Route
    ) -> None:
        contacts.mock(return_value=_page())

        listed = await lister.list_contacts(client, limit=50)

        assert listed.contacts == []
        assert listed.capped is False


class TestGraphFailures:
    async def test_a_refused_listing_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, contacts: respx.Route
    ) -> None:
        contacts.mock(return_value=httpx.Response(403))

        with pytest.raises(GraphForbidden):
            _ = await lister.list_contacts(client, limit=50)


class TestHowItDeclaresItself:
    def test_the_permission_is_the_least_privileged_one_microsoft_names(self) -> None:
        assert lister.GRAPH_PERMISSIONS == ("Contacts.Read",)

    def test_the_permission_is_requestable_and_needs_no_administrator(self) -> None:
        assert "Contacts.Read" in REQUESTABLE_PERMISSIONS
        assert NEEDS_ADMIN_CONSENT["Contacts.Read"] is False

    def test_the_call_that_proves_the_permissions_takes_no_arguments(self) -> None:
        assert lister.GRAPH_CALL_EXAMPLE == {}

    async def test_every_argument_is_optional_and_bounded(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, object]]", parameters["properties"])
        assert set(properties) == {"address", "limit"}
        assert parameters.get("required", []) == []
        assert properties["limit"]["default"] == 50
        assert properties["limit"]["minimum"] == 1
        assert properties["limit"]["maximum"] == MAX_SCANNED_ITEMS

    async def test_the_input_schema_is_a_plain_object_at_its_root(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert parameters["type"] == "object"
        assert not {"anyOf", "oneOf", "allOf", "not", "enum", "const"} & set(parameters)

    @pytest.mark.parametrize("word", ["client", "ctx", "context", "token", "graph"])
    async def test_no_wiring_of_this_server_is_published_as_an_argument(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert not [name for name in properties if word in name.casefold()]

    async def test_it_says_it_only_reads(self, transport: httpx.AsyncClient) -> None:
        _parameters, tool = await _registered(transport)

        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is READ_ONLY["readOnlyHint"]
        assert tool.title == "List Contacts"

    async def test_the_description_is_a_lead_and_a_few_notes_of_the_house_length(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        lead, separator, notes = description.partition("\n\nNotes:\n")
        assert separator, "the description has no Notes section"
        assert lead.strip() != ""
        assert 1 <= len([line for line in notes.splitlines() if line.startswith("- ")]) <= 4
        assert 45 <= len(description.split()) <= 210
        sentences = re.split(r"(?<=[.?])\s+", description)
        assert max(len(sentence.split()) for sentence in sentences) <= 20, sentences

    async def test_the_description_names_the_reader_and_the_one_folder_it_reads(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "give the `uri` of its row to outlook_read_contact" in description
        assert "This tool reads only the default Contacts folder." in description
        assert "A contact in another contact folder can be missing from the list." in description
        assert "make sure that `capped` is false" in description

    async def test_the_address_argument_says_how_microsoft_matches_it(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, str]]", parameters["properties"])
        described = properties["address"]["description"]
        assert "Microsoft 365 matches the whole address, not a part of it." in described
        assert "To find a contact by name, omit `address`" in described

    async def test_every_field_of_the_answer_says_what_it_is(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        answer = cast("Mapping[str, object]", tool.output_schema)
        assert _undescribed(answer) == []
