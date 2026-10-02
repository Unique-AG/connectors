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

from office_365_mcp.graph_client import GraphFailure, GraphForbidden, GraphNotFound
from office_365_mcp.shared.contacts import ContactSummary
from office_365_mcp.shared.handles import (
    CalendarHandle,
    ContactHandle,
    MailMessageHandle,
    contact_handle,
)
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE_IDEMPOTENT
from office_365_mcp.tools import outlook_update_contact as updater
from office_365_mcp.tools.outlook_update_contact import ContactChange

_CONTACT_ID = "AAMkAGI2SYNTHETIC-contact-0001="

_CONTACT_URI = "outlook:///contacts/AAMkAGI2SYNTHETIC-contact-0001%3D"

_PATH = "/me/contacts/AAMkAGI2SYNTHETIC-contact-0001%3D"

_RETRY = "If you call this tool again with the same arguments, the call will fail the same way."

_TEXT_ARGUMENTS = [
    "given_name",
    "surname",
    "display_name",
    "mobile_phone",
    "company_name",
    "job_title",
]

_CURRENT: Mapping[str, object] = {
    "id": _CONTACT_ID,
    "emailAddresses": [
        {"name": "Alex Wilber", "address": "alexw@example.invalid", "type": "unknown"},
        {"name": "Alex Wilber", "address": "alex.wilber@example.invalid", "type": "personal"},
    ],
    "businessPhones": ["+1 425 555 0109"],
    "homePhones": ["+1 425 555 0111"],
}


def _updated(**fields: object) -> dict[str, object]:
    return {"id": _CONTACT_ID, "displayName": "Alex Wilber", **fields}


@pytest.fixture
def read(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_PATH).mock(return_value=httpx.Response(200, json=dict(_CURRENT)))


@pytest.fixture
def write(graph: respx.MockRouter) -> respx.Route:
    return graph.patch(_PATH).mock(return_value=httpx.Response(200, json=_updated()))


def _sent(route: respx.Route) -> dict[str, object]:
    body = cast("dict[str, object]", json.loads(route.calls.last.request.content))
    return {key: value for key, value in body.items() if key != "@odata.type"}


async def _changed(client: GraphServiceClient, change: ContactChange) -> ContactSummary:
    return await updater.update_contact(client, uri=_CONTACT_URI, change=change)


