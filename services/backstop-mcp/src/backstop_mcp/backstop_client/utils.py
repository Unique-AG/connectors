"""Small, stateless helpers shared by `BackstopClient` and `BackstopClientFactory`.

Kept separate from `client.py` because none of these need `BackstopClient`'s collaborators
(the http provider, the gate, the retry policy) — they're pure functions over paths, bytes, and
credentials.
"""

import functools
import logging
import re
from types import GenericAlias
from typing import TypeVar, cast

import httpx
from pydantic import TypeAdapter, ValidationError

from backstop_mcp.backstop_client.errors import (
    BackstopResponseSchemaError,
    BackstopUntrustedUrlError,
)

logger = logging.getLogger(__name__)

# `typing_extensions.TypeVar` (not stdlib) so `T` can carry a PEP 696 default: native PEP 695
# generic-method syntax can't express a default until Python 3.13, but this repo targets 3.12.
T = TypeVar("T", default=dict[str, object])

# Ordinary classes (including pydantic's parameterized models like `_Page[Record]`) plus
# typing constructs such as `dict[str, object]` that feed `TypeAdapter`.
type SchemaInput = type[object] | GenericAlias


def schema_label(schema: SchemaInput) -> str:
    """Stable name for logs/errors — works for classes and parameterized generics."""
    name = getattr(schema, "__name__", None)
    if isinstance(name, str):
        return name
    origin = getattr(schema, "__origin__", None)
    raw_args = getattr(schema, "__args__", None)
    if isinstance(origin, type):
        if isinstance(raw_args, tuple) and raw_args:
            rendered_args: list[str] = []
            for arg in cast(tuple[object, ...], raw_args):
                if isinstance(arg, (type, GenericAlias)):
                    rendered_args.append(schema_label(arg))
                else:
                    rendered_args.append(str(arg))
            return f"{origin.__name__}[{', '.join(rendered_args)}]"
        return origin.__name__
    return str(schema)


@functools.cache
def adapter_for(schema: SchemaInput) -> TypeAdapter[object]:
    """Process-wide `TypeAdapter` cache — building one is expensive; validating with it is cheap.

    Accepts ordinary classes and parameterized generics (`BackstopApiResource[Attrs]`,
    `_Page[Record]`, `dict[str, object]`, …) so every call site can share one compiled adapter.
    """
    return TypeAdapter(schema)


def deserialize(content: bytes, schema: SchemaInput, *, path: str) -> object:
    """Parse a response body against `schema`, via the process-wide adapter cache.

    `ValidationError` is always wrapped as `BackstopResponseSchemaError` — every Backstop call
    names the shape it expects, so a mismatch is a typed tool failure rather than a raw pydantic
    error.
    """
    try:
        return adapter_for(schema).validate_json(content)
    except ValidationError as exc:
        name = schema_label(schema)
        logger.error(
            "backstop.response.schema_error",
            extra={"path": path, "schema": name},
        )
        raise BackstopResponseSchemaError(path, name, exc) from exc


def resolve_request_url(base_url: str, path: str) -> str:
    """Return a URL/path safe for an `AsyncClient` that already has `base_url` set.

    Relative paths are returned as-is (httpx joins them onto the client base). Absolute URLs
    arrive from `links.next` while walking a pagination chain and are pinned to the configured
    scheme + host: an authenticated client following an arbitrary upstream-supplied origin
    (or a same-host scheme downgrade) would send `Authorization: Basic ...` wherever that
    origin points.

    Protocol-relative URLs (`//evil.example/...`) are absolute network-path references — rewrite
    them with the configured scheme so host/scheme pinning still runs.
    """
    if path.startswith("//"):
        path = f"{httpx.URL(base_url).scheme}:{path}"

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
