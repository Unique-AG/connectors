"""Small, stateless helpers shared by `BackstopClient` and `BackstopClientFactory`.

Kept separate from `client.py` because none of these need `BackstopClient`'s collaborators
(the http provider, the gate, the retry policy) — they're pure functions over paths, bytes, and
credentials.
"""

import logging
import re

import httpx
from pydantic import TypeAdapter, ValidationError
from typing_extensions import TypeVar

from backstop_mcp.backstop_client.errors import (
    BackstopResponseSchemaError,
    BackstopUntrustedUrlError,
)

logger = logging.getLogger(__name__)

# `typing_extensions.TypeVar` (not stdlib) so `T` can carry a PEP 696 default: native PEP 695
# generic-method syntax can't express a default until Python 3.13, but this repo targets 3.12.
T = TypeVar("T", default=dict[str, object])


def schema_label(schema: type[object]) -> str:
    """Stable name for logs/errors — works for classes and `dict[str, object]`-style aliases."""
    name = getattr(schema, "__name__", None)
    if isinstance(name, str):
        return name
    origin = getattr(schema, "__origin__", None)
    if isinstance(origin, type):
        return origin.__name__
    return str(schema)


def deserialize(content: bytes, adapter: TypeAdapter[T], *, path: str, schema_name: str) -> T:
    """Parse a response body with a caller-supplied `TypeAdapter`.

    `ValidationError` is always wrapped as `BackstopResponseSchemaError` — every Backstop call
    names the shape it expects, so a mismatch is a typed tool failure rather than a raw pydantic
    error.
    """
    try:
        return adapter.validate_json(content)
    except ValidationError as exc:
        logger.error(
            "backstop.response.schema_error",
            extra={"path": path, "schema": schema_name},
        )
        raise BackstopResponseSchemaError(path, schema_name, exc) from exc


def resolve_request_url(base_url: str, path: str) -> str:
    """Return a URL/path safe for an `AsyncClient` that already has `base_url` set.

    Relative paths are returned as-is (httpx joins them onto the client base). Absolute URLs
    arrive from `links.next` while walking a pagination chain and are pinned to the configured
    scheme + host: an authenticated client following an arbitrary upstream-supplied origin
    (or a same-host scheme downgrade) would send `Authorization: Basic ...` wherever that
    origin points.
    """
    if not path.startswith(("http://", "https://")):
        return path if path.startswith("/") else f"/{path}"

    expected = httpx.URL(base_url)
    actual = httpx.URL(path)
    if actual.netloc != expected.netloc or actual.scheme != expected.scheme:
        raise BackstopUntrustedUrlError(path, expected.netloc.decode("ascii", "replace"))
    return path


# Matches a bare numeric id ("123") or a UUID ("f47ac10b-58cc-4372-a567-0e02b2c3d479"), with or
# without dashes — the two id shapes Backstop actually uses in its paths.
_ID_SEGMENT_RE = re.compile(
    r"^\d+$|^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _is_id_segment(segment: str) -> bool:
    return bool(_ID_SEGMENT_RE.match(segment))


def metric_route(path: str) -> str:
    """Bounded label for a request path: every segment, with ids collapsed to a placeholder.

    Full paths carry record ids — segments that are purely numeric or UUID-shaped would make
    the metric's cardinality unbounded, so each one is replaced with `:id` rather than dropped;
    the surrounding segments (e.g. `/contacts/:id/analytics` vs `/contacts/:id`) still matter.
    """
    segments = [segment for segment in httpx.URL(path).path.split("/") if segment]
    if not segments:
        return "/"
    labeled = [":id" if _is_id_segment(segment) else segment for segment in segments]
    return "/" + "/".join(labeled)
