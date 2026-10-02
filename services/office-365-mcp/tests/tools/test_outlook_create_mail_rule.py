import json
from collections.abc import Mapping, Sequence
from typing import cast
from urllib.parse import quote

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

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound, GraphUnavailable
from office_365_mcp.shared.handles import MailFolderHandle, MailRuleHandle
from office_365_mcp.shared.rules import MailRule, RuleActionsInput, RuleConditionsInput
from office_365_mcp.shared.seam import WRITE_ADDITIVE, Confirm
from office_365_mcp.tools import outlook_create_mail_rule as creator
from office_365_mcp.tools.outlook_create_mail_rule import a_person_agrees, create_mail_rule

_RULE_ID = "AQAAAJ5dZqSYNTHETIC="
_FOLDER_ID = "AQMkADAwSYNTHETIC-newsletters="
_ARCHIVE_ID = "AQMkADAwSYNTHETIC-archive="

_RULES_PATH = "/me/mailFolders/inbox/messageRules"
_ARCHIVE_PATH = "/me/mailFolders/archive"
_FOLDER_PATH = f"/me/mailFolders/{quote(_FOLDER_ID, safe='')}"

_DANA = "dana@example.invalid"
_ERIN = "erin@example.invalid"
_TEAM = "team@example.invalid"

_NOTHING_CREATED = "No rule was created."

_RETRY = "If you call this tool again with the same arguments, the call will fail the same way."

_MARK_READ = RuleActionsInput(mark_as_read=True)
_FORWARDS = RuleActionsInput(forward_to=[_DANA], stop_processing_rules=True)
_NEWSLETTERS = RuleConditionsInput(sender_contains=["newsletter"])


def _created(payload: Mapping[str, object] | None = None) -> dict[str, object]:
    return {
        "id": _RULE_ID,
        "displayName": "Newsletters",
        "sequence": 2,
        "isEnabled": True,
        "hasError": False,
        "isReadOnly": False,
        "conditions": {"senderContains": ["NEWSLETTER"]},
        "actions": {"markAsRead": True},
        **(payload or {}),
    }


def _folder(folder_id: str, *, hidden: bool = False) -> dict[str, object]:
    return {"id": folder_id, "displayName": "Newsletters", "isHidden": hidden}


def _creates(graph: respx.MockRouter, payload: Mapping[str, object] | None = None) -> respx.Route:
    return graph.post(_RULES_PATH).mock(return_value=httpx.Response(201, json=_created(payload)))


def _reads_folders(graph: respx.MockRouter, *, hidden: bool = False) -> tuple[respx.Route, ...]:
    return (
        graph.get(_ARCHIVE_PATH).mock(
            return_value=httpx.Response(200, json=_folder(_ARCHIVE_ID, hidden=hidden))
        ),
        graph.get(_FOLDER_PATH).mock(
            return_value=httpx.Response(200, json=_folder(_FOLDER_ID, hidden=hidden))
        ),
    )


async def _agrees(question: str, about: str) -> str | None:
    assert question, "the person was asked nothing at all"
    assert about, "the answer was bound to nothing"
    return None


async def _refuses(question: str, about: str) -> str | None:
    assert question
    assert about
    return _NOTHING_CREATED


async def _never_asked(question: str, about: str) -> str | None:
    raise AssertionError(
        f"a rule that needs no question was put to a person: {question!r} ({about})"
    )


async def _round(
    client: GraphServiceClient,
    *,
    display_name: str = "Newsletters",
    sequence: int = 2,
    actions: RuleActionsInput = _MARK_READ,
    conditions: RuleConditionsInput | None = _NEWSLETTERS,
    exceptions: RuleConditionsInput | None = None,
    is_enabled: bool = True,
    confirm: Confirm = _never_asked,
) -> MailRule | InputRequiredResult:
    return await create_mail_rule(
        client,
        display_name=display_name,
        sequence=sequence,
        actions=actions,
        confirm=confirm,
        conditions=conditions,
        exceptions=exceptions,
        is_enabled=is_enabled,
    )


async def _create(
    client: GraphServiceClient,
    *,
    display_name: str = "Newsletters",
    sequence: int = 2,
    actions: RuleActionsInput = _MARK_READ,
    conditions: RuleConditionsInput | None = _NEWSLETTERS,
    exceptions: RuleConditionsInput | None = None,
    is_enabled: bool = True,
    confirm: Confirm = _never_asked,
) -> MailRule:
    answer = await _round(
        client,
        display_name=display_name,
        sequence=sequence,
        actions=actions,
        conditions=conditions,
        exceptions=exceptions,
        is_enabled=is_enabled,
        confirm=confirm,
    )
    assert isinstance(answer, MailRule), "this call was answered with a question"
    return answer


