import json
from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import AcceptedElicitation, DeclinedElicitation
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools import Tool
from fastmcp.tools.base import ToolResult
from mcp.shared.exceptions import MCPError
from mcp.types import (
    METHOD_NOT_FOUND,
    CallToolRequestParams,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
    InputResponse,
)
from mcp.types.version import LATEST_MODERN_VERSION
from msgraph.graph_service_client import GraphServiceClient
from respx.models import Call

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound, GraphUnavailable
from office_365_mcp.shared.files import ITEM_HANDLE_SOURCES
from office_365_mcp.shared.handles import (
    DriveFileHandle,
    DriveFolderHandle,
    MailMessageHandle,
    OnenotePageHandle,
    drive_item_handle,
)
from office_365_mcp.shared.notes import write_state_for
from office_365_mcp.shared.prose import PREVIEW_CHARACTERS
from office_365_mcp.shared.seam import (
    WRITE_IDEMPOTENT,
    Confirm,
    Confirmed,
    GraphAdviceMiddleware,
    ToolAdvice,
)
from office_365_mcp.tools import sharepoint_create_share_link as sharer
from office_365_mcp.tools.sharepoint_create_share_link import (
    SharingLink,
    a_person_agrees,
    create_share_link,
)

_DRIVE_ID = "b!SYNTHETICDRIVE0000"
_ITEM_ID = "01SYNTHETICFILE0000"

_FILE = DriveFileHandle(_DRIVE_ID, _ITEM_ID).uri
_FOLDER = DriveFolderHandle(_DRIVE_ID, _ITEM_ID).uri

_ITEM_PATH = "/drives/b%21SYNTHETICDRIVE0000/items/01SYNTHETICFILE0000"
_LINK_PATH = f"{_ITEM_PATH}/createLink"

_NAME = "Quarterly-report.docx"
_LINK_URL = "https://contoso.sharepoint.invalid/:w:/s/finance/SYNTHETICLINK0000"

_NOTHING_CREATED = "No link was created, and nothing was shared."


def _item_payload(*, name: str | None = _NAME) -> dict[str, object]:
    return {
        "id": _ITEM_ID,
        "name": name,
        "file": {"mimeType": "application/octet-stream"},
        "parentReference": {"driveId": _DRIVE_ID},
    }


def _link_payload(
    *,
    link_type: str | None = "view",
    scope: str | None = "organization",
    web_url: str | None = _LINK_URL,
) -> dict[str, object]:
    return {
        "id": "SYNTHETICPERMISSION0000",
        "roles": ["read"],
        "link": {"type": link_type, "scope": scope, "webUrl": web_url},
    }


def _reads(graph: respx.MockRouter, payload: Mapping[str, object] | None = None) -> respx.Route:
    return graph.get(_ITEM_PATH).mock(
        return_value=httpx.Response(200, json=dict(payload or _item_payload()))
    )


def _links(
    graph: respx.MockRouter, payload: Mapping[str, object] | None = None, *, status: int = 201
) -> respx.Route:
    return graph.post(_LINK_PATH).mock(
        return_value=httpx.Response(status, json=dict(payload or _link_payload()))
    )


async def _agrees(question: str, about: str) -> Confirmed:
    assert question, "the person was asked nothing at all"
    assert about, "the answer was bound to nothing"
    return None


async def _refuses(question: str, about: str) -> Confirmed:
    assert question and about
    return _NOTHING_CREATED


async def _share(
    client: GraphServiceClient,
    *,
    item: str = _FILE,
    access: sharer.Access = "view",
    audience: sharer.Audience = "organization",
    confirm: Confirm = _agrees,
) -> SharingLink:
    answer = await create_share_link(
        client, item=item, access=access, audience=audience, confirm=confirm
    )
    assert isinstance(answer, SharingLink), "this call was answered with a question, not a link"
    return answer