async def _registered(transport: httpx.AsyncClient) -> Tool:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    updater.register(mcp, transport)
    tool = await mcp.get_tool(updater.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return tool


def _described(tool: Tool, argument: str) -> str:
    properties = cast("Mapping[str, Mapping[str, str]]", tool.parameters["properties"])
    return properties[argument]["description"]


class TestWhatItSendsToGraph:
    async def test_a_change_of_fields_alone_reads_nothing_and_patches_only_those_fields(
        self, client: GraphServiceClient, graph: respx.MockRouter, write: respx.Route
    ) -> None:
        _ = await _changed(client, ContactChange(job_title="Director", company_name="Fabrikam"))

        assert len(graph.calls) == 1
        assert write.call_count == 1
        assert _sent(write) == {"jobTitle": "Director", "companyName": "Fabrikam"}

    async def test_every_field_reaches_graph_under_its_own_name(
        self, client: GraphServiceClient, write: respx.Route
    ) -> None:
        _ = await _changed(
            client,
            ContactChange(
                given_name="Alex",
                surname="Wilber",
                display_name="Alex W.",
                mobile_phone="+1 425 555 0110",
                company_name="Contoso",
                job_title="Marketing Manager",
            ),
        )

        assert _sent(write) == {
            "givenName": "Alex",
            "surname": "Wilber",
            "displayName": "Alex W.",
            "mobilePhone": "+1 425 555 0110",
            "companyName": "Contoso",
            "jobTitle": "Marketing Manager",
        }

    async def test_it_reads_the_addresses_before_it_writes_the_merged_list(
        self, client: GraphServiceClient, read: respx.Route, write: respx.Route
    ) -> None:
        _ = await _changed(client, ContactChange(add_email_addresses=("alex@fabrikam.invalid",)))

        assert read.call_count == 1
        assert _sent(write) == {
            "emailAddresses": [
                {"name": "Alex Wilber", "address": "alexw@example.invalid"},
                {"name": "Alex Wilber", "address": "alex.wilber@example.invalid"},
                {"address": "alex@fabrikam.invalid"},
            ]
        }

    async def test_the_read_asks_only_for_the_lists_in_the_immutable_id_space(
        self, client: GraphServiceClient, read: respx.Route, write: respx.Route
    ) -> None:
        _ = write

        _ = await _changed(client, ContactChange(remove_home_phones=("+1 425 555 0111",)))

        request = read.calls.last.request
        assert request.url.params["$select"] == "emailAddresses,businessPhones,homePhones"
        assert 'IdType="ImmutableId"' in request.headers["prefer"]

    async def test_the_write_declares_the_immutable_id_space(
        self, client: GraphServiceClient, write: respx.Route
    ) -> None:
        _ = await _changed(client, ContactChange(job_title="Director"))

        assert 'IdType="ImmutableId"' in write.calls.last.request.headers["prefer"]

    @pytest.mark.parametrize(
        ("add", "remove", "written"),
        [
            pytest.param(
                ("ALEXW@example.invalid",),
                (),
                ["alexw@example.invalid", "alex.wilber@example.invalid"],
                id="an-address-it-holds-in-another-case-is-not-added-again",
            ),
            pytest.param(
                (),
                ("Alex.Wilber@Example.Invalid",),
                ["alexw@example.invalid"],
                id="a-removal-ignores-case",
            ),
            pytest.param(
                (),
                ("nobody@example.invalid",),
                ["alexw@example.invalid", "alex.wilber@example.invalid"],
                id="an-address-it-does-not-hold-changes-nothing",
            ),
            pytest.param(
                (" new@example.invalid ",),
                (" ALEXW@example.invalid\t",),
                ["alex.wilber@example.invalid", "new@example.invalid"],
                id="an-address-with-spaces-around-it-is-trimmed-before-the-match",
            ),
        ],
    )
    async def test_the_merged_addresses_keep_the_others_and_ignore_case(
        self,
        client: GraphServiceClient,
        read: respx.Route,
        write: respx.Route,
        add: tuple[str, ...],
        remove: tuple[str, ...],
        written: list[str],
    ) -> None:
        _ = read

        _ = await _changed(
            client, ContactChange(add_email_addresses=add, remove_email_addresses=remove)
        )

        sent = cast("list[dict[str, str]]", _sent(write)["emailAddresses"])
        assert [entry["address"] for entry in sent] == written

    async def test_a_kept_address_carries_only_the_name_and_the_address_back(
        self, client: GraphServiceClient, read: respx.Route, write: respx.Route
    ) -> None:
        _ = read

        _ = await _changed(client, ContactChange(add_email_addresses=("new@example.invalid",)))

        sent = cast("list[dict[str, str]]", _sent(write)["emailAddresses"])
        assert all(set(entry) <= {"name", "address"} for entry in sent), sent

    async def test_the_merged_numbers_keep_the_others_and_match_exactly(
        self, client: GraphServiceClient, read: respx.Route, write: respx.Route
    ) -> None:
        _ = read

        _ = await _changed(
            client,
            ContactChange(
                add_business_phones=("+1 425 555 0109", "+41 44 555 0100"),
                remove_home_phones=("+14255550111",),
            ),
        )

        assert _sent(write) == {
            "businessPhones": ["+1 425 555 0109", "+41 44 555 0100"],
            "homePhones": ["+1 425 555 0111"],
        }

    async def test_removing_the_last_number_writes_an_empty_list(
        self, client: GraphServiceClient, read: respx.Route, write: respx.Route
    ) -> None:
        _ = read

        _ = await _changed(client, ContactChange(remove_business_phones=("+1 425 555 0109",)))

        assert _sent(write) == {"businessPhones": []}

    async def test_a_contact_that_holds_no_list_gets_the_added_entries(
        self, client: GraphServiceClient, graph: respx.MockRouter, write: respx.Route
    ) -> None:
        _ = graph.get(_PATH).mock(return_value=httpx.Response(200, json={"id": _CONTACT_ID}))

        _ = await _changed(client, ContactChange(add_home_phones=("+1 425 555 0111",)))

        assert _sent(write) == {"homePhones": ["+1 425 555 0111"]}

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_write_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, write: respx.Route
    ) -> None:
        write.mock(return_value=httpx.Response(503))

        with pytest.raises(GraphFailure):
            _ = await _changed(client, ContactChange(job_title="Director"))

        assert write.call_count == 1, "no_retry means one attempt, however Graph answers"


