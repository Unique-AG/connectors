from mcp_observability import validate_trace_declarations

from backstop_mcp.server.tools import TOOLS


def test_every_trace_declaration_in_the_app_is_valid() -> None:
    """`create_app` runs the same check and crashes on a bad declaration; this catches it in CI."""
    assert TOOLS

    validate_trace_declarations()
