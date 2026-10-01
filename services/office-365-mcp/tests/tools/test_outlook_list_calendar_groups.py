from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden
from office_365_mcp.shared.calendar import CalendarSummary
from office_365_mcp.shared.handles import CalendarHandle
from office_365_mcp.tools import outlook_list_calendar_groups as lister

from .conftest import GRAPH_V1

_GROUPS = "/me/calendarGroups"

_MINE_ID = "AAMkGROUPSYNTHETIC-mine-0001="
_OTHER_ID = "AAMkGROUPSYNTHETIC-other-0002="
_MINE_CLASS_ID = "0006f0b7-0000-0000-c000-000000000046"
_OTHER_CLASS_ID = "0006f0b8-0000-0000-c000-000000000046"
_OWNER = {"name": "Ada Lovelace", "address": "ada@example.invalid"}

_OWN_CALENDAR_ID = "AAMkCALSYNTHETIC-own-0001="
_TEAM_CALENDAR_ID = "AAMkCALSYNTHETIC-team-0002="
_SHARED_CALENDAR_ID = "AAMkCALSYNTHETIC-shared-0003="


def _calendars_of(group_id: str) -> str:
    return f"{_GROUPS}/{group_id.replace('=', '%3D')}/calendars"


def _group_payload(
    group_id: str,
    *,
    name: str | None = "My Calendars",
    class_id: str | None = _MINE_CLASS_ID,
) -> dict[str, object]:
    return {
        "id": group_id,
        "name": name,
        "classId": class_id,
        "changeKey": "NreqLYgxdE2DpHBBId74XwAAAAAGZw==",
    }


def _calendar_payload(calendar_id: str, *, name: str | None = "Calendar") -> dict[str, object]:
    return {
        "id": calendar_id,
        "name": name,
        "owner": _OWNER,
        "canEdit": True,
        "canViewPrivateItems": False,
        "isDefaultCalendar": False,
    }


def _page(*rows: dict[str, object], next_link: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"value": list(rows)}
    if next_link is not None:
        body["@odata.nextLink"] = next_link
    return httpx.Response(200, json=body)


def _fields(node: object, at: str, *, root: Mapping[str, object]) -> dict[str, object]:
    schema = _resolved(node, root=root)
    found: dict[str, object] = {}
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for name, field in cast("Mapping[str, object]", properties).items():
            found[f"{at}.{name}"] = field
            found |= _fields(field, f"{at}.{name}", root=root)
    items = schema.get("items")
    if items is not None:
        found |= _fields(items, f"{at}[]", root=root)
    branches = schema.get("anyOf")
    if isinstance(branches, list):
        for branch in cast("Sequence[object]", branches):
            found |= _fields(branch, at, root=root)
    return found


def _resolved(node: object, *, root: Mapping[str, object]) -> Mapping[str, object]:
    schema = cast("Mapping[str, object]", node)
    reference = schema.get("$ref")
    if not isinstance(reference, str):
        return schema
    definitions = cast("Mapping[str, object]", root.get("$defs", {}))
    return cast("Mapping[str, object]", definitions[reference.removeprefix("#/$defs/")])


@pytest.fixture
def groups(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_GROUPS).mock(
        return_value=_page(
            _group_payload(_MINE_ID),
            _group_payload(_OTHER_ID, name="Other calendars", class_id=_OTHER_CLASS_ID),
        )
    )


@pytest.fixture
def mine(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_calendars_of(_MINE_ID)).mock(
        return_value=_page(
            _calendar_payload(_OWN_CALENDAR_ID),
            _calendar_payload(_TEAM_CALENDAR_ID, name="Team"),
        )
    )


@pytest.fixture
def other(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_calendars_of(_OTHER_ID)).mock(
        return_value=_page(_calendar_payload(_SHARED_CALENDAR_ID, name="Alex Wilber"))
    )


class TestTheRequestsItSends:
    @pytest.mark.usefixtures("mine", "other")
    async def test_it_asks_for_the_groups_with_no_query_option_at_all(
        self, client: GraphServiceClient, groups: respx.Route
    ) -> None:
        _ = await lister.list_calendar_groups(client)

        request = groups.calls.last.request
        assert request.url.query == b""
        assert "Prefer" not in request.headers

    @pytest.mark.usefixtures("groups")
    async def test_it_asks_for_the_calendars_of_each_group_by_the_id_of_the_group(
        self, client: GraphServiceClient, mine: respx.Route, other: respx.Route
    ) -> None:
        _ = await lister.list_calendar_groups(client)

        assert mine.call_count == 1
        assert other.call_count == 1

    @pytest.mark.usefixtures("groups")
    async def test_the_calendar_reads_send_no_query_option_either(
        self, client: GraphServiceClient, mine: respx.Route, other: respx.Route
    ) -> None:
        _ = await lister.list_calendar_groups(client)

        assert mine.calls.last.request.url.query == b""
        assert other.calls.last.request.url.query == b""

    async def test_a_mailbox_with_no_group_asks_for_no_calendars(
        self, client: GraphServiceClient, groups: respx.Route, mine: respx.Route
    ) -> None:
        groups.mock(return_value=_page())

        answer = await lister.list_calendar_groups(client)

        assert answer.groups == []
        assert answer.capped is False
        assert mine.call_count == 0


