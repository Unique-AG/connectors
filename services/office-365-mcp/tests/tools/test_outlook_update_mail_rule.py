import json
from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import AcceptedElicitation, DeclinedElicitation
from fastmcp.tools import Tool
from mcp.types import ElicitRequest, ElicitRequestFormParams, ElicitResult, InputRequiredResult
from mcp.types.version import LATEST_MODERN_VERSION
from msgraph.graph_service_client import GraphServiceClient
from respx.models import Call

from office_365_mcp.graph_client import GraphFailure, GraphNotFound, GraphSettings
from office_365_mcp.shared.handles import MailFolderHandle, MailRuleHandle
from office_365_mcp.shared.rules import (
    RULE_FIELDS,
    MailRule,
    RuleActionName,
    RuleActionsInput,
    RuleConditionsInput,
)
from office_365_mcp.shared.seam import WRITE_IDEMPOTENT, Confirm
from office_365_mcp.tools import outlook_update_mail_rule as updater
from office_365_mcp.tools.outlook_update_mail_rule import a_person_agrees, update_mail_rule

_RULE_ID = "AQAAAJ5dZqSYNTHETIC="
_OTHER_RULE_ID = "AQAAAJ5dZqSYNTHETIC-other="
_ARCHIVE_ID = "AQMkADAwSYNTHETIC-archive="
_FILED_ID = "AQMkADAwSYNTHETIC-filed="
_COPIED_ID = "AQMkADAwSYNTHETIC-copied="

_RULE_REF = MailRuleHandle(_RULE_ID).uri

_RULE_PATH = "/me/mailFolders/inbox/messageRules/AQAAAJ5dZqSYNTHETIC%3D"
_ARCHIVE_PATH = "/me/mailFolders/archive"

_ADA = "ada@example.invalid"
_DANA = "dana@example.invalid"
_ERIN = "erin@example.invalid"

_NOTHING_CHANGED = "The rule was not changed."

_RETRY = "If you call this tool again with the same arguments, the call will fail the same way."


def _recipient(address: str) -> dict[str, object]:
    return {"emailAddress": {"address": address, "name": None}}


def _rule(
    *,
    display_name: str | None = "Partner mail",
    is_enabled: bool | None = True,
    is_read_only: bool | None = False,
    actions: Mapping[str, object] | None = None,
    conditions: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": _RULE_ID,
        "displayName": display_name,
        "sequence": 3,
        "isEnabled": is_enabled,
        "isReadOnly": is_read_only,
        "hasError": False,
        "conditions": dict(conditions or {"senderContains": ["partner"]}),
        "actions": dict(actions or {"forwardTo": [_recipient(_DANA)]}),
    }


def _reads(graph: respx.MockRouter, payload: Mapping[str, object] | None = None) -> respx.Route:
    return graph.get(_RULE_PATH).mock(
        return_value=httpx.Response(200, json=dict(payload or _rule()))
    )


def _patches(graph: respx.MockRouter, payload: Mapping[str, object] | None = None) -> respx.Route:
    return graph.patch(_RULE_PATH).mock(
        return_value=httpx.Response(200, json=dict(payload or _rule()))
    )


def _ready(graph: respx.MockRouter, payload: Mapping[str, object] | None = None) -> respx.Route:
    _ = _reads(graph, payload)
    return _patches(graph, payload)


async def _agrees(question: str, about: str) -> str | None:
    assert question, "the person was asked nothing at all"
    assert about, "the answer was bound to nothing"
    return None


async def _refuses(question: str, about: str) -> str | None:
    assert question
    assert about
    return _NOTHING_CHANGED


async def _never_asked(question: str, about: str) -> str | None:
    raise AssertionError(
        f"a change that needs no question was put to a person: {question!r} ({about})"
    )


