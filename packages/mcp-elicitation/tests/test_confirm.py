import asyncio

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from mcp.types import ElicitRequestFormParams
from mcp.types import ElicitResult
from mcp_configs import ElicitationSettings

from mcp_elicitation import SKIP_CONFIRMATION_KEY
from tests.server import ERAS
from tests.server import Era
from tests.server import Mailbox
from tests.server import answering
from tests.server import build_server
from tests.server import returned


@pytest.mark.parametrize("era", ERAS)
async def test_the_tool_goes_ahead_when_the_person_agrees(era: Era) -> None:
    mailbox = Mailbox()
    handler, shown = answering({"answer": "confirm"})

    async with Client(build_server(mailbox), mode=era, elicitation_handler=handler) as client:
        result = await client.call_tool("delete_rule", {})

    assert returned(result) == "deleted, skipped=False"
    assert mailbox.deleted == ["Newsletters"]
    assert shown[0].message == 'Delete the inbox rule "Newsletters"?'


@pytest.mark.parametrize("era", ERAS)
async def test_the_form_is_one_required_choice_without_a_default(era: Era) -> None:
    handler, shown = answering({"answer": "confirm"})

    async with Client(build_server(Mailbox()), mode=era, elicitation_handler=handler) as client:
        await client.call_tool("delete_rule", {})

    assert shown[0].requested_schema == {
        "type": "object",
        "properties": {
            "answer": {
                "type": "string",
                "title": "Answer",
                "oneOf": [
                    {"const": "confirm", "title": "Delete the rule"},
                    {"const": "cancel", "title": "Keep the rule"},
                ],
            }
        },
        "required": ["answer"],
    }


@pytest.mark.parametrize("era", ERAS)
@pytest.mark.parametrize(
    "answer",
    [
        ElicitResult(action="accept", content={"answer": "cancel"}),
        ElicitResult(action="accept", content={}),
        ElicitResult(action="accept", content=None),
        ElicitResult(action="decline"),
        ElicitResult(action="cancel"),
    ],
    ids=["picked-keep", "accepted-empty", "accepted-unseen", "declined", "dismissed"],
)
async def test_anything_but_an_explicit_agree_refuses(era: Era, answer: ElicitResult) -> None:
    mailbox = Mailbox()
    handler, _ = answering(answer)

    async with Client(build_server(mailbox), mode=era, elicitation_handler=handler) as client:
        with pytest.raises(ToolError, match="The rule was not deleted. The person was asked"):
            await client.call_tool("delete_rule", {})

    assert mailbox.deleted == []


@pytest.mark.parametrize("era", ERAS)
async def test_skip_confirmation_goes_ahead_without_asking(era: Era) -> None:
    mailbox = Mailbox()
    handler, shown = answering()

    async with Client(build_server(mailbox), mode=era, elicitation_handler=handler) as client:
        result = await client.call_tool("delete_rule", {}, meta={SKIP_CONFIRMATION_KEY: True})

    assert returned(result) == "deleted, skipped=True"
    assert mailbox.deleted == ["Newsletters"]
    assert shown == []


@pytest.mark.parametrize("era", ERAS)
async def test_a_client_that_cannot_ask_is_refused(era: Era) -> None:
    mailbox = Mailbox()

    async with Client(build_server(mailbox), mode=era) as client:
        with pytest.raises(ToolError, match="this client cannot ask one"):
            await client.call_tool("delete_rule", {})

    assert mailbox.deleted == []


@pytest.mark.parametrize("era", ERAS)
async def test_without_raising_the_tool_gets_the_refusal(era: Era) -> None:
    mailbox = Mailbox()
    handler, _ = answering({"answer": "cancel"})

    async with Client(build_server(mailbox), mode=era, elicitation_handler=handler) as client:
        result = await client.call_tool("delete_rule_softly", {})

    assert returned(result) == "refused: declined"
    assert mailbox.deleted == []


async def test_a_person_who_does_not_answer_in_time_is_refused() -> None:
    mailbox = Mailbox()

    async def never_answers(
        _message: str, _response_type: object, _params: ElicitRequestFormParams, _context: object
    ) -> ElicitResult:
        await asyncio.sleep(5)
        return ElicitResult(action="accept", content={"answer": "confirm"})

    server = build_server(mailbox, settings=ElicitationSettings(timeout_before_cancel_seconds=0.1))
    async with Client(server, mode="legacy", elicitation_handler=never_answers) as client:
        with pytest.raises(ToolError, match="did not answer in time"):
            await client.call_tool("delete_rule", {})

    assert mailbox.deleted == []
