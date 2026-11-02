import base64
from pathlib import Path

from mcp.types import Icon

_ICON_PNG = (Path(__file__).parent / "assets" / "icon-192.png").read_bytes()

SERVER_ICONS = [
    Icon(
        src=f"data:image/png;base64,{base64.b64encode(_ICON_PNG).decode('ascii')}",
        mime_type="image/png",
        sizes=["192x192"],
    )
]