def _asking(asked: list[str]) -> Confirm:
    async def capturing(question: str, about: str) -> Confirmed:
        assert about
        asked.append(question)
        return None

    return capturing


def _body(route: respx.Route) -> Mapping[str, object]:
    return cast("Mapping[str, object]", json.loads(route.calls.last.request.content))


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    sharer.register(mcp, transport)
    tool = await mcp.get_tool(sharer.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


def _properties(parameters: Mapping[str, object]) -> Mapping[str, Mapping[str, object]]:
    return cast("Mapping[str, Mapping[str, object]]", parameters["properties"])


def _choices(parameters: Mapping[str, object], name: str) -> object:
    reference = str(_properties(parameters)[name]["$ref"])
    definitions = cast("Mapping[str, Mapping[str, object]]", parameters["$defs"])
    return definitions[reference.removeprefix("#/$defs/")]["enum"]


class TestWhatItSendsToGraph:
    async def test_it_reads_the_item_then_asks_for_one_link_and_nothing_else(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        item_route = _reads(graph)
        link_route = _links(graph)

        _ = await _share(client)

        made = cast("Sequence[Call]", graph.calls)
        assert [call.request.method for call in made] == ["GET", "POST"]
        assert item_route.call_count == 1
        assert link_route.call_count == 1

    @pytest.mark.parametrize("access", ["view", "edit"])
    @pytest.mark.parametrize("audience", ["organization", "anonymous"])
    async def test_the_body_is_exactly_the_kind_and_the_audience(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        access: sharer.Access,
        audience: sharer.Audience,
    ) -> None:
        _ = _reads(graph)
        link_route = _links(graph, _link_payload(link_type=access, scope=audience))

        _ = await _share(client, access=access, audience=audience)

        assert _body(link_route) == {"type": access, "scope": audience}, (
            "the SDK sends retainInheritedPermissions false by default, and that removes every "
            + "inherited permission when an item is shared for the first time"
        )

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_link_request_graph_answers_503_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        link_route = graph.post(_LINK_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _share(client)

        assert link_route.call_count == 1


class TestWhatItAnswers:
    async def test_the_answer_carries_the_link_microsoft_made(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _links(graph)

        answer = await _share(client)

        assert answer == SharingLink(
            item_uri=_FILE, web_url=_LINK_URL, access="view", audience="organization"
        )

    async def test_a_200_that_returns_an_existing_link_maps_the_same_way_as_a_201(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        link_route = graph.post(_LINK_PATH).mock(
            side_effect=[
                httpx.Response(201, json=_link_payload()),
                httpx.Response(200, json=_link_payload()),
            ]
        )

        created = await _share(client)
        reused = await _share(client)

        assert link_route.call_count == 2
        assert reused == created

    async def test_the_kind_and_the_audience_come_from_the_answer_and_not_the_arguments(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _links(graph, _link_payload(link_type="edit", scope="organization"))

        answer = await _share(client, access="view", audience="anonymous")

        assert answer.access == "edit"
        assert answer.audience == "organization"

    async def test_a_folder_handle_is_answered_with_the_same_folder_handle(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _links(graph)

        answer = await _share(client, item=_FOLDER)

        assert answer.item_uri == _FOLDER

    @pytest.mark.parametrize(
        "payload",
        [
            {"id": "SYNTHETICPERMISSION0000", "roles": ["read"]},
            _link_payload(web_url=None),
        ],
        ids=["no-link", "no-web-address"],
    )
    async def test_an_answer_with_no_web_address_is_refused_and_says_a_repeat_is_safe(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        payload: Mapping[str, object],
    ) -> None:
        _ = _reads(graph)
        _ = _links(graph, payload)

        with pytest.raises(ToolError, match="makes no second one"):
            _ = await _share(client)


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "value",
        [
            OnenotePageHandle("1-SYNTHETICPAGE0000").uri,
            MailMessageHandle("AAMkSYNTHETIC0000").uri,
            "https://contoso.sharepoint.invalid/sites/finance/Shared%20Documents/Q1.docx",
            _NAME,
            _ITEM_ID,
            "sharepoint:///files/01SYNTHETICFILE0000",
            "sharepoint:///files/%20/01SYNTHETICFILE0000",
            "",
        ],
    )
    async def test_a_value_that_is_not_a_drive_item_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, value: str
    ) -> None:
        with pytest.raises(ToolError, match="No link was created"):
            _ = await _share(client, item=value)

        assert len(graph.calls) == 0, "a refused handle creates no link"

    async def test_the_refusal_names_the_tools_that_find_an_item(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError) as raised:
            _ = await _share(client, item=_NAME)

        assert "sharepoint_search_files" in str(raised.value)
        assert "sharepoint_browse_folder" in str(raised.value)
        assert ITEM_HANDLE_SOURCES in str(raised.value)


class TestThePersonBeforeTheLink:
    async def test_every_call_is_asked_about(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        link_route = _links(graph)
        asked: list[str] = []

        _ = await _share(client, confirm=_asking(asked))
        _ = await _share(client, confirm=_asking(asked))

        assert len(asked) == 2, "a link that reaches other people is asked about every time"
        assert link_route.call_count == 2

    async def test_a_refusal_creates_no_link(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        item_route = _reads(graph)
        link_route = _links(graph)

        with pytest.raises(ToolError, match=_NOTHING_CREATED):
            _ = await _share(client, confirm=_refuses)

        assert item_route.call_count == 1
        assert link_route.call_count == 0

    async def test_the_question_is_asked_after_the_read_and_before_the_link(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        link_route = _links(graph)
        calls_when_asked: list[int] = []

        async def watching(question: str, about: str) -> Confirmed:
            assert question and about
            calls_when_asked.append(len(graph.calls))
            return None

        _ = await _share(client, confirm=watching)

        assert calls_when_asked == [1], "the question came after the link or before the read"
        assert link_route.call_count == 1

    @pytest.mark.parametrize(
        ("audience", "who"),
        [
            ("organization", "Anyone in your organization who signs in can use the link."),
            (
                "anonymous",
                "Anyone who has the link can use it with no sign-in, and that can include people "
                + "outside your organization.",
            ),
        ],
    )
    async def test_both_audiences_reach_the_question_in_plain_words(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        audience: sharer.Audience,
        who: str,
    ) -> None:
        _ = _reads(graph)
        _ = _links(graph)
        asked: list[str] = []

        _ = await _share(client, audience=audience, confirm=_asking(asked))

        assert who in asked[0]
        assert "anonymous" not in asked[0]
        assert "The link does not expire unless your organization sets a limit." in asked[0]

    @pytest.mark.parametrize(
        ("access", "kind"), [("view", "a view-only link"), ("edit", "an edit link")]
    )
    async def test_the_question_names_the_kind_of_link_and_the_item(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        access: sharer.Access,
        kind: str,
    ) -> None:
        _ = _reads(graph)
        _ = _links(graph)
        asked: list[str] = []

        _ = await _share(client, access=access, confirm=_asking(asked))

        assert kind in asked[0]
        assert repr(_NAME) in asked[0]

    async def test_a_long_item_name_is_cut_in_the_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        long = "B" * 200 + ".xlsx"
        _ = _reads(graph, _item_payload(name=long))
        _ = _links(graph)
        asked: list[str] = []

        _ = await _share(client, confirm=_asking(asked))

        assert asked == [
            f"Create a view-only link to '{'B' * PREVIEW_CHARACTERS}…'? Anyone in your "
            + "organization who signs in can use the link. The link does not expire unless your "
            + "organization sets a limit."
        ]
        assert long not in asked[0]

    async def test_the_question_names_no_item_that_graph_left_unnamed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _item_payload(name=None))
        _ = _links(graph)
        asked: list[str] = []

        _ = await _share(client, confirm=_asking(asked))

        assert asked == [
            "Create a view-only link to an unnamed item? Anyone in your organization who signs "
            + "in can use the link. The link does not expire unless your organization sets a limit."
        ]

    async def test_the_top_folder_of_a_drive_is_named_as_such(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(
            graph,
            {
                "id": _ITEM_ID,
                "name": "root",
                "root": {},
                "folder": {"childCount": 3},
                "parentReference": {"driveId": _DRIVE_ID},
            },
        )
        _ = _links(graph)
        asked: list[str] = []

        _ = await _share(
            client, item=_FOLDER, access="edit", audience="anonymous", confirm=_asking(asked)
        )

        assert asked == [
            "Create an edit link to the top folder of the drive? Anyone who has the link can use "
            + "it with no sign-in, and that can include people outside your organization. The "
            + "link does not expire unless your organization sets a limit."
        ]
        assert "'root'" not in asked[0]

    async def test_the_answer_is_bound_to_the_item_the_kind_and_the_audience(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _links(graph)
        bound: list[str] = []

        async def binding(question: str, about: str) -> Confirmed:
            assert question
            bound.append(about)
            return None

        _ = await _share(client, access="edit", audience="anonymous", confirm=binding)

        assert bound == [
            write_state_for(sharer.TOOL_NAME, _DRIVE_ID, _ITEM_ID, "edit", "anonymous")
        ]

    def test_the_binding_differs_for_another_kind_or_another_audience(self) -> None:
        bindings = {
            write_state_for(sharer.TOOL_NAME, _DRIVE_ID, _ITEM_ID, access, audience)
            for access in ("view", "edit")
            for audience in ("organization", "anonymous")
        }

        assert len(bindings) == 4


def _context(answer: object) -> Context:
    class _Client:
        request_context: object = None

        async def elicit(self, message: str, response_type: object = None) -> object:
            assert message
            assert response_type is not None, "the caller must say what it expects back"
            if isinstance(answer, Exception):
                raise answer
            return answer

    return cast("Context", cast("object", _Client()))


class TestHowTheQuestionReachesAPerson:
    async def test_agreeing_answers_with_no_refusal(self) -> None:
        confirm = a_person_agrees(_context(AcceptedElicitation(data="create")))

        assert await confirm("Create a view-only link?", "synthetic-state") is None

    async def test_declining_refuses_and_creates_no_link(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        link_route = _links(graph)
        confirm = a_person_agrees(_context(DeclinedElicitation()))

        with pytest.raises(ToolError) as raised:
            _ = await _share(client, confirm=confirm)

        assert str(raised.value).startswith(_NOTHING_CREATED)
        assert link_route.call_count == 0

    async def test_a_client_that_cannot_ask_creates_no_link(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        link_route = _links(graph)
        confirm = a_person_agrees(_context(MCPError(METHOD_NOT_FOUND, "Method not found")))

        with pytest.raises(ToolError, match="does not support elicitation"):
            _ = await _share(client, confirm=confirm)

        assert link_route.call_count == 0


class _ModernRequest:
    protocol_version: str = LATEST_MODERN_VERSION


def _modern_context(
    *, answers: Mapping[str, InputResponse] | None = None, state: str | None = None
) -> Context:
    class _Client:
        request_context: _ModernRequest = _ModernRequest()
        input_responses: Mapping[str, InputResponse] | None = answers
        request_state: str | None = state

        async def elicit(self, message: str, response_type: object = None) -> object:
            raise AssertionError(
                f"a connection with no back-channel was asked {message!r} over it, "
                + f"expecting {response_type!r} back"
            )

    return cast("Context", cast("object", _Client()))


def _the_question(answer: object) -> tuple[str, str]:
    assert isinstance(answer, InputRequiredResult), "the question was never put to anybody"
    requests = answer.input_requests or {}
    assert len(requests) == 1, f"one question per call, and this one asked {sorted(requests)}"
    key = next(iter(requests))
    request = requests[key]
    assert isinstance(request, ElicitRequest)
    params = request.params
    assert isinstance(params, ElicitRequestFormParams)
    assert params.message
    assert answer.request_state
    return key, answer.request_state


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_creates_a_link(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        link_route = _links(graph)

        answer = await create_share_link(
            client,
            item=_FILE,
            access="view",
            audience="organization",
            confirm=a_person_agrees(_modern_context()),
        )

        _key, state = _the_question(answer)
        assert state == write_state_for(
            sharer.TOOL_NAME, _DRIVE_ID, _ITEM_ID, "view", "organization"
        )
        assert link_route.call_count == 0

    async def test_the_second_round_creates_the_link_the_answer_was_bound_to(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        link_route = _links(graph)
        key, state = _the_question(
            await create_share_link(
                client,
                item=_FILE,
                access="view",
                audience="organization",
                confirm=a_person_agrees(_modern_context()),
            )
        )

        answer = await create_share_link(
            client,
            item=_FILE,
            access="view",
            audience="organization",
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": "create"})},
                    state=state,
                )
            ),
        )

        assert isinstance(answer, SharingLink)
        assert link_route.call_count == 1

    async def test_an_answer_given_for_an_organization_link_creates_no_anonymous_link(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        link_route = _links(graph)
        key, state = _the_question(
            await create_share_link(
                client,
                item=_FILE,
                access="view",
                audience="organization",
                confirm=a_person_agrees(_modern_context()),
            )
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await create_share_link(
                client,
                item=_FILE,
                access="view",
                audience="anonymous",
                confirm=a_person_agrees(
                    _modern_context(
                        answers={key: ElicitResult(action="accept", content={"value": "create"})},
                        state=state,
                    )
                ),
            )

        assert link_route.call_count == 0, "an anonymous link went out on an organization accept"


class TestGraphFailures:
    async def test_a_404_on_the_read_is_a_not_found_and_creates_no_link(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ITEM_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "itemNotFound", "message": "Not Found"}}
            )
        )
        link_route = _links(graph)

        with pytest.raises(GraphNotFound):
            _ = await _share(client)

        assert link_route.call_count == 0

    async def test_a_403_on_the_link_request_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = graph.post(_LINK_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _share(client)

    @pytest.mark.parametrize(
        ("status", "code", "advice"),
        [
            (403, "accessDenied", "the delegated permission Files.ReadWrite.All"),
            (400, "invalidRequest", "it is a bad request"),
        ],
    )
    async def test_a_tenant_that_refuses_an_anonymous_link_reaches_the_model_as_advice(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        status: int,
        code: str,
        advice: str,
    ) -> None:
        _ = _reads(graph)
        link_route = graph.post(_LINK_PATH).mock(
            return_value=httpx.Response(
                status, json={"error": {"code": code, "message": "SYNTHETIC refusal"}}
            )
        )

        async def share(context: MiddlewareContext[CallToolRequestParams]) -> ToolResult:
            assert context.message.name == sharer.TOOL_NAME
            _ = await _share(client, audience="anonymous")
            raise AssertionError("Graph refused the link, and the call still answered with one")

        middleware = GraphAdviceMiddleware(
            {
                sharer.TOOL_NAME: ToolAdvice(
                    permissions=sharer.GRAPH_PERMISSIONS, not_found=sharer.GRAPH_NOT_FOUND
                )
            }
        )
        context = MiddlewareContext(
            message=CallToolRequestParams(name=sharer.TOOL_NAME, arguments={})
        )

        with pytest.raises(ToolError) as raised:
            _ = await middleware.on_call_tool(context, share)

        assert advice in str(raised.value)
        assert f"Graph error code {code}" in str(raised.value)
        assert link_route.call_count == 1

    async def test_the_call_example_reaches_graph_with_an_agreeing_person(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        example = cast("Mapping[str, str]", sharer.GRAPH_CALL_EXAMPLE)
        handle = drive_item_handle(example["item"])
        assert handle is not None, "GRAPH_CALL_EXAMPLE's own item is not a drive item handle"
        _ = _reads(graph)
        link_route = _links(graph)

        answer = await create_share_link(
            client,
            item=example["item"],
            access="view",
            audience="organization",
            confirm=_agrees,
        )

        assert isinstance(answer, SharingLink)
        assert (handle.drive_id, handle.item_id) == (_DRIVE_ID, _ITEM_ID)
        assert link_route.call_count == 1

    def test_not_found_advice_points_at_the_tools_that_find_an_item(self) -> None:
        assert "sharepoint_search_files" in sharer.GRAPH_NOT_FOUND
        assert "sharepoint_browse_folder" in sharer.GRAPH_NOT_FOUND


class TestHowItDeclaresItself:
    def test_the_permission_is_files_readwrite_all(self) -> None:
        assert sharer.GRAPH_PERMISSIONS == ("Files.ReadWrite.All",)

    def test_its_one_write_step_is_create_link(self) -> None:
        assert sharer.STEP_CREATE_LINK == "create_link"

    def test_it_declares_no_tool_that_shows_its_change(self) -> None:
        assert not hasattr(sharer, "CHANGE_SHOWN_BY")

    async def test_it_announces_itself_as_an_idempotent_write(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is WRITE_IDEMPOTENT["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_IDEMPOTENT["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_IDEMPOTENT["idempotentHint"]

    async def test_the_arguments_are_the_item_the_kind_and_the_audience(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert set(_properties(parameters)) == {"item", "access", "audience"}
        assert set(cast("Sequence[str]", parameters["required"])) == {"item", "access"}

    async def test_it_offers_no_embed_link_and_no_link_for_named_people(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert _choices(parameters, "access") == ["view", "edit"]
        assert _choices(parameters, "audience") == ["organization", "anonymous"]

    async def test_the_default_audience_is_the_organization(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert _properties(parameters)["audience"]["default"] == "organization"

    async def test_the_item_argument_names_every_source_of_an_item_handle(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert ITEM_HANDLE_SOURCES in str(_properties(parameters)["item"]["description"])

    async def test_the_item_argument_is_described_in_15_to_60_words(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert 15 <= len(str(_properties(parameters)["item"]["description"]).split()) <= 60

    async def test_the_call_example_is_accepted_by_the_schema(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert set(sharer.GRAPH_CALL_EXAMPLE) <= set(_properties(parameters))
        assert set(cast("Sequence[str]", parameters["required"])) <= set(sharer.GRAPH_CALL_EXAMPLE)

    @pytest.mark.parametrize("word", ["client", "ctx", "context", "token", "graph"])
    async def test_no_wiring_of_this_server_is_published_as_an_argument(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert not [name for name in _properties(parameters) if word in name.casefold()]

    @pytest.mark.parametrize(
        "sentence",
        [
            "This tool asks the user to agree before it creates anything, every time.",
            "If this connector already made a link of this kind to the item, Microsoft returns "
            + "that link and makes no second one.",
            "An administrator can turn off links that work with no sign-in.",
            "This call is safe to repeat after a timeout.",
            "This tool sends the link to nobody.",
        ],
    )
    async def test_the_description_carries_each_guarantee(
        self, transport: httpx.AsyncClient, sentence: str
    ) -> None:
        _parameters, tool = await _registered(transport)

        assert sentence in " ".join((tool.description or "").split())

    async def test_the_lead_names_the_tool_that_shares_with_named_people(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        assert "To share the item with named people, use sharepoint_invite." in " ".join(
            (tool.description or "").split()
        )

    async def test_the_lead_leaves_the_handle_sources_to_the_item_argument(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        lead = (tool.description or "").split("\n\nNotes:")[0]
        assert "sharepoint_search_files" not in lead
        assert "sharepoint_browse_folder" not in lead
        assert "sharepoint_resolve_url" not in lead
