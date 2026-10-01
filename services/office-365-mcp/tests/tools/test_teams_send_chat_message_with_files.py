import json
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from typing import cast

import httpx
import pytest
import respx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError, ValidationError
from fastmcp.server.elicitation import AcceptedElicitation, DeclinedElicitation
from fastmcp.tools import Tool
from mcp.types import (
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
    InputResponse,
)
from mcp.types.version import LATEST_MODERN_VERSION
from msgraph.graph_service_client import GraphServiceClient
from respx.models import Call

from office_365_mcp.graph_client import (
    GraphForbidden,
    GraphThrottled,
    GraphUnavailable,
    graph_step,
)
from office_365_mcp.shared import files
from office_365_mcp.shared.handles import DriveFileHandle, DriveFolderHandle
from office_365_mcp.shared.messages import Mention
from office_365_mcp.shared.seam import WRITE_ADDITIVE, Confirmed
from office_365_mcp.tools import teams_send_chat_message as plain_sender
from office_365_mcp.tools import teams_send_chat_message_with_files as sender
from office_365_mcp.tools.teams_send_chat_message_with_files import (
    a_person_agrees,
    send_chat_message_with_files,
)

from .conftest import TEAMS_SENDER, message_payload

_CHAT_ID = "19:release@thread.v2"
_SEND_PATH = "/chats/19%3Arelease%40thread.v2/messages"

_MESSAGE = "Here is the plan."
_SUBJECT = "Release plan"
_SENT_MESSAGE_ID = "1770000000001"

_JANE = Mention(user_id="00000000-0000-4000-8000-000000000003", name="Jane Smith")

_NOTHING_SENT = "Nothing was sent."

_DRIVE_ID = "b!SYNTHETICDRIVE0000"
_BUDGET = DriveFileHandle(_DRIVE_ID, "01SYNTHETICFILE0000")
_PLAN = DriveFileHandle(_DRIVE_ID, "01SYNTHETICFILE0001")
_BUDGET_PATH = "/drives/b%21SYNTHETICDRIVE0000/items/01SYNTHETICFILE0000"
_PLAN_PATH = "/drives/b%21SYNTHETICDRIVE0000/items/01SYNTHETICFILE0001"
_BUDGET_ID = "153fa47d-18c9-4179-be08-9879815a9f90"
_PLAN_ID = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
_SITE = "https://contoso.sharepoint.invalid/sites/finance/Shared%20Documents"


def _drive_item(
    *,
    name: str,
    guid: str,
    facet: Mapping[str, object] | None = None,
    drive_type: str = "documentLibrary",
) -> Mapping[str, object]:
    return {
        "id": "01SYNTHETIC",
        "name": name,
        "eTag": f'"{{{guid.upper()}}},3"',
        "webDavUrl": f"{_SITE}/{name}",
        "parentReference": {"driveId": _DRIVE_ID, "driveType": drive_type},
        **(facet if facet is not None else {"file": {"mimeType": "application/octet-stream"}}),
    }


def _files(
    graph: respx.MockRouter, *, budget: Mapping[str, object] | None = None
) -> tuple[respx.Route, respx.Route]:
    return (
        graph.get(_BUDGET_PATH).mock(
            return_value=httpx.Response(
                200,
                json=budget
                if budget is not None
                else _drive_item(name="Budget.docx", guid=_BUDGET_ID),
            )
        ),
        graph.get(_PLAN_PATH).mock(
            return_value=httpx.Response(200, json=_drive_item(name="Plan.pptx", guid=_PLAN_ID))
        ),
    )


async def _agrees(question: str, about: str) -> Confirmed:
    assert question and about
    return None


async def _refuses(question: str, about: str) -> Confirmed:
    assert question and about
    return _NOTHING_SENT


