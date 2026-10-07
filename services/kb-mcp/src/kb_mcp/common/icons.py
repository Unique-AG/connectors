"""Per-tool icons (MCP `icons`), inlined as data URIs so no hosting is needed."""

import base64
from functools import cache
from pathlib import Path

from mcp.types import Icon

_ICONS_DIR = Path(__file__).parent.parent / "assets" / "icons"


@cache
def tool_icons(name: str) -> list[Icon]:
    svg_b64 = base64.b64encode((_ICONS_DIR / f"{name}.svg").read_bytes()).decode(
        "ascii"
    )
    return [Icon(src=f"data:image/svg+xml;base64,{svg_b64}", mime_type="image/svg+xml")]