async def _round(
    client: GraphServiceClient,
    *,
    rule_ref: str = _RULE_REF,
    confirm: Confirm = _never_asked,
    display_name: str | None = None,
    sequence: int | None = None,
    is_enabled: bool | None = None,
    conditions: RuleConditionsInput | None = None,
    exceptions: RuleConditionsInput | None = None,
    actions: RuleActionsInput | None = None,
    remove_actions: Sequence[RuleActionName] = (),
) -> MailRule | InputRequiredResult:
    return await update_mail_rule(
        client,
        rule_ref=rule_ref,
        confirm=confirm,
        display_name=display_name,
        sequence=sequence,
        is_enabled=is_enabled,
        conditions=conditions,
        exceptions=exceptions,
        actions=actions,
        remove_actions=remove_actions,
    )


async def _update(
    client: GraphServiceClient,
    *,
    rule_ref: str = _RULE_REF,
    confirm: Confirm = _never_asked,
    display_name: str | None = None,
    sequence: int | None = None,
    is_enabled: bool | None = None,
    conditions: RuleConditionsInput | None = None,
    exceptions: RuleConditionsInput | None = None,
    actions: RuleActionsInput | None = None,
    remove_actions: Sequence[RuleActionName] = (),
) -> MailRule:
    answer = await _round(
        client,
        rule_ref=rule_ref,
        confirm=confirm,
        display_name=display_name,
        sequence=sequence,
        is_enabled=is_enabled,
        conditions=conditions,
        exceptions=exceptions,
        actions=actions,
        remove_actions=remove_actions,
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
    updater.register(mcp, transport)
    tool = await mcp.get_tool(updater.TOOL_NAME)
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
    async def test_it_reads_the_rule_and_then_changes_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)

        _ = await _update(client, display_name="Renamed")

        made = cast("Sequence[Call]", graph.calls)
        path = "/v1.0/me/mailFolders/inbox/messageRules/AQAAAJ5dZqSYNTHETIC%3D"
        assert [(call.request.method, call.request.url.raw_path.decode()) for call in made] == [
            ("GET", f"{path}?$select={','.join(RULE_FIELDS)}"),
            ("PATCH", path),
        ]

    async def test_only_the_parts_the_call_gives_are_on_the_wire(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph)

        _ = await _update(client, display_name="Renamed")

        assert _sent(patch) == {"displayName": "Renamed"}

    async def test_every_part_the_call_gives_is_on_the_wire(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph)

        _ = await _update(
            client,
            display_name="Renamed",
            sequence=1,
            is_enabled=True,
            conditions=RuleConditionsInput(subject_contains=["invoice"]),
            exceptions=RuleConditionsInput(is_automatic_reply=True),
            actions=RuleActionsInput(forward_to=[_ERIN]),
            confirm=_agrees,
        )

        assert _sent(patch) == {
            "displayName": "Renamed",
            "sequence": 1,
            "isEnabled": True,
            "conditions": {"subjectContains": ["invoice"]},
            "exceptions": {"isAutomaticReply": True},
            "actions": {"forwardTo": [{"emailAddress": {"address": _ERIN}}]},
        }

    async def test_new_actions_are_sent_with_the_folder_id_that_was_read(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        archive = graph.get(_ARCHIVE_PATH).mock(
            return_value=httpx.Response(200, json={"id": _ARCHIVE_ID, "isHidden": False})
        )
        patch = _ready(graph, _rule(actions={"stopProcessingRules": True}))

        _ = await _update(
            client, actions=RuleActionsInput(move_to_folder="archive", mark_as_read=True)
        )

        assert archive.call_count == 1
        assert _sent(patch) == {
            "actions": {
                "markAsRead": True,
                "moveToFolder": _ARCHIVE_ID,
                "stopProcessingRules": True,
            }
        }

    async def test_a_change_microsoft_answers_with_no_rule_is_read_back(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        reads = _reads(graph)
        _ = graph.patch(_RULE_PATH).mock(return_value=httpx.Response(204))

        answer = await _update(client, display_name="Renamed")

        assert reads.call_count == 2
        assert answer.uri == _RULE_REF


_FILING = {
    "moveToFolder": _FILED_ID,
    "copyToFolder": _COPIED_ID,
    "assignCategories": ["Partner"],
    "markImportance": "high",
}


class TestWhatItKeeps:
    async def test_new_folder_keeps_the_categories_and_the_importance_of_the_rule(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        archive = graph.get(_ARCHIVE_PATH).mock(
            return_value=httpx.Response(200, json={"id": _ARCHIVE_ID, "isHidden": False})
        )
        patch = _ready(graph, _rule(actions=_FILING))

        _ = await _update(client, actions=RuleActionsInput(move_to_folder="archive"))

        assert archive.call_count == 1
        assert _sent(patch) == {
            "actions": {
                "moveToFolder": _ARCHIVE_ID,
                "copyToFolder": _COPIED_ID,
                "assignCategories": ["Partner"],
                "markImportance": "high",
            }
        }

    async def test_a_kept_folder_id_goes_back_to_graph_without_a_read(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph, _rule(actions=_FILING))

        _ = await _update(client, actions=RuleActionsInput(mark_as_read=True))

        assert _sent(patch) == {"actions": {**_FILING, "markAsRead": True}}
        assert len(graph.calls) == 2

    async def test_a_list_that_the_call_gives_replaces_the_whole_list(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(
            graph,
            _rule(
                actions={"forwardTo": [_recipient(_DANA), _recipient(_ERIN)], "markAsRead": True}
            ),
        )
        asked, _bound, capture = _capturing()

        _ = await _update(client, actions=RuleActionsInput(forward_to=[_ADA]), confirm=capture)

        assert _sent(patch) == {
            "actions": {"forwardTo": [{"emailAddress": {"address": _ADA}}], "markAsRead": True}
        }
        assert _ADA in asked[0]
        assert _DANA not in asked[0]
        assert _ERIN not in asked[0]

    async def test_the_actions_that_are_named_in_remove_actions_are_left_out(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(
            graph,
            _rule(
                actions={
                    "forwardTo": [_recipient(_DANA)],
                    "markAsRead": True,
                    "markImportance": "high",
                }
            ),
        )

        _ = await _update(client, remove_actions=["forward_to"])

        assert _sent(patch) == {"actions": {"markAsRead": True, "markImportance": "high"}}

    async def test_an_action_the_rule_does_not_have_is_removed_without_a_change(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph, _rule(actions={"markAsRead": True}))

        _ = await _update(client, remove_actions=["delete"])

        assert _sent(patch) == {"actions": {"markAsRead": True}}

    async def test_a_given_action_and_a_removed_action_are_both_applied(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph, _rule(actions={"markAsRead": True, "stopProcessingRules": True}))

        _ = await _update(
            client,
            actions=RuleActionsInput(mark_importance="low"),
            remove_actions=["stop_processing_rules"],
        )

        assert _sent(patch) == {"actions": {"markAsRead": True, "markImportance": "low"}}

    async def test_a_flag_that_graph_reports_as_false_is_not_sent_back(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(
            graph,
            _rule(
                actions={
                    "markAsRead": True,
                    "delete": False,
                    "permanentDelete": False,
                    "assignCategories": [],
                    "stopProcessingRules": False,
                }
            ),
        )

        _ = await _update(client, actions=RuleActionsInput(mark_importance="high"))

        assert _sent(patch) == {"actions": {"markAsRead": True, "markImportance": "high"}}

    async def test_actions_that_set_nothing_change_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph)

        _ = await _update(client, display_name="Renamed", actions=RuleActionsInput())

        assert _sent(patch) == {"displayName": "Renamed"}


class TestTheRetryItRefuses:
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_change_microsoft_answers_503_to_is_sent_exactly_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        patch = graph.patch(_RULE_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphFailure):
            _ = await _update(client, display_name="Renamed")

        assert patch.call_count == 1
        assert GraphSettings().max_retries > 0, "no retries are configured, so this proves nothing"


class TestWhatItRefusesBeforeGraph:
    @pytest.mark.parametrize(
        "not_a_rule",
        [
            "outlook:///messages/AAMkAGI2SYNTHETIC-immutable-0001%3D",
            MailFolderHandle(_ARCHIVE_ID).uri,
            "outlook:///rules/",
            _RULE_ID,
            "Partner mail",
        ],
    )
    async def test_a_ref_that_is_not_a_rule_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, not_a_rule: str
    ) -> None:
        with pytest.raises(ToolError, match="outlook_get_mailbox_settings"):
            _ = await _update(client, rule_ref=not_a_rule, display_name="Renamed")

        assert len(graph.calls) == 0

    async def test_a_call_that_gives_nothing_to_change_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="nothing to change"):
            _ = await _update(client)

        assert len(graph.calls) == 0

    @pytest.mark.parametrize("part", ["conditions", "exceptions"])
    async def test_a_predicates_object_that_sets_nothing_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, part: str
    ) -> None:
        empty = {part: RuleConditionsInput()}

        with pytest.raises(ToolError, match="sets no predicate") as raised:
            _ = await _update(
                client,
                conditions=empty.get("conditions"),
                exceptions=empty.get("exceptions"),
            )

        assert str(raised.value).startswith(_NOTHING_CHANGED)
        assert len(graph.calls) == 0

    async def test_actions_that_set_nothing_are_nothing_to_change(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="nothing to change"):
            _ = await _update(client, actions=RuleActionsInput())

        assert len(graph.calls) == 0

    async def test_an_action_that_is_given_and_removed_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="both name `forward_to`, `mark_as_read`") as raised:
            _ = await _update(
                client,
                actions=RuleActionsInput(mark_as_read=True, forward_to=[_ERIN]),
                remove_actions=["mark_as_read", "forward_to", "delete"],
            )

        assert str(raised.value).startswith(_NOTHING_CHANGED)
        assert len(graph.calls) == 0

    async def test_a_ref_that_is_not_a_rule_handle_ends_with_the_one_retry_sentence(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError) as raised:
            _ = await _update(client, rule_ref="Partner mail", display_name="Renamed")

        assert str(raised.value).endswith(_RETRY)

    async def test_an_entry_that_is_not_one_address_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="one SMTP address") as raised:
            _ = await _update(client, actions=RuleActionsInput(redirect_to=["Dana Swope"]))

        assert str(raised.value).startswith(_NOTHING_CHANGED)
        assert len(graph.calls) == 0

    async def test_a_folder_that_is_not_a_folder_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="If this deployment exposes outlook_browse_folders"):
            _ = await _update(client, actions=RuleActionsInput(copy_to_folder="Archive"))

        assert len(graph.calls) == 0