class TestWhatItAnswers:
    async def test_the_answer_is_the_contact_that_graph_answered_with(
        self, client: GraphServiceClient, write: respx.Route
    ) -> None:
        write.mock(
            return_value=httpx.Response(
                200, json=_updated(jobTitle="Director", businessPhones=["+1 425 555 0109"])
            )
        )

        answer = await updater.update_contact(
            client, uri=_CONTACT_URI, change=ContactChange(job_title="Ignored by the answer")
        )

        assert contact_handle(answer.uri) == ContactHandle(_CONTACT_ID)
        assert answer.job_title == "Director"
        assert answer.business_phones == ["+1 425 555 0109"]


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "uri",
        [
            MailMessageHandle(_CONTACT_ID).uri,
            CalendarHandle(_CONTACT_ID).uri,
            "outlook:///contacts/",
            _CONTACT_ID,
            "alexw@example.invalid",
            "Alex Wilber",
        ],
    )
    async def test_a_value_that_is_not_a_contact_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, uri: str
    ) -> None:
        with pytest.raises(ToolError, match="takes the `uri` of a contact") as refused:
            _ = await updater.update_contact(
                client, uri=uri, change=ContactChange(job_title="Director")
            )

        assert len(graph.calls) == 0
        assert "outlook_list_contacts" in str(refused.value)
        assert "Nothing was changed." in str(refused.value)
        assert _RETRY in str(refused.value)

    async def test_a_call_with_nothing_to_change_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="nothing to change") as refused:
            _ = await _changed(client, ContactChange())

        assert len(graph.calls) == 0
        assert "Nothing was changed." in str(refused.value)

    @pytest.mark.parametrize(
        "change",
        [
            pytest.param(ContactChange(add_email_addresses=("Alex Wilber",)), id="add"),
            pytest.param(ContactChange(remove_email_addresses=("alexw@",)), id="remove"),
        ],
    )
    async def test_a_value_that_is_not_one_address_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, change: ContactChange
    ) -> None:
        with pytest.raises(ToolError, match="must be one SMTP address") as refused:
            _ = await _changed(client, change)

        assert len(graph.calls) == 0
        assert "Nothing was changed." in str(refused.value)
        assert str(refused.value).endswith(_RETRY)

    @pytest.mark.parametrize(
        ("change", "named"),
        [
            pytest.param(
                ContactChange(add_email_addresses=("new@example.invalid", "NEW@example.invalid")),
                "NEW@example.invalid",
                id="add",
            ),
            pytest.param(
                ContactChange(
                    remove_email_addresses=("alexw@example.invalid", " alexw@example.invalid ")
                ),
                "alexw@example.invalid",
                id="remove-with-spaces",
            ),
        ],
    )
    async def test_an_address_given_twice_in_one_list_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, change: ContactChange, named: str
    ) -> None:
        with pytest.raises(ToolError, match="in one list twice") as refused:
            _ = await _changed(client, change)

        assert len(graph.calls) == 0
        assert repr(named) in str(refused.value)
        assert "A change of case does not make a second address." in str(refused.value)
        assert "Nothing was changed." in str(refused.value)
        assert str(refused.value).endswith(_RETRY)

    @pytest.mark.parametrize(
        ("change", "named"),
        [
            pytest.param(
                ContactChange(
                    add_email_addresses=("new@example.invalid",),
                    remove_email_addresses=("NEW@example.invalid",),
                ),
                "`add_email_addresses` and `remove_email_addresses`",
                id="address",
            ),
            pytest.param(
                ContactChange(
                    add_business_phones=("+1 425 555 0109",),
                    remove_business_phones=("+1 425 555 0109",),
                ),
                "`add_business_phones` and `remove_business_phones`",
                id="business-phone",
            ),
            pytest.param(
                ContactChange(
                    add_home_phones=("+1 425 555 0111",), remove_home_phones=("+1 425 555 0111",)
                ),
                "`add_home_phones` and `remove_home_phones`",
                id="home-phone",
            ),
        ],
    )
    async def test_a_value_in_both_lists_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, change: ContactChange, named: str
    ) -> None:
        with pytest.raises(ToolError, match="is in both") as refused:
            _ = await _changed(client, change)

        assert len(graph.calls) == 0
        assert named in str(refused.value)
        assert _RETRY in str(refused.value)

    @pytest.mark.parametrize("blank", ["", "   "], ids=["empty", "spaces"])
    @pytest.mark.parametrize(
        "argument",
        ["add_business_phones", "remove_business_phones", "add_home_phones", "remove_home_phones"],
    )
    async def test_a_blank_telephone_number_never_reaches_this_tool(
        self, transport: httpx.AsyncClient, graph: respx.MockRouter, argument: str, blank: str
    ) -> None:
        tool = await _registered(transport)

        with pytest.raises(ValidationError):
            _ = await tool.run({**updater.GRAPH_CALL_EXAMPLE, argument: [blank]})

        assert len(graph.calls) == 0

    @pytest.mark.parametrize("blank", ["", "   ", "\t\n"], ids=["empty", "spaces", "tab_newline"])
    @pytest.mark.parametrize("argument", _TEXT_ARGUMENTS)
    async def test_a_blank_text_value_never_reaches_this_tool(
        self, transport: httpx.AsyncClient, graph: respx.MockRouter, argument: str, blank: str
    ) -> None:
        tool = await _registered(transport)

        with pytest.raises(ValidationError):
            _ = await tool.run({**updater.GRAPH_CALL_EXAMPLE, argument: blank})

        assert len(graph.calls) == 0

    async def test_a_contact_graph_will_not_return_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "ErrorItemNotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _changed(client, ContactChange(add_email_addresses=("a@example.invalid",)))

    async def test_a_refused_write_is_a_forbidden(
        self, client: GraphServiceClient, write: respx.Route
    ) -> None:
        write.mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _changed(client, ContactChange(job_title="Director"))


