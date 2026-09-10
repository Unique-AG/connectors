"""Decode the tool's standard-base64 file and encode Backstop's gzip+URL-safe `data`."""

import base64
import binascii
import gzip

from fastmcp.exceptions import ToolError

ATTACH_FILE_MAX_BYTES = 20 * 1024 * 1024

_OUR_CAP_REMEDY = "Shrink the file and retry. No request was sent to Backstop."
_BACKSTOP_413_MESSAGE = (
    "Backstop rejected the upload as too large (HTTP 413). The file was under our 20 MB "
    "cap and the request was sent; reduce the payload or split the file."
)


def encode_file_data(content: str, *, max_bytes: int | None = None) -> str:
    """Return Backstop `data` (gzip then URL-safe base64, no padding) after the size cap.

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
            + f"before calling Backstop. {_OUR_CAP_REMEDY}"
        )
    return base64.urlsafe_b64encode(gzip.compress(raw)).decode("ascii").rstrip("=")


def backstop_payload_too_large_message() -> str:
    return _BACKSTOP_413_MESSAGE


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