def _posts(graph: respx.MockRouter) -> respx.Route:
    return graph.post(_SEND_PATH).mock(
        return_value=httpx.Response(
            201,
            json=message_payload(
                message_id=_SENT_MESSAGE_ID,
                content=_MESSAGE,
                content_type="text",
                sender=TEAMS_SENDER,
                web_url=None,
            ),
        )
    )


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    sender.register(mcp, transport)
    tool = await mcp.get_tool(sender.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


async def _listed(transport: httpx.AsyncClient) -> Mapping[str, Mapping[str, object]]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    sender.register(mcp, transport)
    (tool,) = await mcp.list_tools()
    return cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])


class TestThePersonBeforeTheSend:
    async def test_a_refusal_reads_the_files_and_sends_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        budget, _plan = _files(graph)
        post = _posts(graph)

        with pytest.raises(ToolError, match=_NOTHING_SENT):
            _ = await send_chat_message_with_files(
                client,
                chat_id=_CHAT_ID,
                message=_MESSAGE,
                attachments=[_BUDGET.uri],
                confirm=_refuses,
            )

        assert budget.call_count == 1
        assert post.call_count == 0, "a declined send with a file still reached the chat"

    async def test_the_question_names_each_file_it_attaches(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _files(graph)
        _ = _posts(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await send_chat_message_with_files(
            client,
            chat_id=_CHAT_ID,
            message=_MESSAGE,
            attachments=[_BUDGET.uri, _PLAN.uri],
            confirm=capturing,
        )

        assert asked == [
            f"Send {_MESSAGE!r} to chat {_CHAT_ID!r} now? It attaches 'Budget.docx', "
            + "'Plan.pptx'. This cannot be recalled once sent."
        ]

    async def test_the_question_names_the_mentions_the_subject_and_the_importance(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _files(graph)
        _ = _posts(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await send_chat_message_with_files(
            client,
            chat_id=_CHAT_ID,
            message=_MESSAGE,
            attachments=[_BUDGET.uri],
            confirm=capturing,
            mentions=[_JANE],
            importance="high",
            subject=_SUBJECT,
        )

        assert asked == [
            f"Send {_MESSAGE!r} with the subject {_SUBJECT!r} and high importance to chat "
            + f"{_CHAT_ID!r} now? It mentions 'Jane Smith'. It attaches 'Budget.docx'. This "
            + "cannot be recalled once sent."
        ]

    async def test_every_file_is_read_before_the_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _files(graph)
        post = _posts(graph)
        calls_when_asked: list[int] = []

        async def watching(question: str, about: str) -> Confirmed:
            assert question and about
            calls_when_asked.append(len(graph.calls))
            return None

        _ = await send_chat_message_with_files(
            client,
            chat_id=_CHAT_ID,
            message=_MESSAGE,
            attachments=[_BUDGET.uri, _PLAN.uri],
            confirm=watching,
        )

        assert calls_when_asked == [2], "asked before every file was read, or after the post"
        assert post.call_count == 1


class TestHowTheQuestionReachesAPerson:
    @staticmethod
    def _context(answer: object) -> Context:
        class _Client:
            request_context: object = None

            async def elicit(self, message: str, response_type: object = None) -> object:
                assert message
                assert response_type is not None
                return answer

        return cast("Context", cast("object", _Client()))

    async def test_agreeing_answers_with_no_refusal(self) -> None:
        confirm = a_person_agrees(self._context(AcceptedElicitation(data="send")))

        assert await confirm("Send it?", "Send it?") is None

    async def test_declining_refuses_and_says_nothing_was_sent(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _files(graph)
        post = _posts(graph)
        confirm = a_person_agrees(self._context(DeclinedElicitation()))

        with pytest.raises(ToolError, match=_NOTHING_SENT):
            _ = await send_chat_message_with_files(
                client,
                chat_id=_CHAT_ID,
                message=_MESSAGE,
                attachments=[_BUDGET.uri],
                confirm=confirm,
            )

        assert post.call_count == 0


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
                f"a connection with no back-channel was asked {message!r} over it, expecting "
                + f"{response_type!r} back"
            )

    return cast("Context", cast("object", _Client()))


def _the_question(answer: object) -> tuple[str, str, str]:
    assert isinstance(answer, InputRequiredResult), "the question was never put to anybody"
    requests = answer.input_requests or {}
    assert len(requests) == 1, f"one question per call, and this one asked {sorted(requests)}"
    key = next(iter(requests))
    request = requests[key]
    assert isinstance(request, ElicitRequest)
    params = request.params
    assert isinstance(params, ElicitRequestFormParams)
    assert params.message
    schema = cast("Mapping[str, object]", params.requested_schema)
    properties = cast("Mapping[str, object]", schema["properties"])
    choices = cast("Sequence[str]", cast("Mapping[str, object]", properties["value"])["enum"])
    assert answer.request_state
    return key, answer.request_state, choices[0]


class TestTheEraWithNoBackChannel:
    async def test_no_answer_yet_asks_and_never_posts(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _files(graph)
        post = _posts(graph)

        answer = await send_chat_message_with_files(
            client,
            chat_id=_CHAT_ID,
            message=_MESSAGE,
            attachments=[_BUDGET.uri],
            confirm=a_person_agrees(_modern_context()),
        )

        _key, _state, _agrees_with = _the_question(answer)
        assert post.call_count == 0, "an unanswered question posted the message anyway"

    async def test_the_second_round_sends_the_files_the_answer_was_bound_to(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _files(graph)
        post = _posts(graph)
        key, state, agrees_with = _the_question(
            await send_chat_message_with_files(
                client,
                chat_id=_CHAT_ID,
                message=_MESSAGE,
                attachments=[_BUDGET.uri],
                confirm=a_person_agrees(_modern_context()),
            )
        )

        answer = await send_chat_message_with_files(
            client,
            chat_id=_CHAT_ID,
            message=_MESSAGE,
            attachments=[_BUDGET.uri],
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": agrees_with})},
                    state=state,
                )
            ),
        )

        assert post.call_count == 1, "the confirmed post did not happen exactly once"
        assert not isinstance(answer, InputRequiredResult)

    async def test_an_accept_for_one_file_set_cannot_send_another(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _files(graph)
        post = _posts(graph)
        key, state, agrees_with = _the_question(
            await send_chat_message_with_files(
                client,
                chat_id=_CHAT_ID,
                message=_MESSAGE,
                attachments=[_BUDGET.uri],
                confirm=a_person_agrees(_modern_context()),
            )
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await send_chat_message_with_files(
                client,
                chat_id=_CHAT_ID,
                message=_MESSAGE,
                attachments=[_BUDGET.uri, _PLAN.uri],
                confirm=a_person_agrees(
                    _modern_context(
                        answers={
                            key: ElicitResult(action="accept", content={"value": agrees_with})
                        },
                        state=state,
                    )
                ),
            )

        assert post.call_count == 0, "the plan went out on an accept given for the budget alone"


class TestWhatItAsksGraphFor:
    async def test_it_reads_each_file_once_and_then_posts_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        budget, plan = _files(graph)
        post = _posts(graph)

        _ = await send_chat_message_with_files(
            client,
            chat_id=_CHAT_ID,
            message=_MESSAGE,
            attachments=[_BUDGET.uri, _PLAN.uri],
            confirm=_agrees,
        )

        assert (budget.call_count, plan.call_count, post.call_count) == (1, 1, 1)
        made = cast("Sequence[Call]", graph.calls)
        assert [call.request.method for call in made] == ["GET", "GET", "POST"]

    async def test_the_post_carries_each_file_as_a_reference_and_a_tag_after_the_text(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _files(graph)
        post = _posts(graph)

        _ = await send_chat_message_with_files(
            client,
            chat_id=_CHAT_ID,
            message="Q3 < Q4 & more",
            attachments=[_BUDGET.uri, _PLAN.uri],
            confirm=_agrees,
            mentions=[_JANE],
        )

        body = cast("Mapping[str, object]", json.loads(post.calls.last.request.content))
        assert body["body"] == {
            "content": '<at id="0">Jane Smith</at> Q3 &lt; Q4 &amp; more '
            + f'<attachment id="{_BUDGET_ID}"></attachment> '
            + f'<attachment id="{_PLAN_ID}"></attachment>',
            "contentType": "html",
        }
        assert body["attachments"] == [
            {
                "contentType": "reference",
                "contentUrl": f"{_SITE}/Budget.docx",
                "id": _BUDGET_ID,
                "name": "Budget.docx",
            },
            {
                "contentType": "reference",
                "contentUrl": f"{_SITE}/Plan.pptx",
                "id": _PLAN_ID,
                "name": "Plan.pptx",
            },
        ]

    async def test_the_post_carries_the_subject_and_the_importance_as_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _files(graph)
        post = _posts(graph)

        _ = await send_chat_message_with_files(
            client,
            chat_id=_CHAT_ID,
            message=_MESSAGE,
            attachments=[_BUDGET.uri],
            confirm=_agrees,
            importance="urgent",
            subject=_SUBJECT,
        )

        body = cast("Mapping[str, object]", json.loads(post.calls.last.request.content))
        assert (body["subject"], body["importance"]) == (_SUBJECT, "urgent")

    async def test_each_call_is_measured_under_its_own_step(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _ = _files(graph)
        _ = _posts(graph)
        measured: list[str] = []

        def recording(step: str) -> AbstractContextManager[None]:
            measured.append(step)
            return graph_step(step)

        monkeypatch.setattr(sender, "graph_step", recording)
        monkeypatch.setattr(files, "graph_step", recording)

        _ = await send_chat_message_with_files(
            client, chat_id=_CHAT_ID, message=_MESSAGE, attachments=[_BUDGET.uri], confirm=_agrees
        )

        assert measured == [files.STEP_DRIVE_ITEM, sender.STEP_SEND]


class TestWhatItRefusesToAttach:
    @pytest.mark.parametrize(
        "attachment",
        [
            DriveFolderHandle(_DRIVE_ID, "01SYNTHETICFILE0000").uri,
            f"{_SITE}/Budget.docx",
            "Budget.docx",
        ],
    )
    async def test_a_value_that_is_not_a_file_handle_is_refused_before_any_call(
        self, client: GraphServiceClient, graph: respx.MockRouter, attachment: str
    ) -> None:
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        with pytest.raises(ToolError) as raised:
            _ = await send_chat_message_with_files(
                client,
                chat_id=_CHAT_ID,
                message=_MESSAGE,
                attachments=[_BUDGET.uri, attachment],
                confirm=capturing,
            )

        assert str(raised.value).startswith(f"{_NOTHING_SENT} The attachment {attachment!r}")
        assert asked == [], "the user was asked to agree to a call that cannot succeed"
        assert len(graph.calls) == 0

    @pytest.mark.parametrize(
        ("budget", "refusal"),
        [
            pytest.param(
                _drive_item(name="Reports", guid=_BUDGET_ID, facet={"folder": {"childCount": 2}}),
                "names a folder, and this tool attaches files only",
                id="folder",
            ),
            pytest.param(
                _drive_item(name="Notes", guid=_BUDGET_ID, facet={"package": {"type": "oneNote"}}),
                "is not a plain file in Microsoft 365",
                id="not-a-file",
            ),
            pytest.param(
                _drive_item(name="Budget.docx", guid=_BUDGET_ID, drive_type="personal"),
                "is in a personal OneDrive",
                id="personal-drive",
            ),
            pytest.param(
                {**_drive_item(name="Budget.docx", guid=_BUDGET_ID), "eTag": None},
                "did not send all the details",
                id="no-etag",
            ),
            pytest.param(
                {**_drive_item(name="Budget.docx", guid=_BUDGET_ID), "webDavUrl": None},
                "did not send all the details",
                id="no-webdav",
            ),
        ],
    )
    async def test_a_file_teams_cannot_attach_is_refused_before_the_question(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        budget: Mapping[str, object],
        refusal: str,
    ) -> None:
        _ = _files(graph, budget=budget)
        post = _posts(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        with pytest.raises(ToolError) as raised:
            _ = await send_chat_message_with_files(
                client,
                chat_id=_CHAT_ID,
                message=_MESSAGE,
                attachments=[_BUDGET.uri, _PLAN.uri],
                confirm=capturing,
            )

        assert str(raised.value).startswith(_NOTHING_SENT)
        assert refusal in str(raised.value)
        assert asked == []
        assert post.call_count == 0


class TestTheRetryItRefuses:
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_post_graph_answers_503_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _files(graph)
        post = graph.post(_SEND_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await send_chat_message_with_files(
                client,
                chat_id=_CHAT_ID,
                message=_MESSAGE,
                attachments=[_BUDGET.uri],
                confirm=_agrees,
            )

        assert post.call_count == 1

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_throttled_post_is_not_repeated_either(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _files(graph)
        post = graph.post(_SEND_PATH).mock(
            return_value=httpx.Response(429, headers={"Retry-After": "12"})
        )

        with pytest.raises(GraphThrottled):
            _ = await send_chat_message_with_files(
                client,
                chat_id=_CHAT_ID,
                message=_MESSAGE,
                attachments=[_BUDGET.uri],
                confirm=_agrees,
            )

        assert post.call_count == 1


class TestWhatItAnswers:
    async def test_the_answer_carries_a_handle_teams_read_message_can_read_back(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _files(graph)
        _ = _posts(graph)

        answer = await send_chat_message_with_files(
            client,
            chat_id=_CHAT_ID,
            message=_MESSAGE,
            attachments=[_BUDGET.uri],
            confirm=_agrees,
        )

        assert not isinstance(answer, InputRequiredResult)
        assert answer.message_id == _SENT_MESSAGE_ID
        assert answer.uri == "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000001"


class TestTheFailuresItPassesOn:
    async def test_a_refused_post_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _files(graph)
        _ = graph.post(_SEND_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await send_chat_message_with_files(
                client,
                chat_id=_CHAT_ID,
                message=_MESSAGE,
                attachments=[_BUDGET.uri],
                confirm=_agrees,
            )

    async def test_a_refused_file_read_is_a_forbidden_and_asks_nobody(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_BUDGET_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "accessDenied", "message": "denied"}}
            )
        )
        post = _posts(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        with pytest.raises(GraphForbidden):
            _ = await send_chat_message_with_files(
                client,
                chat_id=_CHAT_ID,
                message=_MESSAGE,
                attachments=[_BUDGET.uri],
                confirm=capturing,
            )

        assert asked == []
        assert post.call_count == 0


class TestHowItDeclaresItself:
    def test_the_permissions_are_the_chat_send_and_the_file_read_and_nothing_else(self) -> None:
        assert sender.GRAPH_PERMISSIONS == ("ChatMessage.Send", "Files.Read.All")

    def test_its_example_call_is_never_narrowed(self) -> None:
        assert not hasattr(sender, "GRAPH_CALL_NARROWS_TO")

    def test_its_send_step_is_the_one_of_teams_send_chat_message(self) -> None:
        assert sender.STEP_SEND == "send_chat_message"

    async def test_it_announces_itself_as_an_addition_rather_than_a_destructive_write(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is WRITE_ADDITIVE["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_ADDITIVE["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_ADDITIVE["idempotentHint"]

    @pytest.mark.parametrize(
        "sentence",
        [
            "This tool asks the user to agree before it sends anything, every time. This tool "
            + "sends nothing unless the user agrees.",
            "This tool sends the message immediately, and nothing here can recall it.",
            "If a call times out, do not call this tool again first. Before you call again, make "
            + "sure that teams_list_chat_messages does not already show the message.",
            "This tool uploads nothing and changes no sharing setting of a file.",
            "The files come after the text.",
            "teams_send_chat_message sends a message with no file.",
            "teams_send_channel_message_with_files is the tool for a channel.",
        ],
    )
    async def test_the_description_holds_the_sentence(
        self, transport: httpx.AsyncClient, sentence: str
    ) -> None:
        _parameters, tool = await _registered(transport)

        assert sentence in " ".join((tool.description or "").split())

    async def test_the_arguments_are_chat_id_message_attachments_and_the_optional_rest(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {
            "chat_id",
            "message",
            "attachments",
            "mentions",
            "importance",
            "subject",
        }
        assert set(cast("Sequence[str]", parameters["required"])) == {
            "chat_id",
            "message",
            "attachments",
        }

    async def test_the_attachments_are_at_least_one_handle_from_the_sharepoint_tools(
        self, transport: httpx.AsyncClient
    ) -> None:
        attachments = (await _listed(transport))["attachments"]

        described = str(attachments["description"])
        assert "sharepoint_search_files" in described
        assert "sharepoint_browse_folder" in described
        assert attachments["type"] == "array"
        assert attachments["items"] == {"type": "string"}
        assert attachments["minItems"] == 1

    async def test_an_empty_file_list_never_reaches_this_tool(
        self, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _parameters, tool = await _registered(transport)

        with pytest.raises(ValidationError, match="attachments"):
            _ = await tool.run({**sender.GRAPH_CALL_EXAMPLE, "attachments": []})

        assert len(graph.calls) == 0, "a send with no file reached Graph"

    async def test_an_empty_subject_never_reaches_this_tool(
        self, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _parameters, tool = await _registered(transport)

        with pytest.raises(ValidationError, match="subject"):
            _ = await tool.run({**sender.GRAPH_CALL_EXAMPLE, "subject": ""})

        assert len(graph.calls) == 0, "a subject the schema refuses reached Graph"

    async def test_the_importance_is_normal_high_or_urgent_and_nothing_else(
        self, transport: httpx.AsyncClient
    ) -> None:
        importance = (await _listed(transport))["importance"]

        options = cast("Sequence[Mapping[str, object]]", importance["anyOf"])
        assert [option.get("enum") for option in options] == [["normal", "high", "urgent"], None]

    def test_its_example_attaches_a_file_handle(self) -> None:
        attached = cast("Sequence[str]", sender.GRAPH_CALL_EXAMPLE["attachments"])

        assert attached == [_BUDGET.uri]


async def _described_by_both_chat_tools(
    transport: httpx.AsyncClient,
) -> Mapping[str, Mapping[str, str]]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    plain_sender.register(mcp, transport)
    sender.register(mcp, transport)
    return {
        tool.name: {
            name: str(schema.get("description", ""))
            for name, schema in cast(
                "Mapping[str, Mapping[str, object]]", tool.parameters["properties"]
            ).items()
        }
        for tool in await mcp.list_tools()
    }


class TestTheWordsItSharesWithTheChatSendWithNoFile:
    async def test_every_argument_both_tools_take_has_the_same_description_in_both(
        self, transport: httpx.AsyncClient
    ) -> None:
        described = await _described_by_both_chat_tools(transport)

        plain = described[plain_sender.TOOL_NAME]
        with_files = described[sender.TOOL_NAME]
        shared = set(plain) & set(with_files)
        assert shared == {"chat_id", "message", "mentions", "importance", "subject"}
        assert {name: with_files[name] for name in shared} == {name: plain[name] for name in shared}

    async def test_every_argument_of_both_tools_is_described_within_the_house_length(
        self, transport: httpx.AsyncClient
    ) -> None:
        described = await _described_by_both_chat_tools(transport)

        assert set(described) == {plain_sender.TOOL_NAME, sender.TOOL_NAME}
        lengths = {
            f"{tool}.{name}": len(description.split())
            for tool, arguments in described.items()
            for name, description in arguments.items()
        }
        assert all(15 <= length <= 60 for length in lengths.values()), lengths
