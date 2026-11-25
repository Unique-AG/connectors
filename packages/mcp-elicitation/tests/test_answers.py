"""On 2026-07-28 an answer comes back in a later call. These are the rules it has to pass."""

import pytest
from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport
from key_value.aio.stores.memory import MemoryStore
from mcp.shared.exceptions import MCPError
from mcp.types import CallToolResult
from mcp.types import ElicitRequest
from mcp.types import ElicitResult
from mcp.types import InputRequiredResult
from mcp.types import TextContent
from mcp_configs import ElicitationSettings
from pydantic import SecretStr

from tests.server import Mailbox
from tests.server import answering
from tests.server import build_server

SHARED_KEYS = [SecretStr("k" * 32)]


def _client(
    mailbox: Mailbox,
    *,
    settings: ElicitationSettings | None = None,
    store: MemoryStore | None = None,
) -> Client[FastMCPTransport]:
    """A 2026-07-28 client that can elicit. These tests answer by hand, so it is never asked."""
    handler, _ = answering()
    server = build_server(mailbox, settings=settings, store=store)
    return Client(server, elicitation_handler=handler)


async def _ask(client: Client[FastMCPTransport]) -> InputRequiredResult:
    asked = await client.session.call_tool("delete_rule", {}, allow_input_required=True)
    assert isinstance(asked, InputRequiredResult)
    return asked


async def _answer(
    client: Client[FastMCPTransport], asked: InputRequiredResult, answer: str
) -> CallToolResult | InputRequiredResult:
    assert asked.input_requests is not None
    [key] = asked.input_requests
    return await client.session.call_tool(
        "delete_rule",
        {},
        input_responses={key: ElicitResult(action="accept", content={"answer": answer})},
        request_state=asked.request_state,
        allow_input_required=True,
    )


async def test_an_answer_is_used_once() -> None:
    mailbox = Mailbox()

    async with _client(mailbox) as client:
        asked = await _ask(client)
        first = await _answer(client, asked, "confirm")
        second = await _answer(client, asked, "confirm")

    assert isinstance(first, CallToolResult)
    assert first.is_error is False
    assert isinstance(second, CallToolResult)
    assert second.is_error is True
    [refusal] = second.content
    assert isinstance(refusal, TextContent)
    assert "no answer this tool can use came back" in refusal.text
    assert mailbox.deleted == ["Newsletters"]


async def test_an_answer_to_what_the_person_no_longer_sees_asks_again() -> None:
    mailbox = Mailbox()

    async with _client(mailbox) as client:
        asked = await _ask(client)
        mailbox.rule_name = "Invoices"
        result = await _answer(client, asked, "confirm")

    assert isinstance(result, InputRequiredResult)
    assert result.input_requests is not None
    [request] = result.input_requests.values()
    assert isinstance(request, ElicitRequest)
    assert request.params.message == 'Delete the inbox rule "Invoices"?'
    assert mailbox.deleted == []


async def test_with_shared_keys_another_replica_takes_the_answer() -> None:
    settings = ElicitationSettings(request_state_keys=SHARED_KEYS)
    store = MemoryStore()
    mailbox = Mailbox()

    async with _client(mailbox, settings=settings, store=store) as first:
        asked = await _ask(first)
    async with _client(mailbox, settings=settings, store=store) as second:
        result = await _answer(second, asked, "confirm")

    assert isinstance(result, CallToolResult)
    assert result.is_error is False
    assert mailbox.deleted == ["Newsletters"]


async def test_without_shared_keys_another_replica_refuses_the_answer() -> None:
    store = MemoryStore()
    mailbox = Mailbox()

    async with _client(mailbox, store=store) as first:
        asked = await _ask(first)
    async with _client(mailbox, store=store) as second:
        with pytest.raises(MCPError, match="Invalid or expired requestState"):
            await _answer(second, asked, "confirm")

    assert mailbox.deleted == []