class TestWhatItRefusesAfterTheRead:
    async def test_a_read_only_rule_is_read_and_never_changed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph, _rule(is_read_only=True))

        with pytest.raises(ToolError, match="read-only") as raised:
            _ = await _update(client, is_enabled=False)

        assert str(raised.value).startswith(_NOTHING_CHANGED)
        assert patch.call_count == 0

    async def test_new_actions_for_a_rule_that_erases_permanently_are_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph, _rule(actions={"permanentDelete": True}))

        with pytest.raises(ToolError, match="erases each matching message permanently") as raised:
            _ = await _update(client, actions=RuleActionsInput(delete=True))

        assert "call again without `actions`" in str(raised.value)
        assert patch.call_count == 0

    async def test_other_changes_to_a_rule_that_erases_permanently_keep_and_report_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        erasing = _rule(actions={"permanentDelete": True})
        patch = _ready(graph, erasing)

        answer = await _update(client, display_name="Renamed")

        assert _sent(patch) == {"displayName": "Renamed"}
        assert answer.actions is not None
        assert answer.actions.permanent_delete is True

    async def test_removing_the_last_action_is_refused_and_nothing_is_changed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph)

        with pytest.raises(ToolError, match="gives the rule no action") as raised:
            _ = await _update(client, remove_actions=["forward_to"])

        assert str(raised.value).startswith(_NOTHING_CHANGED)
        assert patch.call_count == 0

    async def test_actions_that_graph_reports_as_false_are_no_action_left(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(
            graph,
            _rule(actions={"forwardTo": [_recipient(_DANA)], "delete": False, "markAsRead": False}),
        )

        with pytest.raises(ToolError, match="gives the rule no action"):
            _ = await _update(client, remove_actions=["forward_to"])

        assert patch.call_count == 0

    async def test_removing_an_action_of_a_rule_that_erases_permanently_is_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph, _rule(actions={"permanentDelete": True, "markAsRead": True}))

        with pytest.raises(ToolError, match="erases each matching message permanently") as raised:
            _ = await _update(client, remove_actions=["mark_as_read"])

        assert "call again without `actions` and `remove_actions`" in str(raised.value)
        assert patch.call_count == 0

    async def test_a_hidden_folder_is_refused_and_nothing_is_changed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_ARCHIVE_PATH).mock(
            return_value=httpx.Response(200, json={"id": _ARCHIVE_ID, "isHidden": True})
        )
        patch = _ready(graph)

        with pytest.raises(ToolError, match="hidden from the user"):
            _ = await _update(client, actions=RuleActionsInput(move_to_folder="archive"))

        assert patch.call_count == 0

    async def test_a_rule_graph_does_not_return_asks_nobody_and_changes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_RULE_PATH).mock(return_value=httpx.Response(404))
        patch = _patches(graph)
        asked, _bound, capture = _capturing()

        with pytest.raises(GraphNotFound):
            _ = await _update(client, is_enabled=True, confirm=capture)

        assert asked == []
        assert patch.call_count == 0


