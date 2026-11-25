import pytest
from fastmcp import Client

from mcp_elicitation import ASKS_CONFIRMATION_KEY
from mcp_elicitation import SKIP_CONFIRMATION_KEY
from tests.server import Mailbox
from tests.server import answering
from tests.server import build_server
from tests.server import returned


def test_the_keys_are_the_ones_mcp_hub_reads() -> None:
    assert ASKS_CONFIRMATION_KEY == "unique.app/mcp-server/asks-confirmation"
    assert SKIP_CONFIRMATION_KEY == "unique.app/mcp-server/skip-confirmation"


async def test_a_tool_that_asks_says_so_in_its_definition() -> None:
    async with Client(build_server(Mailbox())) as client:
        tools = await client.list_tools()

    delete_rule = next(tool for tool in tools if tool.name == "delete_rule")
    assert delete_rule.meta is not None
    assert delete_rule.meta[ASKS_CONFIRMATION_KEY] is True


@pytest.mark.parametrize("value", [False, "true", 1, None])
async def test_only_true_skips_the_confirmation(value: object) -> None:
    mailbox = Mailbox()
    handler, shown = answering({"answer": "confirm"})

    async with Client(build_server(mailbox), elicitation_handler=handler) as client:
        result = await client.call_tool("delete_rule", {}, meta={SKIP_CONFIRMATION_KEY: value})

    assert returned(result) == "deleted, skipped=False"
    assert len(shown) == 1
