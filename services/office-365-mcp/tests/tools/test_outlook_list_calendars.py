"""`outlook_list_calendars`: what it asks Graph for, whose calendar each row is, what it answers.

Every response body here is synthesised. No calendar, name or address came from a real mailbox.
"""

from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden
from office_365_mcp.shared.handles import CalendarHandle
from office_365_mcp.tools import outlook_list_calendars as lister

from .conftest import GRAPH_V1, ME

_CALENDARS = "/me/calendars"

_OWN_ID = "AAMkAGI2SYNTHETIC-cal-0001="
_DELEGATED_ID = "AAMkADRpSYNTHETIC-cal-0002="
_TEAM_ID = "AAMkADRpSYNTHETIC-cal-0003="

# Microsoft's own delegated-calendar walkthrough names the row after the delegator and reports
# `canShare` false, `canViewPrivateItems` false and `canEdit` true on it.
_DELEGATOR = {"name": "Alex Wilber", "address": "alexw@example.invalid"}

# `mail` on the signed-in user of `tests/tools/conftest.py`.
_OWN_OWNER = {"name": "Ada Lovelace", "address": "ada@example.invalid"}

# `userPrincipalName` on the same user, in a case Exchange did not use. A calendar owner is stated
# with one address or the other, so a comparison on `mail` alone reports this row as another
# person's.
_OWN_OWNER_BY_SIGN_IN_NAME = {"name": "Ada Lovelace", "address": "ADA@CORP.EXAMPLE.INVALID"}


def _calendar_payload(
    calendar_id: str,
    *,
    name: str | None = "Calendar",
    owner: Mapping[str, object] | None = None,
    can_edit: bool | None = True,
    can_share: bool | None = True,
    can_view_private_items: bool | None = True,
    is_default: bool | None = True,
    tallies_responses: bool | None = True,
    providers: Sequence[str] | None = ("teamsForBusiness",),
    default_provider: str | None = "teamsForBusiness",
) -> dict[str, object]:
    return {
        "id": calendar_id,
        "name": name,
        "owner": dict(owner) if owner is not None else None,
        "canEdit": can_edit,
        "canShare": can_share,
        "canViewPrivateItems": can_view_private_items,
        "isDefaultCalendar": is_default,
        "isTallyingResponses": tallies_responses,
        "allowedOnlineMeetingProviders": None if providers is None else list(providers),
        "defaultOnlineMeetingProvider": default_provider,
    }


def _own() -> dict[str, object]:
    return _calendar_payload(_OWN_ID, owner=_OWN_OWNER)


def _delegated() -> dict[str, object]:
    return _calendar_payload(
        _DELEGATED_ID,
        name="Alex Wilber",
        owner=_DELEGATOR,
        can_edit=True,
        can_share=False,
        can_view_private_items=False,
        is_default=False,
    )


def _page(*calendars: dict[str, object], next_link: str | None = None) -> httpx.Response:
    body: dict[str, object] = {"value": list(calendars)}
    if next_link is not None:
        body["@odata.nextLink"] = next_link
    return httpx.Response(200, json=body)


def _fields(node: object, at: str, *, root: Mapping[str, object]) -> dict[str, object]:
    """Every field of a published schema, at every depth.

    Pydantic publishes a nested model as a `$ref` into the schema's own `$defs` rather than
    inline, so a walk that does not follow one checks the top level and calls it the whole answer.
    """
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
def signed_in(graph: respx.MockRouter) -> respx.Route:
    return graph.get("/me").mock(return_value=httpx.Response(200, json=ME))


@pytest.fixture
def calendars(graph: respx.MockRouter) -> respx.Route:
    return graph.get(_CALENDARS)