class TestWhenItAsksThePerson:
    async def test_turning_on_a_rule_that_forwards_asks_and_names_the_address(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, _rule(is_enabled=False))
        asked, _bound, capture = _capturing()

        _ = await _update(client, is_enabled=True, confirm=capture)

        assert len(asked) == 1
        assert asked[0].startswith("Change the inbox rule 'Partner mail'?")
        assert f"a copy of each matching message to {_DANA}" in asked[0]

    async def test_new_actions_that_redirect_ask_and_name_the_kept_forward_too(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)
        asked, _bound, capture = _capturing()

        _ = await _update(client, actions=RuleActionsInput(redirect_to=[_ERIN]), confirm=capture)

        assert f"redirects each matching message to {_ERIN}" in asked[0]
        assert f"a copy of each matching message to {_DANA}" in asked[0]

    async def test_a_kept_forward_is_named_when_the_call_renames_and_turns_the_rule_on(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, _rule(is_enabled=False))
        asked, _bound, capture = _capturing()

        _ = await _update(
            client,
            display_name="Renamed",
            is_enabled=True,
            actions=RuleActionsInput(mark_importance="high"),
            confirm=capture,
        )

        assert len(asked) == 1
        assert asked[0].startswith("Change the inbox rule 'Renamed'?")
        assert f"a copy of each matching message to {_DANA}" in asked[0]

    async def test_removing_an_action_that_leaves_a_forward_asks_and_names_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph, _rule(actions={"forwardTo": [_recipient(_DANA)], "markAsRead": True}))
        asked, _bound, capture = _capturing()

        _ = await _update(client, remove_actions=["mark_as_read"], confirm=capture)

        assert len(asked) == 1
        assert f"a copy of each matching message to {_DANA}" in asked[0]
        assert patch.call_count == 1

    async def test_new_conditions_on_a_rule_that_forwards_ask(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)
        asked, _bound, capture = _capturing()

        _ = await _update(
            client, conditions=RuleConditionsInput(has_attachments=True), confirm=capture
        )

        assert len(asked) == 1
        assert "match its conditions" in asked[0]

    @pytest.mark.parametrize(
        ("current", "change"),
        [
            (_rule(), {"display_name": "Renamed"}),
            (_rule(), {"sequence": 1}),
            (_rule(), {"is_enabled": False}),
            (_rule(is_enabled=False), {"conditions": RuleConditionsInput(sent_to_me=True)}),
            (
                _rule(actions={"forwardTo": [_recipient(_DANA)], "markAsRead": True}),
                {"remove_actions": ["forward_to"]},
            ),
            (_rule(actions={"markAsRead": True}, is_enabled=False), {"is_enabled": True}),
        ],
        ids=[
            "rename",
            "reorder",
            "turn-off",
            "stays-off",
            "stops-forwarding",
            "sends-nothing-on",
        ],
    )
    async def test_a_change_that_sends_no_more_mail_on_asks_nobody(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        current: Mapping[str, object],
        change: Mapping[str, object],
    ) -> None:
        patch = _ready(graph, current)

        _ = await _update(
            client,
            display_name=cast("str | None", change.get("display_name")),
            sequence=cast("int | None", change.get("sequence")),
            is_enabled=cast("bool | None", change.get("is_enabled")),
            conditions=cast("RuleConditionsInput | None", change.get("conditions")),
            actions=cast("RuleActionsInput | None", change.get("actions")),
            remove_actions=cast("Sequence[RuleActionName]", change.get("remove_actions", ())),
            confirm=_never_asked,
        )

        assert patch.call_count == 1

    async def test_a_refusal_changes_nothing_after_the_read(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        reads = _reads(graph, _rule(is_enabled=False))
        patch = _patches(graph)

        with pytest.raises(ToolError, match=_NOTHING_CHANGED):
            _ = await _update(client, is_enabled=True, confirm=_refuses)

        assert reads.call_count == 1
        assert patch.call_count == 0

    async def test_the_agreement_is_bound_to_the_rule_and_the_whole_change(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)
        _ = graph.get("/me/mailFolders/inbox/messageRules/AQAAAJ5dZqSYNTHETIC-other%3D").mock(
            return_value=httpx.Response(200, json=_rule())
        )
        _ = graph.patch("/me/mailFolders/inbox/messageRules/AQAAAJ5dZqSYNTHETIC-other%3D").mock(
            return_value=httpx.Response(200, json=_rule())
        )
        _asked, bound, capture = _capturing()
        forward = RuleActionsInput(forward_to=[_ERIN])

        _ = await _update(client, actions=forward, confirm=capture)
        _ = await _update(client, actions=forward, confirm=capture)
        _ = await _update(client, actions=RuleActionsInput(forward_to=[_DANA]), confirm=capture)
        _ = await _update(client, actions=forward, display_name="Renamed", confirm=capture)
        _ = await _update(
            client, rule_ref=MailRuleHandle(_OTHER_RULE_ID).uri, actions=forward, confirm=capture
        )

        assert bound[0] == bound[1]
        assert len(set(bound[1:])) == 4

    async def test_the_agreement_is_bound_to_the_actions_that_the_call_removes(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, _rule(actions={"forwardTo": [_recipient(_DANA)], "markAsRead": True}))
        _asked, bound, capture = _capturing()

        _ = await _update(client, remove_actions=["mark_as_read"], confirm=capture)
        _ = await _update(client, remove_actions=["mark_as_read", "mark_as_read"], confirm=capture)
        _ = await _update(
            client, actions=RuleActionsInput(mark_as_read=True), is_enabled=True, confirm=capture
        )
        _ = await _update(client, remove_actions=["stop_processing_rules"], confirm=capture)

        assert bound[0] == bound[1]
        assert len(set(bound)) == 3


class TestTheEraWithAHandshake:
    async def test_a_decline_changes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph, _rule(is_enabled=False))

        with pytest.raises(ToolError) as raised:
            _ = await _update(
                client, is_enabled=True, confirm=a_person_agrees(_context(DeclinedElicitation()))
            )

        assert str(raised.value).startswith(_NOTHING_CHANGED)
        assert patch.call_count == 0

    async def test_agreement_changes_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph, _rule(is_enabled=False))

        _ = await _update(
            client,
            is_enabled=True,
            confirm=a_person_agrees(_context(AcceptedElicitation(data="change the rule"))),
        )

        assert patch.call_count == 1


