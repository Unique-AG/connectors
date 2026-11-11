import base64

from with_intelligence_mcp.server_icons import SERVER_ICONS

# node-chat drops inline icons longer than this.
_MAX_ICON_DATA_URI_LENGTH = 100 * 1024


def test_advertises_one_inline_png_within_the_client_size_cap() -> None:
    (icon,) = SERVER_ICONS
    header, _, payload = icon.src.partition(",")
    assert header == "data:image/png;base64"
    assert icon.mime_type == "image/png"
    assert base64.b64decode(payload).startswith(b"\x89PNG\r\n\x1a\n")
    assert len(icon.src) <= _MAX_ICON_DATA_URI_LENGTH