class TestWhatItAnswers:
    @pytest.mark.usefixtures("groups", "mine", "other")
    async def test_each_group_carries_its_name_and_its_own_calendars(
        self, client: GraphServiceClient
    ) -> None:
        answer = await lister.list_calendar_groups(client)

        assert [group.name for group in answer.groups] == ["My Calendars", "Other calendars"]
        assert [calendar.name for calendar in answer.groups[0].calendars] == ["Calendar", "Team"]
        assert [calendar.name for calendar in answer.groups[1].calendars] == ["Alex Wilber"]

    @pytest.mark.usefixtures("groups", "mine", "other")
    async def test_each_calendar_carries_the_handle_that_addresses_it(
        self, client: GraphServiceClient
    ) -> None:
        answer = await lister.list_calendar_groups(client)

        assert [calendar.uri for calendar in answer.groups[0].calendars] == [
            CalendarHandle(_OWN_CALENDAR_ID).uri,
            CalendarHandle(_TEAM_CALENDAR_ID).uri,
        ]
        assert [calendar.uri for calendar in answer.groups[1].calendars] == [
            CalendarHandle(_SHARED_CALENDAR_ID).uri
        ]

    @pytest.mark.usefixtures("groups", "mine", "other")
    async def test_a_calendar_row_has_the_shape_that_outlook_list_calendars_answers(
        self, client: GraphServiceClient
    ) -> None:
        answer = await lister.list_calendar_groups(client)

        calendar = answer.groups[0].calendars[0]
        assert isinstance(calendar, CalendarSummary)
        assert calendar.owner is not None
        assert calendar.owner.address == "ada@example.invalid"
        assert calendar.can_edit is True
        assert calendar.can_view_private_items is False
        assert calendar.is_default is False

    @pytest.mark.usefixtures("groups", "mine", "other")
    async def test_is_mine_is_null_because_the_tool_does_not_read_the_user(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        me = graph.get("/me")

        answer = await lister.list_calendar_groups(client)

        assert [calendar.is_mine for group in answer.groups for calendar in group.calendars] == [
            None,
            None,
            None,
        ]
        assert me.call_count == 0

    @pytest.mark.usefixtures("groups", "mine", "other")
    async def test_a_group_row_holds_the_name_and_the_calendars_and_nothing_else(
        self, client: GraphServiceClient
    ) -> None:
        answer = await lister.list_calendar_groups(client)

        assert set(answer.groups[0].model_dump()) == {"name", "calendars"}

    @pytest.mark.usefixtures("other")
    async def test_a_group_graph_reported_no_name_for_is_still_listed(
        self, client: GraphServiceClient, groups: respx.Route, mine: respx.Route
    ) -> None:
        groups.mock(return_value=_page(_group_payload(_MINE_ID, name=None)))
        mine.mock(return_value=_page(_calendar_payload(_OWN_CALENDAR_ID, name=None)))

        group = (await lister.list_calendar_groups(client)).groups[0]

        assert group.name is None
        assert [calendar.name for calendar in group.calendars] == [None]
        assert [calendar.uri for calendar in group.calendars] == [
            CalendarHandle(_OWN_CALENDAR_ID).uri
        ]

    @pytest.mark.usefixtures("other")
    async def test_a_group_with_no_calendar_answers_an_empty_list(
        self, client: GraphServiceClient, groups: respx.Route, mine: respx.Route
    ) -> None:
        groups.mock(return_value=_page(_group_payload(_MINE_ID)))
        mine.mock(return_value=_page())

        answer = await lister.list_calendar_groups(client)

        assert answer.groups[0].calendars == []
        assert answer.capped is False

    @pytest.mark.usefixtures("mine", "other")
    async def test_the_pages_of_the_groups_are_followed_rather_than_read_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_GROUPS, params={"$skiptoken": "second"}).mock(
            return_value=_page(_group_payload(_OTHER_ID, name="Other calendars"))
        )
        graph.get(_GROUPS).mock(
            return_value=_page(
                _group_payload(_MINE_ID), next_link=f"{GRAPH_V1}{_GROUPS}?$skiptoken=second"
            )
        )

        answer = await lister.list_calendar_groups(client)

        assert [group.name for group in answer.groups] == ["My Calendars", "Other calendars"]
        assert answer.capped is False, "the walk reached the end of the groups"

    @pytest.mark.usefixtures("groups", "other")
    async def test_the_pages_of_a_groups_calendars_are_followed_rather_than_read_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        calendars = _calendars_of(_MINE_ID)
        graph.get(calendars, params={"$skiptoken": "second"}).mock(
            return_value=_page(_calendar_payload(_TEAM_CALENDAR_ID, name="Team"))
        )
        graph.get(calendars).mock(
            return_value=_page(
                _calendar_payload(_OWN_CALENDAR_ID),
                next_link=f"{GRAPH_V1}{calendars}?$skiptoken=second",
            )
        )

        answer = await lister.list_calendar_groups(client)

        assert [calendar.name for calendar in answer.groups[0].calendars] == ["Calendar", "Team"]
        assert answer.capped is False

    @pytest.mark.usefixtures("mine", "other")
    async def test_a_cap_that_left_more_groups_on_offer_says_capped(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(lister, "MAX_SCANNED_ITEMS", 1)
        graph.get(_GROUPS, params={"$skiptoken": "second"}).mock(
            return_value=_page(_group_payload(_OTHER_ID, name="Other calendars"))
        )
        graph.get(_GROUPS).mock(
            return_value=_page(
                _group_payload(_MINE_ID), next_link=f"{GRAPH_V1}{_GROUPS}?$skiptoken=second"
            )
        )

        answer = await lister.list_calendar_groups(client)

        assert [group.name for group in answer.groups] == ["My Calendars"]
        assert answer.capped is True

    @pytest.mark.usefixtures("groups", "other")
    async def test_a_cap_that_left_more_calendars_in_a_group_on_offer_says_capped(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(lister, "MAX_SCANNED_ITEMS", 2)
        calendars = _calendars_of(_MINE_ID)
        graph.get(calendars, params={"$skiptoken": "second"}).mock(
            return_value=_page(_calendar_payload(_SHARED_CALENDAR_ID, name="Shared"))
        )
        graph.get(calendars).mock(
            return_value=_page(
                _calendar_payload(_OWN_CALENDAR_ID),
                _calendar_payload(_TEAM_CALENDAR_ID, name="Team"),
                next_link=f"{GRAPH_V1}{calendars}?$skiptoken=second",
            )
        )

        answer = await lister.list_calendar_groups(client)

        assert [calendar.name for calendar in answer.groups[0].calendars] == ["Calendar", "Team"]
        assert answer.capped is True


class TestTheSchemaItPublishes:
    async def test_it_publishes_no_arguments_at_all(self, transport: httpx.AsyncClient) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert tool.parameters.get("properties", {}) == {}
        assert tool.parameters.get("required", []) == []

    async def test_the_tool_reads_and_changes_nothing(self, transport: httpx.AsyncClient) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True

    async def test_the_description_names_its_sibling_and_where_a_handle_goes(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        described = tool.description or ""
        assert "outlook_list_calendars" in described
        assert "`calendar_ref` to outlook_list_events" in described
        assert "`is_mine` is null in every row" in described

    async def test_every_field_of_the_answer_says_what_it_is(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        answer = cast("Mapping[str, object]", tool.output_schema)
        published = _fields(answer, lister.TOOL_NAME, root=answer)
        assert f"{lister.TOOL_NAME}.groups[].calendars[].uri" in published, (
            "the walk stopped before the nested rows"
        )
        undescribed = sorted(
            path
            for path, field in published.items()
            if not cast("Mapping[str, object]", field).get("description")
        )
        assert undescribed == [], "a model is handed these values with nothing to say what they are"

    def test_the_call_that_proves_the_permissions_takes_no_arguments(self) -> None:
        assert lister.GRAPH_CALL_EXAMPLE == {}


class TestGraphFailures:
    async def test_a_refused_group_listing_stops_before_any_calendar_is_asked_for(
        self, client: GraphServiceClient, groups: respx.Route, mine: respx.Route
    ) -> None:
        groups.mock(return_value=httpx.Response(403))

        with pytest.raises(GraphForbidden):
            _ = await lister.list_calendar_groups(client)

        assert mine.call_count == 0

    @pytest.mark.usefixtures("groups", "other")
    async def test_a_refused_calendar_listing_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, mine: respx.Route
    ) -> None:
        mine.mock(return_value=httpx.Response(403))

        with pytest.raises(GraphForbidden):
            _ = await lister.list_calendar_groups(client)

    def test_the_permission_is_the_one_microsoft_documents_as_least_privileged(self) -> None:
        assert lister.GRAPH_PERMISSIONS == ("Calendars.ReadBasic",)