class TestTheQueryItComposes:
    @pytest.mark.usefixtures("signed_in")
    async def test_it_asks_for_every_property_a_calendar_row_reports(
        self, client: GraphServiceClient, calendars: respx.Route
    ) -> None:
        """`owner` is load-bearing rather than decorative: it is the only property that separates a
        delegated calendar from the user's own."""
        calendars.mock(return_value=_page(_own()))

        _ = await lister.list_calendars(client)

        assert calendars.calls.last.request.url.params["$select"].split(",") == [
            "id",
            "name",
            "owner",
            "canEdit",
            "canShare",
            "canViewPrivateItems",
            "isDefaultCalendar",
            "isTallyingResponses",
            "allowedOnlineMeetingProviders",
            "defaultOnlineMeetingProvider",
        ]

    @pytest.mark.usefixtures("signed_in")
    async def test_the_window_is_asked_of_graph_rather_than_only_applied_here(
        self, client: GraphServiceClient, calendars: respx.Route
    ) -> None:
        calendars.mock(return_value=_page(_own()))

        _ = await lister.list_calendars(client)

        assert calendars.calls.last.request.url.params["$top"] == str(lister.MAX_CALENDARS)

    @pytest.mark.usefixtures("signed_in")
    async def test_it_asks_for_all_the_calendars_and_never_one_calendar_group(
        self, client: GraphServiceClient, calendars: respx.Route
    ) -> None:
        """The calendar-group routes split the same set by a folder the user arranged, so a filter
        or an ordering here answers a question this tool does not ask."""
        calendars.mock(return_value=_page(_own()))

        _ = await lister.list_calendars(client)

        params = calendars.calls.last.request.url.params
        assert "$filter" not in params
        assert "$orderby" not in params
        assert "$expand" not in params

    @pytest.mark.usefixtures("signed_in")
    async def test_no_preference_header_reaches_a_container_read(
        self, client: GraphServiceClient, calendars: respx.Route
    ) -> None:
        """Microsoft documents that container types such as `calendar` do not support the
        immutable-id preference, and no calendar time is rendered here, so `outlook.timezone` has
        nothing to render either."""
        calendars.mock(return_value=_page(_own()))

        _ = await lister.list_calendars(client)

        assert "Prefer" not in calendars.calls.last.request.headers

    async def test_each_of_the_two_reads_happens_exactly_once(
        self, client: GraphServiceClient, signed_in: respx.Route, calendars: respx.Route
    ) -> None:
        """One `/me` read serves every row: re-reading it per calendar turns an inventory into one
        request per calendar for an answer that never changes."""
        calendars.mock(return_value=_page(_own(), _delegated()))

        _ = await lister.list_calendars(client)

        assert signed_in.call_count == 1
        assert calendars.call_count == 1


class TestWhoseCalendarEachRowIs:
    @pytest.mark.usefixtures("signed_in")
    async def test_a_calendar_owned_at_the_users_mail_address_is_their_own(
        self, client: GraphServiceClient, calendars: respx.Route
    ) -> None:
        calendars.mock(return_value=_page(_own()))

        row = (await lister.list_calendars(client)).calendars[0]

        assert row.is_mine is True
        assert row.owner is not None
        assert row.owner.address == "ada@example.invalid"

    @pytest.mark.usefixtures("signed_in")
    async def test_a_calendar_owned_at_the_users_sign_in_name_is_their_own_too(
        self, client: GraphServiceClient, calendars: respx.Route
    ) -> None:
        """Graph gives a user both a `mail` and a `userPrincipalName` on different domains, and it
        states an owner with either one, in whatever case Exchange stored."""
        calendars.mock(
            return_value=_page(
                _calendar_payload(_TEAM_ID, name="Team", owner=_OWN_OWNER_BY_SIGN_IN_NAME)
            )
        )

        row = (await lister.list_calendars(client)).calendars[0]

        assert row.is_mine is True

    @pytest.mark.usefixtures("signed_in")
    async def test_a_delegated_calendar_is_named_after_its_owner_and_is_not_the_users_own(
        self, client: GraphServiceClient, calendars: respx.Route
    ) -> None:
        """Microsoft's walkthrough returns exactly this row to a delegate: named after the
        delegator, `canEdit` true, `canShare` and `canViewPrivateItems` false."""
        calendars.mock(return_value=_page(_own(), _delegated()))

        row = (await lister.list_calendars(client)).calendars[1]

        assert row.name == "Alex Wilber"
        assert row.is_mine is False
        assert row.can_edit is True
        assert row.can_view_private_items is False
        assert row.is_default is False

    @pytest.mark.usefixtures("signed_in")
    async def test_a_calendar_graph_named_no_owner_for_is_unknown_and_not_somebody_elses(
        self, client: GraphServiceClient, calendars: respx.Route
    ) -> None:
        """Null and false are different answers: null says the comparison had nothing to compare."""
        calendars.mock(return_value=_page(_calendar_payload(_TEAM_ID, name="Team", owner=None)))

        row = (await lister.list_calendars(client)).calendars[0]

        assert row.owner is None
        assert row.is_mine is None


