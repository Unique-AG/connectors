"""Local MCP server that asks for confirmation before deleting, on both protocol generations."""

import mcp_types as types
from mcp.server.mcpserver import Context, MCPServer
from pydantic import BaseModel

server = MCPServer("elicitation-selftest")
things: set[str] = set()


class Confirm(BaseModel):
    confirm: bool


@server.tool()
def create_thing(name: str) -> str:
    things.add(name)
    return f"created {name}"


@server.tool()
def list_things() -> list[str]:
    return sorted(things)


@server.tool()
async def delete_thing(name: str, ctx: Context) -> types.InputRequiredResult | str:
    message = f"Delete {name}?"
    if ctx.protocol_version == "2026-07-28":
        responses = ctx.input_responses
        if not responses:
            schema = {"type": "object", "properties": {"confirm": {"type": "boolean"}}, "required": ["confirm"]}
            return types.InputRequiredResult(
                input_requests={
                    "confirm": types.ElicitRequest(
                        params=types.ElicitRequestFormParams(message=message, requested_schema=schema)
                    )
                }
            )
        answer = responses["confirm"]
        accepted = answer.action == "accept" and bool((answer.content or {}).get("confirm"))
    else:
        result = await ctx.elicit(message, Confirm)
        accepted = result.action == "accept" and result.data.confirm
    if not accepted:
        return f"not deleted: {name}"
    things.discard(name)
    return f"deleted {name}"


if __name__ == "__main__":
    server.run()
