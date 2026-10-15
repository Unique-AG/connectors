from fastmcp import FastMCP
from starlette.testclient import TestClient

from kb_mcp.favicon import add_favicon_route


def test_favicon_is_served_as_svg_without_auth():
    mcp = FastMCP("t")
    add_favicon_route(mcp)

    response = TestClient(mcp.http_app()).get("/favicon.ico")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/svg+xml"
    assert response.content.startswith(b"<svg")
