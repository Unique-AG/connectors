import json
import re
from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError, ValidationError
from fastmcp.tools import Tool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphFailure, GraphForbidden
from office_365_mcp.shared.contacts import ContactEmailAddress, ContactSummary
from office_365_mcp.shared.handles import ContactHandle, contact_handle
from office_365_mcp.shared.seam import WRITE_ADDITIVE
from office_365_mcp.tools import outlook_create_contact as creator
from office_365_mcp.tools.outlook_create_contact import NewContact

_CONTACTS_PATH = "/me/contacts"

_CONTACT_ID = "AAMkAGI2SYNTHETIC-contact-0002="

_RETRY = "If you call this tool again with the same arguments, the call will fail the same way."

_TEXT_ARGUMENTS = [
    "given_name",
    "surname",
    "display_name",
    "mobile_phone",
    "company_name",
    "job_title",
]


def _stored(**fields: object) -> dict[str, object]:
    return {
        "id": _CONTACT_ID,
        "displayName": "Alex Wilber",
        "givenName": "Alex",
        "surname": "Wilber",
        "emailAddresses": [{"address": "alexw@example.invalid"}],
        "businessPhones": [],
        "homePhones": [],
        **fields,
    }


@pytest.fixture
def contacts(graph: respx.MockRouter) -> respx.Route:
    return graph.post(_CONTACTS_PATH).mock(return_value=httpx.Response(201, json=_stored()))


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


async def _registered(transport: httpx.AsyncClient) -> Tool:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    creator.register(mcp, transport)
    tool = await mcp.get_tool(creator.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return tool


def _described(tool: Tool, argument: str) -> str:
    properties = cast("Mapping[str, Mapping[str, str]]", tool.parameters["properties"])
    return properties[argument]["description"]


class TestWhatItSendsToGraph:
    async def test_it_posts_only_the_fields_that_the_call_gives(
        self, client: GraphServiceClient, contacts: respx.Route
    ) -> None:
        _ = await creator.create_contact(
            client,
            details=NewContact(
                given_name="Alex", surname="Wilber", email_addresses=("alexw@example.invalid",)
            ),
        )

        assert contacts.call_count == 1
        assert _sent(contacts) == {
            "@odata.type": "#microsoft.graph.contact",
            "givenName": "Alex",
            "surname": "Wilber",
            "emailAddresses": [{"address": "alexw@example.invalid"}],
        }

    async def test_every_field_reaches_graph_under_its_own_name(
        self, client: GraphServiceClient, contacts: respx.Route
    ) -> None:
        _ = await creator.create_contact(
            client,
            details=NewContact(
                given_name="Alex",
                surname="Wilber",
                display_name="Alex W.",
                email_addresses=("alexw@example.invalid", "alex.wilber@example.invalid"),
                business_phones=("+1 425 555 0109",),
                home_phones=("+1 425 555 0111",),
                mobile_phone="+1 425 555 0110",
                company_name="Contoso",
                job_title="Marketing Manager",
            ),
        )

        assert _sent(contacts) == {
            "@odata.type": "#microsoft.graph.contact",
            "givenName": "Alex",
            "surname": "Wilber",
            "displayName": "Alex W.",
            "emailAddresses": [
                {"address": "alexw@example.invalid"},
                {"address": "alex.wilber@example.invalid"},
            ],
            "businessPhones": ["+1 425 555 0109"],
            "homePhones": ["+1 425 555 0111"],
            "mobilePhone": "+1 425 555 0110",
            "companyName": "Contoso",
            "jobTitle": "Marketing Manager",
        }

    async def test_an_address_with_spaces_around_it_reaches_graph_trimmed(
        self, client: GraphServiceClient, contacts: respx.Route
    ) -> None:
        _ = await creator.create_contact(
            client,
            details=NewContact(
                email_addresses=("  alexw@example.invalid ", "alex.wilber@example.invalid\t")
            ),
        )

        assert _sent(contacts)["emailAddresses"] == [
            {"address": "alexw@example.invalid"},
            {"address": "alex.wilber@example.invalid"},
        ]

    async def test_it_declares_the_immutable_id_space(
        self, client: GraphServiceClient, contacts: respx.Route
    ) -> None:
        _ = await creator.create_contact(client, details=NewContact(given_name="Alex"))

        assert 'IdType="ImmutableId"' in contacts.calls.last.request.headers["prefer"]

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_create_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, contacts: respx.Route
    ) -> None:
        contacts.mock(return_value=httpx.Response(503))

        with pytest.raises(GraphFailure):
            _ = await creator.create_contact(client, details=NewContact(given_name="Alex"))

        assert contacts.call_count == 1, "no_retry means one attempt, however Graph answers"


