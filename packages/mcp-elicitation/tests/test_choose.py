from typing import cast

import pytest
from fastmcp import Client
from fastmcp.client.client import CallToolResult

from mcp_elicitation import SKIP_CONFIRMATION_KEY
from tests.server import ERAS
from tests.server import Era
from tests.server import Mailbox
from tests.server import answering
from tests.server import build_server
from tests.server import form_field
from tests.server import returned


def _left_to_the_model(result: CallToolResult) -> dict[str, object]:
    """The `NeedsChoice` a tool returned. A tool that may also return text wraps it in `result`."""
    needs_choice = cast("dict[str, object]", returned(result))
    assert needs_choice["status"] == "needs_choice"
    return needs_choice


@pytest.mark.parametrize("era", ERAS)
async def test_choose_one_returns_the_option_picked(era: Era) -> None:
    mailbox = Mailbox()
    handler, shown = answering({"choice": "f2"})

    async with Client(build_server(mailbox), mode=era, elicitation_handler=handler) as client:
        result = await client.call_tool("empty_folder", {})

    assert returned(result) == "emptied f2"
    assert shown[0].requested_schema["required"] == ["choice"]
    assert form_field(shown[0], "choice")["oneOf"] == [
        {"const": "f1", "title": "Inbox/XYZ (822 mails)"},
        {"const": "f2", "title": "Archive/XYZ (3 mails)"},
        {"const": "f3", "title": "Shared/XYZ (40 mails)"},
    ]


@pytest.mark.parametrize("era", ERAS)
async def test_an_answer_that_is_not_an_option_leaves_the_choice_to_the_model(era: Era) -> None:
    mailbox = Mailbox()
    handler, _ = answering({"choice": "f9"})

    async with Client(build_server(mailbox), mode=era, elicitation_handler=handler) as client:
        result = await client.call_tool("empty_folder", {})

    needs_choice = _left_to_the_model(result)
    assert needs_choice["reason"] == "declined"
    options = cast("list[dict[str, str]]", needs_choice["options"])
    assert [option["ref"] for option in options] == ["f1", "f2", "f3"]
    assert mailbox.deleted == []


@pytest.mark.parametrize("era", ERAS)
async def test_skip_confirmation_leaves_the_choice_to_the_model_without_asking(era: Era) -> None:
    handler, shown = answering()

    async with Client(build_server(Mailbox()), mode=era, elicitation_handler=handler) as client:
        result = await client.call_tool("empty_folder", {}, meta={SKIP_CONFIRMATION_KEY: True})

    needs_choice = _left_to_the_model(result)
    assert needs_choice["reason"] == "skipped"
    assert needs_choice["multiple"] is False
    assert shown == []


@pytest.mark.parametrize("era", ERAS)
async def test_a_client_that_cannot_ask_leaves_the_choice_to_the_model(era: Era) -> None:
    async with Client(build_server(Mailbox()), mode=era) as client:
        result = await client.call_tool("empty_folder", {})

    assert _left_to_the_model(result)["reason"] == "unavailable"


@pytest.mark.parametrize("era", ERAS)
async def test_choose_many_returns_every_option_picked(era: Era) -> None:
    mailbox = Mailbox()
    handler, shown = answering({"choices": ["f1", "f3"]})

    async with Client(build_server(mailbox), mode=era, elicitation_handler=handler) as client:
        result = await client.call_tool("empty_folders", {})

    assert returned(result) == "emptied f1,f3"
    choices = form_field(shown[0], "choices")
    assert choices["type"] == "array"
    assert (choices["minItems"], choices["maxItems"]) == (2, 2)
    assert choices["items"] == {
        "anyOf": [
            {"const": "f1", "title": "Inbox/XYZ (822 mails)"},
            {"const": "f2", "title": "Archive/XYZ (3 mails)"},
            {"const": "f3", "title": "Shared/XYZ (40 mails)"},
        ]
    }


@pytest.mark.parametrize("era", ERAS)
@pytest.mark.parametrize(
    "picked", [["f1"], ["f1", "f2", "f3"], ["f1", "f1"], ["f1", "f9"], []], ids=str
)
async def test_choose_many_refuses_a_pick_outside_the_bounds(era: Era, picked: list[str]) -> None:
    mailbox = Mailbox()
    handler, _ = answering({"choices": picked})

    async with Client(build_server(mailbox), mode=era, elicitation_handler=handler) as client:
        result = await client.call_tool("empty_folders", {})

    assert _left_to_the_model(result)["multiple"] is True
    assert mailbox.deleted == []


@pytest.mark.parametrize("era", ERAS)
async def test_a_tool_can_ask_twice_in_one_call(era: Era) -> None:
    mailbox = Mailbox()
    handler, shown = answering({"choice": "f3"}, {"answer": "confirm"})

    async with Client(build_server(mailbox), mode=era, elicitation_handler=handler) as client:
        result = await client.call_tool("pick_then_confirm", {})

    assert returned(result) == "emptied f3"
    assert [form.message for form in shown] == ["Which folder?", "Delete all mails in f3?"]
    assert mailbox.deleted == ["f3"]