class TestTheEraWithNoBackChannel:
    async def test_the_second_round_changes_once_under_the_agreed_change(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph, _rule(is_enabled=False))
        first = await _round(client, is_enabled=True, confirm=a_person_agrees(_modern_context()))
        key, state, agree, message = _the_question(first)
        assert _DANA in message
        assert patch.call_count == 0

        answer = await _round(
            client,
            is_enabled=True,
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": agree})},
                    state=state,
                )
            ),
        )

        assert isinstance(answer, MailRule)
        assert patch.call_count == 1

    async def test_an_answer_bound_to_another_change_changes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        patch = _ready(graph, _rule(is_enabled=False))
        key, state, agree, _message = _the_question(
            await _round(client, is_enabled=True, confirm=a_person_agrees(_modern_context()))
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await _round(
                client,
                is_enabled=True,
                display_name="Renamed",
                confirm=a_person_agrees(
                    _modern_context(
                        answers={key: ElicitResult(action="accept", content={"value": agree})},
                        state=state,
                    )
                ),
            )

        assert patch.call_count == 0


class TestWhatItAnswers:
    async def test_the_answer_is_the_rule_microsoft_returned_after_the_change(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _patches(
            graph,
            _rule(display_name="Renamed", actions={"moveToFolder": _ARCHIVE_ID}),
        )

        answer = await _update(client, display_name="Renamed")

        assert answer.uri == _RULE_REF
        assert answer.display_name == "Renamed"
        assert answer.conditions is not None
        assert answer.conditions.model_dump() == {"sender_contains": ["partner"]}
        assert answer.actions is not None
        assert answer.actions.model_dump() == {"move_to_folder": _ARCHIVE_ID}


class TestHowItDeclaresItself:
    def test_the_permission_is_the_one_the_write_needs(self) -> None:
        assert updater.GRAPH_PERMISSIONS == ("MailboxSettings.ReadWrite",)

    def test_a_repeat_cannot_write_twice_so_no_tool_is_named_to_look_first(self) -> None:
        assert not hasattr(updater, "CHANGE_SHOWN_BY")

    def test_the_not_found_advice_names_both_causes(self) -> None:
        assert "the rule was not changed" in updater.GRAPH_NOT_FOUND
        assert "If this deployment exposes outlook_browse_folders" in updater.GRAPH_NOT_FOUND
        assert updater.GRAPH_NOT_FOUND.count("outlook_browse_folders") == 1
        assert "outlook_get_mailbox_settings" in updater.GRAPH_NOT_FOUND

    def test_the_not_found_advice_ends_with_the_one_retry_sentence(self) -> None:
        assert updater.GRAPH_NOT_FOUND.endswith(_RETRY)

    async def test_it_takes_a_rule_and_every_part_of_it_is_optional(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {
            "rule_ref",
            "display_name",
            "sequence",
            "is_enabled",
            "conditions",
            "exceptions",
            "actions",
            "remove_actions",
        }
        assert parameters["required"] == ["rule_ref"]
        assert set(updater.GRAPH_CALL_EXAMPLE) <= set(properties)

    async def test_no_property_of_the_schema_erases_mail_permanently(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        named = _property_names(parameters)
        assert "forward_to" in named
        assert not [name for name in named if "permanent" in name.casefold()]

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

    async def test_it_says_it_writes_and_that_writing_the_same_change_twice_is_safe(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is WRITE_IDEMPOTENT["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_IDEMPOTENT["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_IDEMPOTENT["idempotentHint"]

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

    async def test_the_description_says_when_it_asks_what_it_refuses_and_how_to_retry(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert "This tool changes only the parts that the call gives" in description
        assert "asks the user to agree when the rule runs and forwards or redirects mail" in (
            description
        )
        assert "Every address must come from the user." in description
        assert "This tool refuses a read-only rule." in description
        assert "refuses `actions` and `remove_actions` for a rule that erases mail" in description
        assert "Each action that you give in `actions` replaces the same action" in description
        assert "keeps every other action, except the actions that `remove_actions` names" in (
            description
        )
        assert "This call is safe to repeat after a timeout." in description

    async def test_the_actions_field_says_that_a_given_action_replaces_only_that_action(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, object]]", parameters["properties"])
        described = cast("str", properties["actions"]["description"])
        assert "replaces the same action of the rule, and a list replaces the whole list" in (
            described
        )
        assert "keeps every other action, except those that `remove_actions` names" in described
        assert "replace all the current actions" not in described

    async def test_the_remove_actions_field_offers_exactly_the_actions_a_call_can_give(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, object]]", parameters["properties"])
        field = properties["remove_actions"]
        definitions = cast("Mapping[str, Mapping[str, object]]", parameters["$defs"])
        assert field["default"] == []
        assert set(cast("Sequence[str]", definitions["RuleActionName"]["enum"])) == set(
            RuleActionsInput.model_fields
        )
        assert 15 <= len(cast("str", field["description"]).split()) <= 60

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
