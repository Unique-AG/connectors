import base64

import pytest

from kb_mcp.tools.content_metadata.tool import content_metadata
from kb_mcp.tools.content_tree.tool import content_tree
from kb_mcp.tools.read_file.tool import read_file
from kb_mcp.tools.search.tool import search


@pytest.mark.parametrize("fn", [search, content_tree, read_file, content_metadata])
def test_tool_icon_is_an_svg_data_uri(fn):
    (icon,) = fn.__fastmcp__.icons
    header, _, payload = icon.src.partition(",")
    assert (header, icon.mime_type) == ("data:image/svg+xml;base64", "image/svg+xml")
    assert base64.b64decode(payload).startswith(b"<svg")
