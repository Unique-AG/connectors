import json
from collections.abc import Mapping, Sequence
from typing import Annotated, cast

import httpx
import pytest
import respx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError, ValidationError
from fastmcp.server.elicitation import AcceptedElicitation, DeclinedElicitation
from fastmcp.tools import FunctionTool
from mcp.shared.exceptions import MCPError
from mcp.types import (
    METHOD_NOT_FOUND,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
    InputResponse,
)
from mcp.types.version import LATEST_MODERN_VERSION
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field, TypeAdapter

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared.messages import CHAT_TOPIC_MAX_CHARACTERS
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE_IDEMPOTENT, Confirmed
from office_365_mcp.tools import teams_rename_chat as renamer
from office_365_mcp.tools.teams_rename_chat import RenamedChat, a_person_agrees, rename_chat

_CHAT_ID = "19:release@thread.v2"
_OTHER_CHAT_ID = "19:pricing@thread.v2"
_CHAT_PATH = "/chats/19%3Arelease%40thread.v2"

_TOPIC = "Release planning"
_OTHER_TOPIC = "Pricing review"

_NOTHING_RENAMED = "Nothing was renamed."


async def _agrees(question: str, about: str) -> Confirmed:
    assert question and about
    return None


async def _refuses(question: str, about: str) -> Confirmed:
    assert question and about
    return _NOTHING_RENAMED


def _chat_payload(*, chat_id: str = _CHAT_ID, topic: str | None = _TOPIC) -> dict[str, object]:
    return {
        "id": chat_id,
        "topic": topic,
        "createdDateTime": "2026-02-10T09:00:00Z",
        "lastUpdatedDateTime": "2026-02-11T09:20:00Z",
        "chatType": "group",
    }


def _patches(graph: respx.MockRouter, payload: Mapping[str, object] | None = None) -> respx.Route:
    return graph.patch(_CHAT_PATH).mock(
        return_value=httpx.Response(200, json=payload if payload is not None else _chat_payload())
    )


class _ModernRequest:
    protocol_version: str = LATEST_MODERN_VERSION


class _Session:
    def __init__(
        self,
        *,
        modern: bool = True,
        answers: Mapping[str, InputResponse] | None = None,
        state: str | None = None,
        elicited: object = None,
    ) -> None:
        self.request_context: _ModernRequest | None = _ModernRequest() if modern else None
        self.input_responses: Mapping[str, InputResponse] | None = answers
        self.request_state: str | None = state
        self.asked: list[str] = []
        self._elicited: object = elicited

    async def elicit(self, message: str, response_type: object = None) -> object:
        assert response_type is not None
        self.asked.append(message)
        if self._elicited is None:
            raise AssertionError(f"a connection with no back-channel was asked {message!r}")
        return self._elicited

    @property
    def context(self) -> Context:
        return cast("Context", cast("object", self))


def _the_question(answer: object) -> tuple[str, str, str, str]:
    assert isinstance(answer, InputRequiredResult), "the question was never put to anybody"
    requests = answer.input_requests or {}
    assert len(requests) == 1, f"one question per call, and this one asked {sorted(requests)}"
    key = next(iter(requests))
    request = requests[key]
    assert isinstance(request, ElicitRequest)
    params = request.params
    assert isinstance(params, ElicitRequestFormParams)
    schema = cast("Mapping[str, object]", params.requested_schema)
    properties = cast("Mapping[str, object]", schema["properties"])
    choices = cast("Sequence[str]", cast("Mapping[str, object]", properties["value"])["enum"])
    assert answer.request_state
    return key, answer.request_state, choices[0], params.message


async def _registered(transport: httpx.AsyncClient) -> FunctionTool:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    renamer.register(mcp, transport)
    tool = await mcp.get_tool(renamer.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    assert isinstance(tool, FunctionTool)
    return tool


def _topic_schema(tool: FunctionTool) -> Mapping[str, object]:
    properties = cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])
    return properties["topic"]


