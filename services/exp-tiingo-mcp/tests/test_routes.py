from tiingo_mcp.openapi.routes import MCP_NAMES


def test_mcp_names_are_unique() -> None:
    assert len(set(MCP_NAMES.values())) == len(MCP_NAMES)