class TestHowItDeclaresItself:
    def test_the_permission_is_the_least_privileged_one_microsoft_names(self) -> None:
        assert updater.GRAPH_PERMISSIONS == ("Contacts.ReadWrite",)

    def test_a_safe_repeat_declares_no_tool_to_look_before_a_repeat(self) -> None:
        assert not hasattr(updater, "CHANGE_SHOWN_BY")

    def test_the_example_call_is_a_contact_handle_this_tool_accepts(self) -> None:
        assert contact_handle(cast("str", updater.GRAPH_CALL_EXAMPLE["uri"])) is not None

    def test_a_404_says_the_handle_is_well_formed_and_sends_the_caller_back_to_the_list(
        self,
    ) -> None:
        assert "nothing was changed" in updater.GRAPH_NOT_FOUND
        assert "The handle is well formed" in updater.GRAPH_NOT_FOUND
        assert "Find the contact again with outlook_list_contacts." in updater.GRAPH_NOT_FOUND
        assert _RETRY in updater.GRAPH_NOT_FOUND

    async def test_it_announces_itself_as_a_write_that_removes_values_and_is_safe_to_repeat(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["idempotentHint"]
        assert tool.title == "Update a Contact"

    async def test_only_the_handle_is_required_and_there_is_no_mailbox(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        properties = cast("Mapping[str, object]", tool.parameters["properties"])
        assert tool.parameters["required"] == ["uri"]
        assert "mailbox" not in properties
        assert set(updater.GRAPH_CALL_EXAMPLE) <= set(properties)

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

    async def test_the_description_says_it_never_asks_to_agree_and_is_safe_to_repeat(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = tool.description or ""
        assert "changes only the fields that the call gives" in description
        assert "There is no draft and no review step." in description
        assert "own mailbox alone, so this tool never asks anybody to agree" in description
        assert "This call is safe to repeat after a timeout." in description
        assert "Every address must come from the user." in description

    async def test_the_description_says_that_it_cannot_clear_a_field(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = tool.description or ""
        clearable = "a name, the company, the job title, or the mobile number"
        assert f"This tool cannot clear {clearable}." in description
        assert "Tell the user to clear the value in Outlook." in description

    async def test_the_handle_argument_names_its_one_shape_and_its_minters(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        described = _described(tool, "uri")
        assert "outlook:///contacts/{contact_id}" in described
        for minter in ("outlook_list_contacts", "outlook_read_contact", "outlook_create_contact"):
            assert minter in described

    @pytest.mark.parametrize(
        "argument",
        ["add_business_phones", "remove_business_phones", "add_home_phones", "remove_home_phones"],
    )
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

    @pytest.mark.parametrize(
        "argument", ["add_email_addresses", "add_business_phones", "add_home_phones"]
    )
    async def test_an_added_list_says_that_it_reads_merges_and_writes_the_whole_list(
        self, transport: httpx.AsyncClient, argument: str
    ) -> None:
        tool = await _registered(transport)

        described = _described(tool, argument)
        assert "Microsoft 365 replaces the whole list on a change" in described
        assert "writes the list back" in described
        assert "It keeps the other" in described

    async def test_the_display_name_says_that_microsoft_can_write_a_new_one(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        described = _described(tool, "display_name")
        assert "Microsoft 365 can write a new display name" in described

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
