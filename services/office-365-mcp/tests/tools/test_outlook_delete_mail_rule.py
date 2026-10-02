from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
)
from fastmcp.tools import Tool
from mcp.shared.exceptions import MCPError
from mcp.types import (
    METHOD_NOT_FOUND,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
)
from mcp.types.version import LATEST_MODERN_VERSION
from msgraph.graph_service_client import GraphServiceClient
from respx.models import Call

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared.handles import MailFolderHandle, MailRuleHandle
from office_365_mcp.shared.rules import RULE_FIELDS
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE_IDEMPOTENT, Confirm
from office_365_mcp.tools import outlook_delete_mail_rule as deleter
from office_365_mcp.tools.outlook_delete_mail_rule import (
    DeletedRule,
    a_person_agrees,
    delete_mail_rule,
)

_RULE_ID = "AQAAAJ5dZqSYNTHETIC="

_RULE_REF = MailRuleHandle(_RULE_ID).uri

_RULE_PATH = "/me/mailFolders/inbox/messageRules/AQAAAJ5dZqSYNTHETIC%3D"

_DANA = "dana@example.invalid"

_NOTHING_DELETED = "The rule was not deleted."

_RETRY = "If you call this tool again with the same arguments, the call will fail the same way."


def _rule(
    *,
    display_name: str | None = "Partner mail",
    is_read_only: bool | None = False,
    conditions: Mapping[str, object] | None = None,
    actions: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": _RULE_ID,
        "displayName": display_name,
        "sequence": 3,
        "isEnabled": True,
        "isReadOnly": is_read_only,
        "hasError": False,
        "conditions": dict(conditions or {"senderContains": ["partner"]}),
        "actions": dict(
            actions
            or {"forwardTo": [{"emailAddress": {"address": _DANA}}], "permanentDelete": True}
        ),
    }


_CHANGED_BY_THEN = [
    pytest.param(_rule(conditions={"senderContains": ["anyone"]}), id="other-conditions"),
    pytest.param(_rule(actions={"markAsRead": True}), id="other-actions"),
    pytest.param(_rule(display_name="Renamed"), id="other-name"),
]


def _reads(graph: respx.MockRouter, payload: Mapping[str, object] | None = None) -> respx.Route:
    return graph.get(_RULE_PATH).mock(
        return_value=httpx.Response(200, json=dict(payload or _rule()))
    )


def _deletes(graph: respx.MockRouter, status: int = 204) -> respx.Route:
    return graph.delete(_RULE_PATH).mock(return_value=httpx.Response(status))


def _ready(graph: respx.MockRouter, payload: Mapping[str, object] | None = None) -> respx.Route:
    _ = _reads(graph, payload)
    return _deletes(graph)


async def _agrees(question: str, about: str) -> str | None:
    assert question, "the person was asked nothing at all"
    assert about, "the answer was bound to nothing"
    return None


async def _refuses(question: str, about: str) -> str | None:
    assert question
    assert about
    return _NOTHING_DELETED


async def _never_asked(question: str, about: str) -> str | None:
    raise AssertionError(f"a refused delete was put to a person: {question!r} ({about})")


async def _round(
    client: GraphServiceClient, *, rule_ref: str = _RULE_REF, confirm: Confirm = _agrees
) -> DeletedRule | InputRequiredResult:
    return await delete_mail_rule(client, rule_ref=rule_ref, confirm=confirm)


async def _delete(
    client: GraphServiceClient, *, rule_ref: str = _RULE_REF, confirm: Confirm = _agrees
) -> DeletedRule:
    answer = await _round(client, rule_ref=rule_ref, confirm=confirm)
    assert isinstance(answer, DeletedRule), "this call was answered with a question"
    return answer


def _capturing() -> tuple[list[str], list[str], Confirm]:
    asked: list[str] = []
    bound: list[str] = []

    async def capture(question: str, about: str) -> str | None:
        asked.append(question)
        bound.append(about)
        return None

    return asked, bound, capture


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


class _ModernRequest:
    protocol_version: str = LATEST_MODERN_VERSION


def _modern_context(
    *, answers: Mapping[str, object] | None = None, state: str | None = None
) -> Context:
    class _Client:
        request_context: _ModernRequest = _ModernRequest()
        input_responses: Mapping[str, object] | None = answers
        request_state: str | None = state

        async def elicit(self, message: str, response_type: object = None) -> object:
            raise AssertionError(
                f"a connection with no back-channel was asked {message!r} over it, "
                + f"expecting {response_type!r} back"
            )

    return cast("Context", cast("object", _Client()))


def _agreeing(key: str, agree: str, state: str) -> Context:
    return _modern_context(
        answers={key: ElicitResult(action="accept", content={"value": agree})}, state=state
    )