class TestWhatItAnswers:
    @pytest.mark.usefixtures("signed_in")
    async def test_each_calendar_carries_the_handle_that_addresses_it(
        self, client: GraphServiceClient, calendars: respx.Route
    ) -> None:
        calendars.mock(return_value=_page(_own(), _delegated()))

        listed = await lister.list_calendars(client)

        assert [row.uri for row in listed.calendars] == [
            CalendarHandle(_OWN_ID).uri,
            CalendarHandle(_DELEGATED_ID).uri,
        ]

    @pytest.mark.usefixtures("signed_in")
    async def test_it_reports_what_the_user_can_do_on_the_calendar(
        self, client: GraphServiceClient, calendars: respx.Route
    ) -> None:
        calendars.mock(return_value=_page(_own()))

        row = (await lister.list_calendars(client)).calendars[0]

        assert row.name == "Calendar"
        assert row.can_edit is True
        assert row.can_view_private_items is True
        assert row.is_default is True
        assert row.tracks_responses is True
        assert row.online_meeting_providers == ["teamsForBusiness"]
        assert row.default_online_meeting_provider == "teamsForBusiness"

    @pytest.mark.usefixtures("signed_in")
    async def test_a_calendar_graph_reported_no_flags_for_is_still_listed(
        self, client: GraphServiceClient, calendars: respx.Route
    ) -> None:
        calendars.mock(
            return_value=_page(
                _calendar_payload(
                    _TEAM_ID,
                    name=None,
                    owner=_DELEGATOR,
                    can_edit=None,
                    can_share=None,
                    can_view_private_items=None,
                    is_default=None,
                    tallies_responses=None,
                    providers=None,
                    default_provider=None,
                )
            )
        )

        row = (await lister.list_calendars(client)).calendars[0]

        assert row.uri == CalendarHandle(_TEAM_ID).uri
        assert row.name is None
        assert row.can_edit is None
        assert row.can_view_private_items is None
        assert row.is_default is None
        assert row.tracks_responses is None
        assert row.online_meeting_providers == []
        assert row.default_online_meeting_provider is None

    @pytest.mark.usefixtures("signed_in")
    async def test_the_pages_of_the_listing_are_followed_rather_than_read_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The cursor route is registered before the bare one, which respx matches in registration
        order: the bare path matches a `$skiptoken` request too, and answers every page.
        """
        graph.get(_CALENDARS, params={"$skiptoken": "second"}).mock(
            return_value=_page(_delegated())
        )
        graph.get(_CALENDARS).mock(
            return_value=_page(_own(), next_link=f"{GRAPH_V1}{_CALENDARS}?$skiptoken=second")
        )

        listed = await lister.list_calendars(client)

        assert [row.name for row in listed.calendars] == ["Calendar", "Alex Wilber"]
        assert listed.capped is False, "the walk reached the end of the listing"

    @pytest.mark.usefixtures("signed_in")
    async def test_a_cap_that_left_more_calendars_on_offer_says_capped(
        self, client: GraphServiceClient, graph: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`capped` is the difference between "this mailbox has one calendar" and "this listing
        stopped at one". The cap is patched rather than answered with 201 synthetic calendars.
        """
        monkeypatch.setattr(lister, "MAX_CALENDARS", 1)
        graph.get(_CALENDARS, params={"$skiptoken": "second"}).mock(
            return_value=_page(_delegated())
        )
        graph.get(_CALENDARS).mock(
            return_value=_page(_own(), next_link=f"{GRAPH_V1}{_CALENDARS}?$skiptoken=second")
        )

        listed = await lister.list_calendars(client)

        assert [row.name for row in listed.calendars] == ["Calendar"]
        assert listed.capped is True

    @pytest.mark.usefixtures("signed_in")
    async def test_a_mailbox_graph_reported_no_calendar_for_answers_an_empty_listing(
        self, client: GraphServiceClient, calendars: respx.Route
    ) -> None:
        """An empty listing is an answer, not a failure. It does not happen for a licensed mailbox,
        and the field description says which permission explains it."""
        calendars.mock(return_value=_page())

        listed = await lister.list_calendars(client)

        assert listed.calendars == []
        assert listed.capped is False, "an empty listing is the whole of it, not a cap"