class TestTheRequestItMakes:
    async def test_it_patches_the_chat_with_the_topic_and_nothing_else(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _patches(graph)

        _ = await rename_chat(client, chat_id=_CHAT_ID, topic=_TOPIC, confirm=_agrees)

        assert route.call_count == 1
        assert len(graph.calls) == 1, "one rename costs one Graph call, and nothing else"
        request = route.calls.last.request
        assert request.headers["content-type"] == "application/json"
        assert json.loads(request.content) == {"topic": _TOPIC}

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_rename_is_idempotent_so_the_default_retry_runs(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.patch(_CHAT_PATH).mock(
            side_effect=[httpx.Response(503), httpx.Response(200, json=_chat_payload())]
        )

        _ = await rename_chat(client, chat_id=_CHAT_ID, topic=_TOPIC, confirm=_agrees)

        assert route.call_count == 2, (
            "renaming again with the same topic is harmless, so it retries"
        )


class TestTheSchemaBeforeTheRequest:
    @pytest.mark.parametrize(
        "topic",
        [
            pytest.param("Release: planning", id="colon"),
            pytest.param(":", id="colon-only"),
            pytest.param("x" * (CHAT_TOPIC_MAX_CHARACTERS + 1), id="251-characters"),
            pytest.param("", id="empty"),
        ],
    )
    async def test_a_topic_the_schema_refuses_never_reaches_graph(
        self, transport: httpx.AsyncClient, graph: respx.MockRouter, topic: str
    ) -> None:
        tool = await _registered(transport)

        with pytest.raises(ValidationError, match="topic"):
            _ = await tool.run({**renamer.GRAPH_CALL_EXAMPLE, "topic": topic})

        assert len(graph.calls) == 0, "a topic the schema refuses reached Graph"

    async def test_the_published_topic_is_one_to_250_characters_with_no_colon(
        self, transport: httpx.AsyncClient
    ) -> None:
        published = _topic_schema(await _registered(transport))

        assert published["minLength"] == 1
        assert published["maxLength"] == 250
        assert "at most 250 characters" in cast("str", published["description"])
        assert "must not contain a colon (:)" in cast("str", published["description"])
        accepted: TypeAdapter[str] = TypeAdapter(
            Annotated[str, Field(pattern=cast("str", published["pattern"]))]
        )
        assert accepted.validate_python("x" * 250) == "x" * 250
        with pytest.raises(ValueError, match="match pattern"):
            _ = accepted.validate_python("Release: planning")


class TestThePersonBeforeTheChange:
    async def test_a_refusal_renames_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _patches(graph)

        with pytest.raises(ToolError, match=_NOTHING_RENAMED):
            _ = await rename_chat(client, chat_id=_CHAT_ID, topic=_TOPIC, confirm=_refuses)

        assert route.call_count == 0
        assert len(graph.calls) == 0

    async def test_a_decline_renames_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _patches(graph)
        session = _Session(modern=False, elicited=DeclinedElicitation())

        with pytest.raises(ToolError, match=_NOTHING_RENAMED):
            _ = await rename_chat(
                client, chat_id=_CHAT_ID, topic=_TOPIC, confirm=a_person_agrees(session.context)
            )

        assert len(session.asked) == 1
        assert route.call_count == 0

    async def test_agreeing_over_the_back_channel_renames_the_chat(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _patches(graph)
        session = _Session(modern=False, elicited=AcceptedElicitation(data="rename"))

        _ = await rename_chat(
            client, chat_id=_CHAT_ID, topic=_TOPIC, confirm=a_person_agrees(session.context)
        )

        assert len(session.asked) == 1
        assert route.call_count == 1

    async def test_the_question_happens_before_the_patch(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _patches(graph)
        calls_when_asked: list[int] = []

        async def watching(question: str, about: str) -> Confirmed:
            assert question and about
            calls_when_asked.append(len(graph.calls))
            return None

        _ = await rename_chat(client, chat_id=_CHAT_ID, topic=_TOPIC, confirm=watching)

        assert calls_when_asked == [0], "asked after the chat was already renamed"
        assert route.call_count == 1

    async def test_the_question_names_the_chat_the_topic_and_who_sees_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _patches(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await rename_chat(client, chat_id=_CHAT_ID, topic=_TOPIC, confirm=capturing)

        assert asked == [
            f"Rename the chat {_CHAT_ID!r} to {_TOPIC!r}? "
            + "Everyone in the conversation can see this change."
        ]

    async def test_a_client_that_cannot_ask_renames_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _patches(graph)

        class _CannotAsk:
            request_context: object = None

            async def elicit(self, message: str, response_type: object = None) -> object:
                assert message and response_type is not None
                raise MCPError(METHOD_NOT_FOUND, "Method not found")

        confirm = a_person_agrees(cast("Context", cast("object", _CannotAsk())))

        with pytest.raises(ToolError, match="does not support elicitation"):
            _ = await rename_chat(client, chat_id=_CHAT_ID, topic=_TOPIC, confirm=confirm)

        assert route.call_count == 0

    def test_the_binding_differs_for_another_topic_and_another_chat(self) -> None:
        about = renamer._about  # pyright: ignore[reportPrivateUsage]

        bound = about(_CHAT_ID, _TOPIC)

        assert bound == about(_CHAT_ID, _TOPIC)
        assert bound != about(_CHAT_ID, _OTHER_TOPIC)
        assert bound != about(_OTHER_CHAT_ID, _TOPIC)


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_patches(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _patches(graph)

        answer = await rename_chat(
            client, chat_id=_CHAT_ID, topic=_TOPIC, confirm=a_person_agrees(_Session().context)
        )

        _key, _state, agrees_with, question = _the_question(answer)
        assert agrees_with == "rename"
        assert _TOPIC in question
        assert route.call_count == 0, "an unanswered question renamed the chat anyway"

    async def test_the_second_round_patches_the_topic_the_answer_was_bound_to(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _patches(graph)
        key, state, agrees_with, _question = _the_question(
            await rename_chat(
                client,
                chat_id=_CHAT_ID,
                topic=_TOPIC,
                confirm=a_person_agrees(_Session().context),
            )
        )

        answer = await rename_chat(
            client,
            chat_id=_CHAT_ID,
            topic=_TOPIC,
            confirm=a_person_agrees(
                _Session(
                    answers={key: ElicitResult(action="accept", content={"value": agrees_with})},
                    state=state,
                ).context
            ),
        )

        assert route.call_count == 1, "the agreed rename did not happen exactly once"
        assert json.loads(route.calls.last.request.content) == {"topic": _TOPIC}
        assert answer == RenamedChat(chat_id=_CHAT_ID, topic=_TOPIC)

    async def test_an_answer_bound_to_another_topic_renames_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _patches(graph)
        key, state, agrees_with, _question = _the_question(
            await rename_chat(
                client,
                chat_id=_CHAT_ID,
                topic=_TOPIC,
                confirm=a_person_agrees(_Session().context),
            )
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await rename_chat(
                client,
                chat_id=_CHAT_ID,
                topic=_OTHER_TOPIC,
                confirm=a_person_agrees(
                    _Session(
                        answers={
                            key: ElicitResult(action="accept", content={"value": agrees_with})
                        },
                        state=state,
                    ).context
                ),
            )

        assert route.call_count == 0, "a chat was renamed under an answer nobody gave for it"

    async def test_a_declined_second_round_renames_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _patches(graph)
        key, state, _agrees_with, _question = _the_question(
            await rename_chat(
                client,
                chat_id=_CHAT_ID,
                topic=_TOPIC,
                confirm=a_person_agrees(_Session().context),
            )
        )

        with pytest.raises(ToolError, match=_NOTHING_RENAMED):
            _ = await rename_chat(
                client,
                chat_id=_CHAT_ID,
                topic=_TOPIC,
                confirm=a_person_agrees(
                    _Session(answers={key: ElicitResult(action="decline")}, state=state).context
                ),
            )

        assert route.call_count == 0


class TestWhatItAnswers:
    async def test_the_answer_is_read_off_the_chat_graph_returned(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _patches(graph, _chat_payload(topic="Release planning (stored)"))

        answer = await rename_chat(client, chat_id=_CHAT_ID, topic=_TOPIC, confirm=_agrees)

        assert answer == RenamedChat(chat_id=_CHAT_ID, topic="Release planning (stored)")

    async def test_a_chat_graph_returned_with_no_topic_answers_null(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _patches(graph, _chat_payload(topic=None))

        answer = await rename_chat(client, chat_id=_CHAT_ID, topic=_TOPIC, confirm=_agrees)

        assert answer == RenamedChat(chat_id=_CHAT_ID, topic=None)


class TestTheFailuresItPassesOn:
    async def test_a_refused_rename_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.patch(_CHAT_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Forbidden", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await rename_chat(client, chat_id=_CHAT_ID, topic=_TOPIC, confirm=_agrees)

    async def test_a_chat_graph_does_not_find_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.patch(_CHAT_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "NotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await rename_chat(client, chat_id=_CHAT_ID, topic=_TOPIC, confirm=_agrees)


class TestHowItDeclaresItself:
    def test_it_declares_the_permission_microsoft_documents_for_a_chat_update(self) -> None:
        assert renamer.GRAPH_PERMISSIONS == ("Chat.ReadWrite",)

    def test_its_step_is_rename_chat(self) -> None:
        assert renamer.STEP == "rename_chat"

    def test_it_names_no_tool_that_shows_the_change(self) -> None:
        assert not hasattr(renamer, "CHANGE_SHOWN_BY")

    async def test_it_announces_itself_as_a_destructive_write_that_is_safe_to_repeat(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["idempotentHint"]
        assert annotations.open_world_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["openWorldHint"]

    async def test_the_description_says_who_sees_it_that_it_asks_every_time_and_how_to_retry(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = " ".join((tool.description or "").split())
        assert "Everyone in the conversation can see the change." in description
        assert (
            "This tool asks the user to agree before it renames a chat, every time. This tool "
            + "renames nothing unless the user agrees."
        ) in description
        assert "This call is safe to repeat after a timeout." in description

    async def test_the_description_says_only_a_group_chat_can_be_renamed(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = " ".join((tool.description or "").split())
        assert (
            "Microsoft 365 lets this tool rename a group chat only, not a one-to-one chat or a "
            + "meeting chat."
        ) in description

    async def test_the_arguments_are_chat_id_and_topic_and_nothing_else(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        properties = cast("Mapping[str, object]", tool.parameters["properties"])
        assert set(properties) == {"chat_id", "topic"}
        assert set(cast("Sequence[str]", tool.parameters["required"])) == {"chat_id", "topic"}
        assert set(renamer.GRAPH_CALL_EXAMPLE) == set(properties)
