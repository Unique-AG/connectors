"""Decode the tool's standard-base64 file and encode Backstop's gzip+URL-safe `data`.

The size cap itself lives in `attach_file_max_bytes.py` at the feature root, with the
reasoning behind the number. Rejecting here rather than letting the transport 413 means the
agent gets an actionable message instead of a bare HTTP error.
"""

import base64
import binascii
import gzip

from fastmcp.exceptions import ToolError

from backstop_mcp.features.activity_writes.attach_file_max_bytes import ATTACH_FILE_MAX_BYTES


def encode_file_data(content: str, *, max_bytes: int | None = None) -> str:
    """Return Backstop `data` (gzip then URL-safe base64, no padding) after the size cap.

    Backstop is explicit about the encoding: plain base64 answers
    `400 "You should Zip and encode dto data with Base64 schema"`. Verified live that this
    form round-trips byte-for-byte when the document is read back from `documentUri`.

    Raises `ToolError` for invalid base64, an empty file, or a decoded size over the cap.
    That rejection happens before any HTTP call.
    """
    limit = ATTACH_FILE_MAX_BYTES if max_bytes is None else max_bytes
    raw = _decode_standard_base64(content)
    if not raw:
        raise ToolError("content decoded to an empty file.")
    if len(raw) > limit:
        raise ToolError(
            f"File is {len(raw)} bytes; attach_file rejects files over {limit} bytes "
            + "before calling Backstop. Shrink or split the file and retry. No request "
            + "was sent to Backstop."
        )
    return base64.urlsafe_b64encode(gzip.compress(raw)).decode("ascii").rstrip("=")


def _decode_standard_base64(content: str) -> bytes:
    stripped = "".join(content.split())
    padded = stripped + "=" * (-len(stripped) % 4)
    try:
        return base64.b64decode(padded, validate=True)
    except binascii.Error:
        pass
    try:
        return base64.urlsafe_b64decode(padded)
    except binascii.Error as exc:
        raise ToolError(
            "content is not valid base64. Pass standard base64 of the raw file bytes."
        ) from exc