class TestTheSchemaItPublishes:
    async def test_it_publishes_no_arguments_at_all(self, transport: httpx.AsyncClient) -> None:
        """This is the one calendar tool a model reaches with nothing in hand. An argument here
        would be a handle no earlier call minted."""
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert tool.parameters.get("properties", {}) == {}
        assert tool.parameters.get("required", []) == []

    async def test_the_delegated_create_is_named_as_a_tool_this_deployment_might_not_run(
        self, transport: httpx.AsyncClient
    ) -> None:
        """Three presets register this tool and only the delegate one registers
        outlook_create_event_on_behalf, so a flat "this `uri` goes to that tool" sends a model to a
        tool that is not there. The mention stays conditional.
        """
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert "also runs outlook_create_event_on_behalf" in (tool.description or "")

    async def test_every_field_of_the_answer_says_what_it_is(
        self, transport: httpx.AsyncClient
    ) -> None:
        """Asserted over the published schema rather than the model classes: a description that
        never reaches the wire is not one."""
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        answer = cast("Mapping[str, object]", tool.output_schema)
        published = _fields(answer, lister.TOOL_NAME, root=answer)
        # Guards the guard: a walk that stopped descending passes by finding nothing to check.
        assert f"{lister.TOOL_NAME}.calendars[].owner.address" in published
        undescribed = sorted(
            path
            for path, field in published.items()
            if not cast("Mapping[str, object]", field).get("description")
        )
        assert undescribed == [], "a model is handed these values with nothing to say what they are"

    def test_the_call_that_proves_the_permissions_takes_no_arguments(self) -> None:
        """The startup probe calls this tool with the example verbatim. A tool with no arguments
        reaches Graph on the empty mapping, so the empty mapping is the whole example."""
        assert lister.GRAPH_CALL_EXAMPLE == {}


class TestGraphFailures:
    async def test_a_refused_identity_read_stops_before_the_calendars_are_asked_for(
        self, client: GraphServiceClient, graph: respx.MockRouter, calendars: respx.Route
    ) -> None:
        """Without the signed-in user no row answers `is_mine`, which is the question this tool
        exists for, so the second request is not worth making."""
        graph.get("/me").mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Authorization_RequestDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await lister.list_calendars(client)

        assert calendars.call_count == 0

    @pytest.mark.usefixtures("signed_in")
    async def test_a_refused_listing_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, calendars: respx.Route
    ) -> None:
        calendars.mock(return_value=httpx.Response(403))

        with pytest.raises(GraphForbidden):
            _ = await lister.list_calendars(client)

    def test_the_permissions_are_the_ones_microsoft_documents(self) -> None:
        """Microsoft names `Calendars.Read.Shared` as the least privileged permission for reading a
        delegated calendar, and `User.Read` covers the `/me` read `is_mine` is decided against."""
        assert lister.GRAPH_PERMISSIONS == (
            "Calendars.Read",
            "Calendars.Read.Shared",
            "User.Read",
        )
