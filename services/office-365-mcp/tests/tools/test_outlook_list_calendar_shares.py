import json
import re
from collections.abc import Mapping
from typing import cast
from urllib.parse import quote

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared.handles import (
    CalendarHandle,
    CalendarPermissionHandle,
    EventHandle,
    calendar_handle,
    calendar_permission_handle,
)
from office_365_mcp.shared.seam import READ_ONLY
from office_365_mcp.tools import PRESETS, TOOL_NAMES
from office_365_mcp.tools import outlook_list_calendar_shares as lister

from .conftest import GRAPH_V1

_CALENDAR_ID = "AAMkSYNTHETIC-cal-0002="

_URI = CalendarHandle(_CALENDAR_ID).uri

_PERMISSIONS_PATH = f"/me/calendars/{quote(_CALENDAR_ID, safe='')}/calendarPermissions"

_DANA_SHARE = "RXhjaGFuZ2VQdWJsaXNoZWRVc2VyLmRhbmE="
_ORGANIZATION_SHARE = "RGVmYXVsdA=="


def _share(
    *,
    share_id: str = _DANA_SHARE,
    name: str | None = "Dana Swope",
    address: str | None = "dana@example.invalid",
    role: str | None = "read",
    allowed: list[str] | None = None,
    inside: bool | None = True,
    removable: bool | None = True,
) -> dict[str, object]:
    person: dict[str, object] = {}
    if name is not None:
        person["name"] = name
    if address is not None:
        person["address"] = address
    return {
        "id": share_id,
        "isRemovable": removable,
        "isInsideOrganization": inside,
        "role": role,
        "allowedRoles": ["freeBusyRead", "limitedRead", "read", "write"]
        if allowed is None
        else allowed,
        "emailAddress": person,
    }


def _organization() -> dict[str, object]:
    return _share(
        share_id=_ORGANIZATION_SHARE,
        name="My Organization",
        address=None,
        role="freeBusyRead",
        allowed=["none", "freeBusyRead", "limitedRead", "read", "write"],
        removable=False,
    )


def _page(*shares: dict[str, object], next_link: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"value": list(shares)}
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


def _unguarded(tool: Tool) -> list[str]:
    schemas = json.dumps([tool.parameters, tool.output_schema], ensure_ascii=False)
    prose = [tool.description or "", *re.findall(r'"description": "((?:[^"\\]|\\.)*)"', schemas)]
    held = frozenset(TOOL_NAMES).intersection(
        *(names for names in PRESETS.values() if tool.name in names)
    )
    mention = re.compile(rf"\b(?:{'|'.join(TOOL_NAMES)})\b")
    offenders: list[str] = []
    for sentence in (s for text in prose for s in re.split(r"(?<=[.!?])\s+|\n\s*-\s+", text)):
        outside = set(mention.findall(sentence)) - held
        guard = sentence.split(",", 1)[0]
        if outside and not (
            guard.startswith("If this deployment exposes ")
            and outside <= set(mention.findall(guard))
        ):
            offenders.append(sentence)
    return offenders


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    lister.register(mcp, transport)
    tool = await mcp.get_tool(lister.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


@pytest.fixture
def shares(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_PERMISSIONS_PATH)


class TestTheRequestItMakes:
    async def test_it_reads_the_permissions_of_the_calendar_the_handle_names(
        self, client: GraphServiceClient, graph: respx.MockRouter, shares: respx.Route
    ) -> None:
        shares.mock(return_value=_page(_share()))

        _ = await lister.list_calendar_shares(client, calendar_ref=_URI)

        assert shares.call_count == 1
        assert len(graph.calls) == 1
        assert shares.calls.last.request.url.path == (
            f"/v1.0/me/calendars/{_CALENDAR_ID}/calendarPermissions"
        )

    async def test_it_sends_no_query_option(
        self, client: GraphServiceClient, shares: respx.Route
    ) -> None:
        shares.mock(return_value=_page(_share()))

        _ = await lister.list_calendar_shares(client, calendar_ref=_URI)

        assert dict(shares.calls.last.request.url.params) == {}


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "value",
        [
            EventHandle(_CALENDAR_ID, "AAMkSYNTHETIC-event-0001=").uri,
            CalendarPermissionHandle(_CALENDAR_ID, _DANA_SHARE).uri,
            "Project Apollo",
            _CALENDAR_ID,
            "outlook:///calendars/%20",
        ],
    )
    async def test_a_value_that_is_not_a_calendar_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError, match="outlook_list_calendars") as raised:
            _ = await lister.list_calendar_shares(client, calendar_ref=value)

        assert "This tool read nothing." in str(raised.value)
        assert len(graph.calls) == 0