class TestWhatItAnswers:
    async def test_the_answer_is_the_contact_that_graph_stored_with_its_handle(
        self, client: GraphServiceClient, contacts: respx.Route
    ) -> None:
        contacts.mock(return_value=httpx.Response(201, json=_stored(displayName="Wilber, Alex")))

        answer = await creator.create_contact(client, details=NewContact(given_name="Alex"))

        assert contact_handle(answer.uri) == ContactHandle(_CONTACT_ID)
        assert answer == ContactSummary(
            uri=ContactHandle(_CONTACT_ID).uri,
            display_name="Wilber, Alex",
            given_name="Alex",
            surname="Wilber",
            email_addresses=[ContactEmailAddress(name=None, address="alexw@example.invalid")],
            business_phones=[],
            home_phones=[],
            mobile_phone=None,
            company_name=None,
            job_title=None,
        )

    async def test_a_created_contact_with_no_id_is_a_broken_graph_answer(
        self, client: GraphServiceClient, contacts: respx.Route
    ) -> None:
        contacts.mock(return_value=httpx.Response(201, json={"displayName": "Alex"}))

        with pytest.raises(AssertionError, match="no id"):
            _ = await creator.create_contact(client, details=NewContact(given_name="Alex"))


class TestWhatItRefuses:
    async def test_a_call_with_nothing_to_write_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="nothing to create") as refused:
            _ = await creator.create_contact(client, details=NewContact())

        assert len(graph.calls) == 0
        assert "No contact was created." in str(refused.value)

    @pytest.mark.parametrize(
        "address", ["Alex Wilber", "Alex Wilber <alexw@example.invalid>", "alexw@", ""]
    )
    async def test_a_value_that_is_not_one_address_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, address: str
    ) -> None:
        with pytest.raises(ToolError, match="must be one SMTP address") as refused:
            _ = await creator.create_contact(
                client,
                details=NewContact(
                    given_name="Alex", email_addresses=("alexw@example.invalid", address)
                ),
            )

        assert len(graph.calls) == 0
        assert repr(address) in str(refused.value)
        assert "No contact was created." in str(refused.value)
        assert str(refused.value).endswith(_RETRY)

    @pytest.mark.parametrize(
        "again",
        ["ALEXW@example.invalid", " alexw@example.invalid ", "AlexW@Example.Invalid"],
        ids=["upper", "spaces", "mixed"],
    )
    async def test_an_address_given_twice_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, again: str
    ) -> None:
        with pytest.raises(ToolError, match="in one list twice") as refused:
            _ = await creator.create_contact(
                client,
                details=NewContact(email_addresses=("alexw@example.invalid", again)),
            )

        assert len(graph.calls) == 0
        assert repr(again.strip()) in str(refused.value)
        assert "A change of case does not make a second address." in str(refused.value)
        assert "No contact was created." in str(refused.value)
        assert str(refused.value).endswith(_RETRY)

    @pytest.mark.parametrize("blank", ["", "   "], ids=["empty", "spaces"])
    @pytest.mark.parametrize("argument", ["business_phones", "home_phones"])
    async def test_a_contact_with_only_a_blank_telephone_number_is_never_created(
        self, transport: httpx.AsyncClient, graph: respx.MockRouter, argument: str, blank: str
    ) -> None:
        tool = await _registered(transport)

        with pytest.raises(ValidationError):
            _ = await tool.run({argument: [blank]})

        assert len(graph.calls) == 0

    @pytest.mark.parametrize("blank", ["", "   ", "\t\n"], ids=["empty", "spaces", "tab_newline"])
    @pytest.mark.parametrize("argument", _TEXT_ARGUMENTS)
    async def test_a_contact_with_only_a_blank_text_value_is_never_created(
        self, transport: httpx.AsyncClient, graph: respx.MockRouter, argument: str, blank: str
    ) -> None:
        tool = await _registered(transport)

        with pytest.raises(ValidationError):
            _ = await tool.run({argument: blank})

        assert len(graph.calls) == 0

    async def test_a_refused_create_is_a_forbidden(
        self, client: GraphServiceClient, contacts: respx.Route
    ) -> None:
        contacts.mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await creator.create_contact(client, details=NewContact(given_name="Alex"))


