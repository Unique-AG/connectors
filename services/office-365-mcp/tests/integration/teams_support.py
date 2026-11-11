from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

import pytest
from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from mcp.types import ElicitRequestFormParams, ElicitRequestParams, ElicitResult
from mcp.types.version import LATEST_MODERN_VERSION

from tests.integration.test_scenarios import Person, build_server, items, mapping, patch_obo

__all__ = ["Says", "call_on_the_newer_protocol", "refused_on_the_newer_protocol"]


@dataclass
class Says:
    choice: int | str
    asked: list[str] = field(default_factory=list)

    async def __call__(
        self, message: str, _type: type | None, params: ElicitRequestParams, _context: object
    ) -> ElicitResult[dict[str, str]]:
        self.asked.append(message)
        assert isinstance(params, ElicitRequestFormParams)
        answers = mapping(mapping(cast("object", params.requested_schema["properties"]))["value"])
        word = items(answers["enum"])[self.choice] if isinstance(self.choice, int) else self.choice
        return ElicitResult(action="accept", content={"value": str(word)})


async def call_on_the_newer_protocol(
    tool: str, /, *, person: Person | Says, **arguments: object
) -> Mapping[str, object]:
    with pytest.MonkeyPatch.context() as patch:
        patch_obo(patch)
        async with Client(FastMCPTransport(build_server()), elicitation_handler=person) as client:
            assert client.protocol_version == LATEST_MODERN_VERSION, (
                "this call no longer reaches the era where the question travels in the answer"
            )
            answer = await client.call_tool(tool, arguments)
    assert answer.structured_content is not None, f"{tool} answered with text only"
    return cast("Mapping[str, object]", answer.structured_content)


async def refused_on_the_newer_protocol(
    tool: str, /, *, person: Person | Says, **arguments: object
) -> str:
    with pytest.raises(ToolError) as raised:
        _ = await call_on_the_newer_protocol(tool, person=person, **arguments)
    return str(raised.value)