class TestWhatItAnswers:
    async def test_a_row_carries_the_person_the_role_and_what_microsoft_allows(
        self, client: GraphServiceClient, shares: respx.Route
    ) -> None:
        shares.mock(return_value=_page(_share(allowed=["freeBusyRead", "limitedRead", "read"])))

        row = (await lister.list_calendar_shares(client, calendar_ref=_URI)).shares[0]

        assert row.name == "Dana Swope"
        assert row.address == "dana@example.invalid"
        assert row.role == "read"
        assert row.allowed_roles == ["freeBusyRead", "limitedRead", "read"]
        assert row.is_inside_organization is True
        assert row.is_removable is True

    async def test_a_row_is_a_share_handle_on_the_same_calendar(
        self, client: GraphServiceClient, shares: respx.Route
    ) -> None:
        shares.mock(return_value=_page(_share()))

        row = (await lister.list_calendar_shares(client, calendar_ref=_URI)).shares[0]

        assert calendar_permission_handle(row.uri) == CalendarPermissionHandle(
            _CALENDAR_ID, _DANA_SHARE
        )

    async def test_the_organization_row_has_no_address_and_is_not_removable(
        self, client: GraphServiceClient, shares: respx.Route
    ) -> None:
        shares.mock(return_value=_page(_share(), _organization()))

        listed = await lister.list_calendar_shares(client, calendar_ref=_URI)

        organization = listed.shares[1]
        assert organization.name == "My Organization"
        assert organization.address is None
        assert organization.role == "freeBusyRead"
        assert organization.is_removable is False
        assert "none" in organization.allowed_roles

    async def test_a_delegate_row_keeps_the_role_microsoft_names(
        self, client: GraphServiceClient, shares: respx.Route
    ) -> None:
        shares.mock(return_value=_page(_share(role="delegateWithPrivateEventAccess")))

        row = (await lister.list_calendar_shares(client, calendar_ref=_URI)).shares[0]

        assert row.role == "delegateWithPrivateEventAccess"

    async def test_a_role_name_this_connector_does_not_know_is_left_out_of_the_row(
        self, client: GraphServiceClient, shares: respx.Route
    ) -> None:
        shares.mock(
            return_value=_page(_share(role="synthesizedRole", allowed=["read", "synthesizedRole"]))
        )

        row = (await lister.list_calendar_shares(client, calendar_ref=_URI)).shares[0]

        assert row.role is None
        assert row.allowed_roles == ["read"]

    async def test_a_row_with_nothing_but_an_id_answers_nulls(
        self, client: GraphServiceClient, shares: respx.Route
    ) -> None:
        shares.mock(return_value=_page({"id": _DANA_SHARE}))

        row = (await lister.list_calendar_shares(client, calendar_ref=_URI)).shares[0]

        assert row.name is None
        assert row.address is None
        assert row.role is None
        assert row.allowed_roles == []
        assert row.is_inside_organization is None
        assert row.is_removable is None

    async def test_the_pages_of_the_listing_are_followed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_PERMISSIONS_PATH, params={"$skiptoken": "second"}).mock(
            return_value=_page(_organization())
        )
        graph.get(_PERMISSIONS_PATH).mock(
            return_value=_page(
                _share(), next_link=f"{GRAPH_V1}{_PERMISSIONS_PATH}?$skiptoken=second"
            )
        )

        listed = await lister.list_calendar_shares(client, calendar_ref=_URI)

        assert [row.name for row in listed.shares] == ["Dana Swope", "My Organization"]
        assert listed.capped is False

    async def test_a_scan_limit_that_left_more_shares_on_offer_says_capped(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(lister, "MAX_SCANNED_ITEMS", 1)
        graph.get(_PERMISSIONS_PATH, params={"$skiptoken": "second"}).mock(
            return_value=_page(_organization())
        )
        graph.get(_PERMISSIONS_PATH).mock(
            return_value=_page(
                _share(), next_link=f"{GRAPH_V1}{_PERMISSIONS_PATH}?$skiptoken=second"
            )
        )

        listed = await lister.list_calendar_shares(client, calendar_ref=_URI)

        assert [row.name for row in listed.shares] == ["Dana Swope"]
        assert listed.capped is True

    async def test_a_calendar_with_no_share_answers_an_empty_listing(
        self, client: GraphServiceClient, shares: respx.Route
    ) -> None:
        shares.mock(return_value=_page())

        listed = await lister.list_calendar_shares(client, calendar_ref=_URI)

        assert listed.shares == []
        assert listed.capped is False


class TestGraphFailures:
    async def test_a_refused_listing_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, shares: respx.Route
    ) -> None:
        shares.mock(return_value=httpx.Response(403))

        with pytest.raises(GraphForbidden):
            _ = await lister.list_calendar_shares(client, calendar_ref=_URI)

    async def test_a_calendar_graph_does_not_return_is_a_not_found(
        self, client: GraphServiceClient, shares: respx.Route
    ) -> None:
        shares.mock(return_value=httpx.Response(404))

        with pytest.raises(GraphNotFound):
            _ = await lister.list_calendar_shares(client, calendar_ref=_URI)

    async def test_the_call_example_reaches_graph_on_the_calendar_it_names(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        example = cast("Mapping[str, str]", lister.GRAPH_CALL_EXAMPLE)
        handle = calendar_handle(example["calendar_ref"])
        assert handle is not None, "GRAPH_CALL_EXAMPLE's own value is not a calendar handle"
        refused = graph.get(
            f"/me/calendars/{quote(handle.calendar_id, safe='')}/calendarPermissions"
        ).mock(return_value=httpx.Response(403))

        with pytest.raises(GraphForbidden):
            _ = await lister.list_calendar_shares(client, calendar_ref=example["calendar_ref"])

        assert refused.call_count == 1

    def test_the_not_found_advice_points_at_the_calendar_lister(self) -> None:
        assert "outlook_list_calendars" in lister.GRAPH_NOT_FOUND
        assert "this tool listed no share" in lister.GRAPH_NOT_FOUND


class TestHowItDeclaresItself:
    def test_the_permission_is_the_least_privileged_one_microsoft_names(self) -> None:
        assert lister.GRAPH_PERMISSIONS == ("Calendars.ReadBasic",)

    def test_the_call_example_is_a_calendar_handle_and_nothing_else(self) -> None:
        assert set(lister.GRAPH_CALL_EXAMPLE) == {"calendar_ref"}

    async def test_it_takes_one_calendar_handle_that_cannot_be_empty(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, object]]", parameters["properties"])
        assert set(properties) == {"calendar_ref"}
        assert parameters["required"] == ["calendar_ref"]
        assert properties["calendar_ref"]["minLength"] == 1

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

    async def test_the_description_names_the_sibling_tools_and_the_owner_rule(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "outlook_list_calendars lists the calendars and their handles" in description
        assert (
            "If this deployment exposes outlook_share_calendar, that tool shares a calendar with "
            "a person."
        ) in description
        assert (
            "If this deployment exposes outlook_unshare_calendar, that tool stops a share."
        ) in description
        assert "Microsoft lists the shares only for a calendar that the signed-in user owns" in (
            description
        )
        assert "`My Organization`" in description
        assert "A delegate also receives meeting requests for the owner" in description

    async def test_a_row_says_which_tool_takes_its_handle(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        answer = cast(
            "Mapping[str, Mapping[str, Mapping[str, Mapping[str, Mapping[str, str]]]]]",
            tool.output_schema,
        )
        described = answer["$defs"]["CalendarShare"]["properties"]["uri"]["description"]
        assert (
            "If this deployment exposes outlook_unshare_calendar, pass it as `share_ref` to that "
            "tool to stop the share."
        ) in described

    async def test_a_row_says_what_a_false_removable_flag_means_for_the_unshare_tool(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        answer = cast(
            "Mapping[str, Mapping[str, Mapping[str, Mapping[str, Mapping[str, str]]]]]",
            tool.output_schema,
        )
        described = answer["$defs"]["CalendarShare"]["properties"]["is_removable"]["description"]
        assert "True when Microsoft lets anybody remove this share." in described
        assert "False when Microsoft does not let anybody remove this row." in described
        assert (
            "If this deployment exposes outlook_unshare_calendar, that tool refuses a share that "
            "has the value false."
        ) in described

    async def test_every_other_tool_it_names_comes_after_a_guard_that_names_it(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        assert _unguarded(tool) == []

    async def test_every_field_of_the_answer_says_what_it_is(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        answer = cast("Mapping[str, object]", tool.output_schema)
        assert _undescribed(answer) == []