def _the_question(answer: DeletedRule | InputRequiredResult) -> tuple[str, str, str, str]:
    assert isinstance(answer, InputRequiredResult), "the question was never put to anybody"
    requests = answer.input_requests or {}
    assert len(requests) == 1
    key = next(iter(requests))
    request = requests[key]
    assert isinstance(request, ElicitRequest)
    params = request.params
    assert isinstance(params, ElicitRequestFormParams)
    properties = cast(
        "Mapping[str, Mapping[str, object]]",
        cast("Mapping[str, object]", params.requested_schema)["properties"],
    )
    agree = cast("Sequence[str]", properties["value"]["enum"])[0]
    assert answer.request_state is not None
    return key, answer.request_state, agree, params.message


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    deleter.register(mcp, transport)
    tool = await mcp.get_tool(deleter.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


class TestWhatItSendsToGraph:
    async def test_it_reads_the_rule_and_then_deletes_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)

        _ = await _delete(client)

        made = cast("Sequence[Call]", graph.calls)
        path = "/v1.0/me/mailFolders/inbox/messageRules/AQAAAJ5dZqSYNTHETIC%3D"
        assert [(call.request.method, call.request.url.raw_path.decode()) for call in made] == [
            ("GET", f"{path}?$select={','.join(RULE_FIELDS)}"),
            ("DELETE", path),
        ]


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        "not_a_rule",
        [
            "outlook:///messages/AAMkAGI2SYNTHETIC-immutable-0001%3D",
            MailFolderHandle("AQMkADAwSYNTHETIC-folder").uri,
            "outlook:///rules/",
            _RULE_ID,
            "Partner mail",
        ],
    )
    async def test_a_ref_that_is_not_a_rule_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, not_a_rule: str
    ) -> None:
        with pytest.raises(ToolError, match="outlook_get_mailbox_settings") as raised:
            _ = await _delete(client, rule_ref=not_a_rule, confirm=_never_asked)

        assert "Nothing was deleted." in str(raised.value)
        assert str(raised.value).endswith(_RETRY)
        assert len(graph.calls) == 0

    async def test_a_read_only_rule_is_refused_unasked_and_never_deleted(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        delete = _ready(graph, _rule(is_read_only=True))

        with pytest.raises(ToolError, match="read-only") as raised:
            _ = await _delete(client, confirm=_never_asked)

        assert str(raised.value).startswith(_NOTHING_DELETED)
        assert str(raised.value).endswith(_RETRY)
        assert delete.call_count == 0


class TestThePersonBetweenTheRequestAndTheDelete:
    async def test_every_delete_asks_and_the_question_names_the_rule(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)
        asked, _bound, capture = _capturing()

        _ = await _delete(client, confirm=capture)

        assert len(asked) == 1
        assert asked[0].startswith("Delete the inbox rule 'Partner mail'?")
        assert "No message is deleted." in asked[0]
        assert "This connector cannot restore a deleted rule." in asked[0]

    async def test_a_rule_with_no_name_is_named_by_its_handle(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, _rule(display_name=None))
        asked, _bound, capture = _capturing()

        _ = await _delete(client, confirm=capture)

        assert _RULE_REF in asked[0]

    async def test_a_refusal_deletes_nothing_after_the_read(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        reads = _reads(graph)
        delete = _deletes(graph)

        with pytest.raises(ToolError, match=_NOTHING_DELETED):
            _ = await _delete(client, confirm=_refuses)

        assert reads.call_count == 1
        assert delete.call_count == 0

    async def test_the_same_rule_read_twice_gives_the_same_agreement(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)
        asked, bound, capture = _capturing()

        _ = await _delete(client, confirm=capture)
        _ = await _delete(client, confirm=capture)

        assert asked[0] == asked[1]
        assert bound[0] == bound[1]

    @pytest.mark.parametrize("changed", _CHANGED_BY_THEN)
    async def test_the_agreement_is_bound_to_the_rule_as_it_was_read(
        self, client: GraphServiceClient, graph: respx.MockRouter, changed: dict[str, object]
    ) -> None:
        reads = _reads(graph)
        _ = _deletes(graph)
        _asked, bound, capture = _capturing()

        _ = await _delete(client, confirm=capture)
        _ = reads.mock(return_value=httpx.Response(200, json=changed))
        _ = await _delete(client, confirm=capture)

        assert bound[0] != bound[1]


class TestTheEraWithAHandshake:
    @pytest.mark.parametrize(
        "answer",
        [
            DeclinedElicitation(),
            CancelledElicitation(),
            AcceptedElicitation(data="keep the rule"),
            MCPError(METHOD_NOT_FOUND, "Method not found"),
        ],
        ids=["declined", "cancelled", "another-answer", "cannot-ask"],
    )
    async def test_no_answer_but_agreement_deletes_anything(
        self, client: GraphServiceClient, graph: respx.MockRouter, answer: object
    ) -> None:
        delete = _ready(graph)

        with pytest.raises(ToolError) as raised:
            _ = await _delete(client, confirm=a_person_agrees(_context(answer)))

        assert str(raised.value).startswith(_NOTHING_DELETED)
        assert delete.call_count == 0

    async def test_agreement_deletes_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        delete = _ready(graph)

        _ = await _delete(
            client, confirm=a_person_agrees(_context(AcceptedElicitation(data="delete the rule")))
        )

        assert delete.call_count == 1


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_reaches_the_delete(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        delete = _ready(graph)

        answer = await _round(client, confirm=a_person_agrees(_modern_context()))

        _key, _state, _agree, message = _the_question(answer)
        assert "Partner mail" in message
        assert delete.call_count == 0

    async def test_the_second_round_deletes_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        delete = _ready(graph)
        key, state, agree, _message = _the_question(
            await _round(client, confirm=a_person_agrees(_modern_context()))
        )

        answer = await _round(client, confirm=a_person_agrees(_agreeing(key, agree, state)))

        assert isinstance(answer, DeletedRule)
        assert delete.call_count == 1

    @pytest.mark.parametrize("changed", _CHANGED_BY_THEN)
    async def test_an_answer_to_a_rule_that_changed_by_then_deletes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter, changed: dict[str, object]
    ) -> None:
        reads = _reads(graph)
        delete = _deletes(graph)
        key, state, agree, _message = _the_question(
            await _round(client, confirm=a_person_agrees(_modern_context()))
        )
        _ = reads.mock(return_value=httpx.Response(200, json=changed))

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await _round(client, confirm=a_person_agrees(_agreeing(key, agree, state)))

        assert delete.call_count == 0


class TestGraphFailures:
    async def test_a_rule_graph_does_not_return_asks_nobody_and_deletes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_RULE_PATH).mock(return_value=httpx.Response(404))
        delete = _deletes(graph)
        asked, _bound, capture = _capturing()

        with pytest.raises(GraphNotFound):
            _ = await _delete(client, confirm=capture)

        assert asked == []
        assert delete.call_count == 0

    async def test_a_rule_that_is_gone_by_the_time_of_the_delete_is_deleted(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        delete = _deletes(graph, status=404)

        answer = await _delete(client)

        assert delete.call_count == 1
        assert answer.deleted is True

    async def test_the_call_example_reaches_graph_and_the_read_is_what_a_403_refuses(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        example = cast("Mapping[str, str]", deleter.GRAPH_CALL_EXAMPLE)
        refused = graph.get("/me/mailFolders/inbox/messageRules/AQAAAJSYNTHETIC-rule-one").mock(
            return_value=httpx.Response(403)
        )

        with pytest.raises(GraphForbidden):
            _ = await _delete(client, rule_ref=example["rule_ref"], confirm=_never_asked)

        assert refused.call_count == 1


class TestWhatItAnswers:
    async def test_the_answer_is_the_rule_as_it_was_immediately_before_the_delete(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)

        answer = await _delete(client)

        assert answer.uri == _RULE_REF
        assert answer.display_name == "Partner mail"
        assert answer.conditions is not None
        assert answer.conditions.model_dump() == {"sender_contains": ["partner"]}
        assert answer.exceptions is None
        assert answer.actions is not None
        assert answer.actions.model_dump() == {"forward_to": [_DANA], "permanent_delete": True}
        assert answer.deleted is True


class TestHowItDeclaresItself:
    def test_the_permission_is_the_one_the_write_needs(self) -> None:
        assert deleter.GRAPH_PERMISSIONS == ("MailboxSettings.ReadWrite",)

    def test_a_repeat_cannot_write_twice_so_no_tool_is_named_to_look_first(self) -> None:
        assert not hasattr(deleter, "CHANGE_SHOWN_BY")

    def test_the_not_found_advice_says_nothing_was_deleted(self) -> None:
        assert "nothing was deleted" in deleter.GRAPH_NOT_FOUND
        assert "already gone" in deleter.GRAPH_NOT_FOUND
        assert deleter.GRAPH_NOT_FOUND.endswith(_RETRY)

    async def test_it_takes_one_rule_handle(self, transport: httpx.AsyncClient) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, object]]", parameters["properties"])
        assert set(properties) == {"rule_ref"}
        assert set(deleter.GRAPH_CALL_EXAMPLE) == {"rule_ref"}
        assert parameters["required"] == ["rule_ref"]
        assert properties["rule_ref"]["minLength"] == 1

    async def test_the_input_schema_is_a_plain_object_at_its_root(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        assert parameters["type"] == "object"
        assert not {"anyOf", "oneOf", "allOf", "not", "enum", "const"} & set(parameters)

    async def test_it_announces_itself_as_a_destructive_write_that_is_safe_to_repeat(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["idempotentHint"]

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

    async def test_the_description_says_it_always_asks_and_that_no_mail_is_lost(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "This tool always asks the user to agree" in description
        assert "no message is deleted" in description
        assert "This connector cannot restore a deleted rule." in description
        assert "This tool refuses a read-only rule." in description
        assert "This call is safe to repeat after a timeout." in description
        assert "outlook_disable_mail_rule turns a rule off and keeps it" in description

    async def test_every_field_of_the_answer_says_what_it_is(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        answer = cast("Mapping[str, object]", tool.output_schema)
        properties = cast("Mapping[str, Mapping[str, object]]", answer["properties"])
        assert set(properties) == {
            "uri",
            "display_name",
            "conditions",
            "exceptions",
            "actions",
            "deleted",
        }
        undescribed = sorted(
            name for name, field in properties.items() if not field.get("description")
        )
        assert undescribed == []