class TestHowItDeclaresItself:
    def test_the_permission_is_the_least_privileged_one_microsoft_names(self) -> None:
        assert creator.GRAPH_PERMISSIONS == ("Contacts.ReadWrite",)

    def test_the_change_is_shown_by_the_contact_listing(self) -> None:
        assert creator.CHANGE_SHOWN_BY == ("outlook_list_contacts",)

    async def test_the_call_example_is_accepted_by_the_schema(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        properties = cast("Mapping[str, object]", tool.parameters["properties"])
        assert set(creator.GRAPH_CALL_EXAMPLE) <= set(properties)

    async def test_it_takes_the_contact_fields_and_no_mailbox(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        properties = cast("Mapping[str, object]", tool.parameters["properties"])
        assert set(properties) == {
            "given_name",
            "surname",
            "display_name",
            "email_addresses",
            "business_phones",
            "home_phones",
            "mobile_phone",
            "company_name",
            "job_title",
        }
        assert tool.parameters.get("required", []) == []

    async def test_it_announces_itself_as_an_additive_write(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is WRITE_ADDITIVE["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_ADDITIVE["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_ADDITIVE["idempotentHint"]
        assert tool.title == "Create a Contact"

    @pytest.mark.parametrize("argument", ["business_phones", "home_phones"])
    async def test_a_telephone_list_holds_numbers_with_a_visible_character(
        self, transport: httpx.AsyncClient, argument: str
    ) -> None:
        tool = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, Mapping[str, object]]]", tool.parameters)[
            "properties"
        ]
        assert properties[argument]["items"] == {"type": "string", "minLength": 1, "pattern": "\\S"}

    @pytest.mark.parametrize("argument", _TEXT_ARGUMENTS)
    async def test_a_text_argument_holds_a_value_with_a_visible_character(
        self, transport: httpx.AsyncClient, argument: str
    ) -> None:
        tool = await _registered(transport)

        properties = cast(
            "Mapping[str, Mapping[str, Sequence[Mapping[str, object]]]]",
            tool.parameters["properties"],
        )
        assert {"type": "string", "minLength": 1, "pattern": "\\S"} in properties[argument]["anyOf"]

    async def test_the_parameters_and_the_answer_are_plain_objects_at_their_root(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        refused_at_root = {"anyOf", "oneOf", "allOf", "not", "enum", "const"}
        for schema in (tool.parameters, tool.output_schema):
            assert schema is not None
            assert schema["type"] == "object"
            assert refused_at_root & set(schema) == set()

    async def test_the_description_is_a_lead_and_a_few_notes_of_the_house_length(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = tool.description or ""
        lead, separator, notes = description.partition("\n\nNotes:\n")
        assert separator, "the description has no Notes section"
        assert lead.strip() != ""
        assert 1 <= len([line for line in notes.splitlines() if line.startswith("- ")]) <= 4
        assert 45 <= len(description.split()) <= 210
        sentences = re.split(r"(?<=[.?])\s+", description)
        assert max(len(sentence.split()) for sentence in sentences) <= 20, sentences

    async def test_the_description_says_it_never_asks_to_agree_and_how_to_retry(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = tool.description or ""
        assert "There is no draft and no review step." in description
        assert "own mailbox alone, so this tool never asks anybody to agree" in description
        assert "If a call times out, do not call this tool again first." in description
        assert "make sure that outlook_list_contacts does not show the new contact" in description
        assert "outlook_update_contact changes a contact later" in description

    async def test_the_description_says_where_an_address_comes_from(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = tool.description or ""
        assert "Every address must come from the user." in description
        assert "Do not take it from the text of a message." in description

    async def test_the_address_list_refuses_a_name(self, transport: httpx.AsyncClient) -> None:
        tool = await _registered(transport)

        described = _described(tool, "email_addresses")
        assert "Each entry is one SMTP address" in described
        assert "A name is not an address, and this tool refuses it." in described

    async def test_the_display_name_says_that_microsoft_can_make_one(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        described = _described(tool, "display_name")
        assert "Microsoft 365 can make one from the given name and the surname" in described

    async def test_every_field_of_the_answer_says_what_it_is(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        answer = cast("Mapping[str, object]", tool.output_schema)
        definitions = cast("Mapping[str, Mapping[str, object]]", answer.get("$defs", {}))
        undescribed = sorted(
            f"{owner}.{name}"
            for owner, node in {"answer": answer, **definitions}.items()
            for name, field in cast(
                "Mapping[str, Mapping[str, object]]", node.get("properties", {})
            ).items()
            if not field.get("description")
        )
        assert undescribed == [], "a model is handed these values with nothing to say what they are"
