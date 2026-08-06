"""Small, stateless helpers shared by `BackstopClient` and `BackstopClientFactory`.

Kept separate from `client.py` because none of these need `BackstopClient`'s collaborators
(the http provider, the gate, the retry policy) — they're pure functions over paths, bytes, and
credentials.
"""

import base64
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

_DICT_ADAPTER = TypeAdapter(dict[str, object])

# `typing_extensions.TypeVar` (not stdlib) so `T` can carry a PEP 696 default: native PEP 695
# generic-method syntax can't express a default until Python 3.13, but this repo targets 3.12.
# The default lets every schema-less call site (e.g. `client.get("/system-info")`) infer
# `dict[str, object]` without an explicit subscript.
T = TypeVar("T", default=dict[str, object])


def deserialize(content: bytes, schema: type[T] | None, *, path: str) -> T:
    """Parse a response body, validating against `schema` if given, else the generic dict shape.

    Only the schema-given case is wrapped as `BackstopResponseSchemaError`: a caller that asked
    for a shape gets told which shape failed and where, while the schema-less path keeps
    propagating pydantic's own error.
    """
    if schema is None:
        return _DICT_ADAPTER.validate_json(content)  # pyright: ignore[reportReturnType]
    try:
        return TypeAdapter(schema).validate_json(content)
    except ValidationError as exc:
        logger.error(
            "backstop.response.schema_error",
            extra={"path": path, "schema": schema.__name__},
        )
        raise BackstopResponseSchemaError(path, schema.__name__, exc) from exc


# /reports and /{entity}/{id}/analytics are the calls Backstop docs call out as legitimately
# slow (up to ~30s per 500 records) — they get the extended timeout and the larger
# report-sized page default; everything else gets the ordinary CRUD profile.
_EXTENDED_PROFILE_MARKERS = ("/reports", "/analytics")


def build_auth_headers(username: str, api_token: str) -> dict[str, str]:
    """Build the `Authorization: Basic ...` + `token: true` headers Backstop expects.

    Every user connects with a personal API token (not a password), so `token: true` is
    always sent — see https://backstopsolutions.elevio.help/en/articles/1018 and .../236.
    """
    basic_auth = base64.b64encode(f"{username}:{api_token}".encode()).decode()
    return {"authorization": f"Basic {basic_auth}", "token": "true"}


def is_extended_profile_path(path: str) -> bool:
    return any(marker in path for marker in _EXTENDED_PROFILE_MARKERS)


def build_url(base_url: str, path: str) -> str:
    """Resolve a path (or an absolute `links.next` URL) against the configured base URL.

    Absolute URLs arrive from `links.next` while walking a pagination chain. They are pinned
    to the configured host: an authenticated client following an arbitrary upstream-supplied
    origin would send `Authorization: Basic ...` wherever that origin points.
    """
    if not path.startswith(("http://", "https://")):
        separator = "" if path.startswith("/") else "/"
        return base_url.rstrip("/") + separator + path

    expected = httpx.URL(base_url).netloc
    actual = httpx.URL(path).netloc
    if actual != expected:
        raise BackstopUntrustedUrlError(path, expected.decode("ascii", "replace"))
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
    without_query = path.split("?", 1)[0]
    is_absolute = without_query.startswith(("http://", "https://"))
    stripped = without_query.removeprefix("http://").removeprefix("https://")
    segments = [segment for segment in stripped.split("/") if segment]
    if is_absolute:
        # The leading segment of an absolute URL is the host, not part of the route.
        segments = segments[1:]
    if not segments:
        return "/"
    labeled = [":id" if _is_id_segment(segment) else segment for segment in segments]
    return "/" + "/".join(labeled)