def _sent(route: respx.Route) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(route.calls.last.request.content))


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


def _the_question(answer: MailRule | InputRequiredResult) -> tuple[str, str, str, str]:
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
    creator.register(mcp, transport)
    tool = await mcp.get_tool(creator.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


def _property_names(schema: object) -> set[str]:
    if isinstance(schema, Mapping):
        mapping = cast("Mapping[str, object]", schema)
        named = set(cast("Mapping[str, object]", mapping.get("properties", {})))
        return named.union(*(_property_names(value) for value in mapping.values()))
    if isinstance(schema, list):
        return set[str]().union(*(_property_names(item) for item in cast("list[object]", schema)))
    return set()


class TestWhatItSendsToGraph:
    async def test_it_posts_one_rule_to_the_inbox_rules(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)

        _ = await _create(client)

        made = cast("Sequence[Call]", graph.calls)
        assert [(call.request.method, call.request.url.path) for call in made] == [
            ("POST", "/v1.0/me/mailFolders/inbox/messageRules")
        ]

    async def test_the_body_carries_the_name_the_order_the_state_and_the_parts_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)

        _ = await _create(
            client,
            exceptions=RuleConditionsInput(importance="low", sent_only_to_me=True),
            is_enabled=False,
        )

        assert _sent(create) == {
            "displayName": "Newsletters",
            "sequence": 2,
            "isEnabled": False,
            "conditions": {"senderContains": ["newsletter"]},
            "exceptions": {"importance": "low", "sentOnlyToMe": True},
            "actions": {"markAsRead": True},
        }

    async def test_a_rule_with_no_conditions_sends_none(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)

        _ = await _create(client, conditions=RuleConditionsInput())

        assert "conditions" not in _sent(create)

    async def test_a_well_known_folder_is_read_and_its_id_is_what_the_rule_moves_mail_to(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        archive, _ = _reads_folders(graph)
        create = _creates(graph)

        _ = await _create(client, actions=RuleActionsInput(move_to_folder="archive"))

        assert archive.call_count == 1
        assert archive.calls.last.request.url.params["$select"] == "id,displayName,isHidden"
        assert _sent(create)["actions"] == {"moveToFolder": _ARCHIVE_ID}

    async def test_a_folder_handle_is_read_by_its_id_and_the_rule_copies_mail_there(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _, folder = _reads_folders(graph)
        create = _creates(graph)

        _ = await _create(
            client, actions=RuleActionsInput(copy_to_folder=MailFolderHandle(_FOLDER_ID).uri)
        )

        assert folder.call_count == 1
        assert _sent(create)["actions"] == {"copyToFolder": _FOLDER_ID}

    async def test_the_delete_action_is_the_one_that_moves_mail_to_deleted_items(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)

        _ = await _create(client, actions=RuleActionsInput(delete=True))

        assert _sent(create)["actions"] == {"delete": True}

    async def test_a_forward_address_reaches_graph_without_the_space_around_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)

        _ = await _create(
            client, actions=RuleActionsInput(forward_to=[f"  {_DANA} "]), confirm=_agrees
        )

        assert _sent(create)["actions"] == {"forwardTo": [{"emailAddress": {"address": _DANA}}]}


class TestWhatCannotBeAskedForAtAll:
    async def test_no_property_of_the_schema_erases_mail_permanently(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        named = _property_names(parameters)
        assert {"actions", "forward_to", "delete", "move_to_folder"} <= named
        assert not [name for name in named if "permanent" in name.casefold()]

    async def test_a_permanent_erase_smuggled_into_the_actions_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)
        smuggled = RuleActionsInput.model_validate({"permanentDelete": True, "delete": True})

        _ = await _create(client, actions=smuggled)

        assert _sent(create)["actions"] == {"delete": True}


class TestTheRetryItRefuses:
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_create_graph_answers_503_is_never_posted_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = graph.post(_RULES_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _create(client)

        assert create.call_count == 1


class TestWhatItRefuses:
    @pytest.mark.parametrize(
        ("conditions", "exceptions", "actions"),
        [
            (RuleConditionsInput(from_addresses=["Dana Swope"]), None, _MARK_READ),
            (None, RuleConditionsInput(sent_to_addresses=[f"Team <{_TEAM}>"]), _MARK_READ),
            (None, None, RuleActionsInput(forward_to=[f"{_DANA}, {_ERIN}"])),
            (None, None, RuleActionsInput(redirect_to=["Erin"])),
            (None, None, RuleActionsInput(forward_as_attachment_to=[" "])),
        ],
        ids=["from-name", "sent-to-display", "two-in-one", "redirect-name", "blank"],
    )
    async def test_an_entry_that_is_not_one_address_never_reaches_graph(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        conditions: RuleConditionsInput | None,
        exceptions: RuleConditionsInput | None,
        actions: RuleActionsInput,
    ) -> None:
        with pytest.raises(ToolError, match="one SMTP address") as raised:
            _ = await _create(client, conditions=conditions, exceptions=exceptions, actions=actions)

        assert str(raised.value).startswith(_NOTHING_CREATED)
        assert "If this deployment exposes outlook_find_recipient, use it" in str(raised.value)
        assert len(graph.calls) == 0

    async def test_actions_that_set_nothing_never_reach_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="gives the rule no action") as raised:
            _ = await _create(client, actions=RuleActionsInput())

        assert str(raised.value).startswith(_NOTHING_CREATED)
        assert len(graph.calls) == 0

    @pytest.mark.parametrize(
        "ref",
        ["Newsletters", "Archive", MailRuleHandle(_RULE_ID).uri, _FOLDER_ID],
    )
    async def test_a_folder_that_is_neither_a_handle_nor_a_well_known_name_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, ref: str
    ) -> None:
        with pytest.raises(
            ToolError, match="If this deployment exposes outlook_browse_folders"
        ) as raised:
            _ = await _create(client, actions=RuleActionsInput(move_to_folder=ref))

        assert str(raised.value).startswith(_NOTHING_CREATED)
        assert str(raised.value).endswith(_RETRY)
        assert len(graph.calls) == 0

    async def test_a_hidden_folder_is_refused_after_its_read_and_before_anybody_is_asked(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        archive, _ = _reads_folders(graph, hidden=True)
        create = _creates(graph)

        with pytest.raises(ToolError, match="hidden from the user") as raised:
            _ = await _create(
                client, actions=RuleActionsInput(move_to_folder="archive", forward_to=[_DANA])
            )

        assert str(raised.value).startswith(_NOTHING_CREATED)
        assert archive.call_count == 1
        assert create.call_count == 0


class TestThePersonBetweenTheRequestAndTheRule:
    async def test_a_rule_that_sends_no_mail_on_is_created_without_a_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads_folders(graph)
        create = _creates(graph)

        _ = await _create(
            client,
            actions=RuleActionsInput(
                move_to_folder="archive", delete=True, mark_importance="high", mark_as_read=True
            ),
            confirm=_never_asked,
        )

        assert create.call_count == 1

    @pytest.mark.parametrize(
        ("actions", "words"),
        [
            (RuleActionsInput(forward_to=[_DANA]), f"a copy of each matching message to {_DANA}"),
            (
                RuleActionsInput(forward_as_attachment_to=[_DANA]),
                f"each matching message as an attachment to {_DANA}",
            ),
            (RuleActionsInput(redirect_to=[_DANA]), f"redirects each matching message to {_DANA}"),
        ],
        ids=["forward", "forward-as-attachment", "redirect"],
    )
    async def test_every_action_that_sends_mail_on_asks_and_names_the_address(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        actions: RuleActionsInput,
        words: str,
    ) -> None:
        _ = _creates(graph)
        asked, _bound, capture = _capturing()

        _ = await _create(client, actions=actions, confirm=capture)

        assert len(asked) == 1
        assert asked[0].startswith("Create the inbox rule 'Newsletters'?")
        assert words in asked[0]

    async def test_the_question_names_every_address_of_every_action(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        asked, _bound, capture = _capturing()

        _ = await _create(
            client,
            actions=RuleActionsInput(
                forward_to=[_DANA, _ERIN], redirect_to=[_TEAM], forward_as_attachment_to=[_ERIN]
            ),
            conditions=None,
            confirm=capture,
        )

        question = asked[0]
        assert f"a copy of each matching message to {_DANA} and {_ERIN}" in question
        assert f"each matching message as an attachment to {_ERIN}" in question
        assert f"redirects each matching message to {_TEAM}" in question
        assert "it acts on every incoming message" in question

    async def test_a_refusal_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)

        with pytest.raises(ToolError, match=_NOTHING_CREATED):
            _ = await _create(client, actions=_FORWARDS, confirm=_refuses)

        assert create.call_count == 0

    async def test_the_question_is_asked_after_the_folder_read_and_before_the_create(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        archive, _ = _reads_folders(graph)
        create = _creates(graph)
        made_when_asked: list[tuple[int, int]] = []

        async def watching(question: str, about: str) -> str | None:
            assert question
            assert about
            made_when_asked.append((archive.call_count, create.call_count))
            return None

        _ = await _create(
            client,
            actions=RuleActionsInput(move_to_folder="archive", forward_to=[_DANA]),
            confirm=watching,
        )

        assert made_when_asked == [(1, 0)]

    async def test_the_agreement_is_bound_to_the_whole_rule(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        _asked, bound, capture = _capturing()

        _ = await _create(client, actions=_FORWARDS, confirm=capture)
        _ = await _create(client, actions=_FORWARDS, confirm=capture)
        _ = await _create(
            client,
            actions=RuleActionsInput(forward_to=[_ERIN], stop_processing_rules=True),
            confirm=capture,
        )
        _ = await _create(client, actions=_FORWARDS, conditions=None, confirm=capture)
        _ = await _create(client, actions=_FORWARDS, display_name="Other", confirm=capture)

        assert bound[0] == bound[1]
        assert len(set(bound[1:])) == 4


class TestTheEraWithAHandshake:
    @pytest.mark.parametrize(
        "answer",
        [
            DeclinedElicitation(),
            CancelledElicitation(),
            AcceptedElicitation(data="do not create the rule"),
            MCPError(METHOD_NOT_FOUND, "Method not found"),
        ],
        ids=["declined", "cancelled", "another-answer", "cannot-ask"],
    )
    async def test_no_answer_but_agreement_creates_anything(
        self, client: GraphServiceClient, graph: respx.MockRouter, answer: object
    ) -> None:
        create = _creates(graph)

        with pytest.raises(ToolError) as raised:
            _ = await _create(client, actions=_FORWARDS, confirm=a_person_agrees(_context(answer)))

        assert str(raised.value).startswith(_NOTHING_CREATED)
        assert create.call_count == 0

    async def test_agreement_creates_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)

        _ = await _create(
            client,
            actions=_FORWARDS,
            confirm=a_person_agrees(_context(AcceptedElicitation(data="create the rule"))),
        )

        assert create.call_count == 1


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_reaches_the_create(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)

        answer = await _round(client, actions=_FORWARDS, confirm=a_person_agrees(_modern_context()))

        _key, _state, _agree, message = _the_question(answer)
        assert _DANA in message
        assert "Newsletters" in message
        assert create.call_count == 0

    async def test_the_second_round_creates_once_under_the_agreed_rule(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)
        key, state, agree, _message = _the_question(
            await _round(client, actions=_FORWARDS, confirm=a_person_agrees(_modern_context()))
        )

        answer = await _round(
            client,
            actions=_FORWARDS,
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": agree})},
                    state=state,
                )
            ),
        )

        assert isinstance(answer, MailRule)
        assert create.call_count == 1

    async def test_an_answer_bound_to_another_address_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        create = _creates(graph)
        key, state, agree, _message = _the_question(
            await _round(client, actions=_FORWARDS, confirm=a_person_agrees(_modern_context()))
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await _round(
                client,
                actions=RuleActionsInput(forward_to=[_ERIN], stop_processing_rules=True),
                confirm=a_person_agrees(
                    _modern_context(
                        answers={key: ElicitResult(action="accept", content={"value": agree})},
                        state=state,
                    )
                ),
            )

        assert create.call_count == 0


class TestGraphFailures:
    async def test_a_folder_graph_does_not_return_asks_nobody_and_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ARCHIVE_PATH).mock(return_value=httpx.Response(404))
        create = _creates(graph)
        asked, _bound, capture = _capturing()

        with pytest.raises(GraphNotFound):
            _ = await _create(
                client,
                actions=RuleActionsInput(move_to_folder="archive", forward_to=[_DANA]),
                confirm=capture,
            )

        assert asked == []
        assert create.call_count == 0

    async def test_the_call_example_reaches_graph_and_the_create_is_what_a_403_refuses(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        example = creator.GRAPH_CALL_EXAMPLE
        refused = graph.post(_RULES_PATH).mock(return_value=httpx.Response(403))

        with pytest.raises(GraphForbidden):
            _ = await _create(
                client,
                display_name=cast("str", example["display_name"]),
                sequence=cast("int", example["sequence"]),
                conditions=RuleConditionsInput.model_validate(example["conditions"]),
                actions=RuleActionsInput.model_validate(example["actions"]),
            )

        assert refused.call_count == 1


class TestWhatItAnswers:
    async def test_the_answer_is_the_rule_microsoft_created_with_only_the_parts_it_sets(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)

        answer = await _create(client)

        assert answer.uri == MailRuleHandle(_RULE_ID).uri
        assert answer.display_name == "Newsletters"
        assert answer.sequence == 2
        assert answer.is_enabled is True
        assert answer.conditions is not None
        assert answer.conditions.model_dump() == {"sender_contains": ["NEWSLETTER"]}
        assert answer.exceptions is None
        assert answer.actions is not None
        assert answer.actions.model_dump() == {"mark_as_read": True}

    async def test_an_answer_with_forwarding_names_the_addresses_microsoft_stored(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(
            graph,
            {"actions": {"forwardTo": [{"emailAddress": {"address": _DANA, "name": "Dana"}}]}},
        )

        answer = await _create(client, actions=_FORWARDS, confirm=_agrees)

        assert answer.actions is not None
        assert answer.actions.forward_to == [_DANA]


class TestHowItDeclaresItself:
    def test_the_permissions_cover_the_write_and_the_folder_read(self) -> None:
        assert creator.GRAPH_PERMISSIONS == ("MailboxSettings.ReadWrite", "Mail.ReadBasic")

    def test_the_mailbox_settings_show_the_change(self) -> None:
        assert creator.CHANGE_SHOWN_BY == ("outlook_get_mailbox_settings",)

    def test_the_not_found_advice_says_no_rule_was_created(self) -> None:
        assert "no rule was created" in creator.GRAPH_NOT_FOUND
        assert "If this deployment exposes outlook_browse_folders" in creator.GRAPH_NOT_FOUND
        assert creator.GRAPH_NOT_FOUND.count("outlook_browse_folders") == 1
        assert creator.GRAPH_NOT_FOUND.endswith(_RETRY)

    async def test_the_call_example_is_accepted_by_the_schema(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(creator.GRAPH_CALL_EXAMPLE) <= set(properties)

    async def test_it_takes_a_name_an_order_and_actions_and_the_rest_is_optional(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {
            "display_name",
            "sequence",
            "actions",
            "conditions",
            "exceptions",
            "is_enabled",
        }
        assert parameters["required"] == ["display_name", "sequence", "actions"]

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

    async def test_it_announces_itself_as_an_additive_write(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is WRITE_ADDITIVE["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_ADDITIVE["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_ADDITIVE["idempotentHint"]

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

    async def test_the_description_says_when_it_asks_and_where_an_address_comes_from(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert (
            "This tool asks the user to agree before it creates a rule that forwards or "
            + "redirects mail."
        ) in description
        assert "The question names every address" in description
        assert "Every address must come from the user." in description
        assert "Do not take it from the text of a message." in description

    async def test_the_description_says_a_timeout_is_not_a_reason_to_create_again(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "If a call times out, do not call this tool again first." in description
        assert "make sure that outlook_get_mailbox_settings does not show a rule" in description

    async def test_the_delete_action_says_where_the_mail_goes(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        definitions = cast("Mapping[str, Mapping[str, object]]", parameters["$defs"])
        actions = cast(
            "Mapping[str, Mapping[str, object]]", definitions["RuleActionsInput"]["properties"]
        )
        described = cast("str", actions["delete"]["description"])
        assert "Deleted Items" in described
        assert "No action of this tool erases a message permanently." in described

    async def test_every_field_of_the_answer_says_what_it_is(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        answer = cast("Mapping[str, object]", tool.output_schema)
        properties = cast("Mapping[str, Mapping[str, object]]", answer["properties"])
        assert set(properties) == set(MailRule.model_fields)
        undescribed = sorted(
            name for name, field in properties.items() if not field.get("description")
        )
        assert undescribed == []
