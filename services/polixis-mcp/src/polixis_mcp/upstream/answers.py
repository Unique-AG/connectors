"""Which operation a request to Polixis calls, read from the spec's routes, so the cache keeps
and reuses only an answer that fits that operation's model.
"""

from collections.abc import Callable
import re
from typing import ClassVar, Protocol

from fastmcp.utilities.openapi import parse_openapi_to_http_routes
import httpx2
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import ValidationError

from polixis_mcp.upstream.cache import AnswerCheck
from polixis_mcp.upstream.generated.operations import FIND_PATHS
from polixis_mcp.upstream.generated.operations import GET_CORPORATE_PROFILE
from polixis_mcp.upstream.generated.operations import GET_JUDICIAL_RECORDS
from polixis_mcp.upstream.generated.operations import GET_PROFILE_FIELDS
from polixis_mcp.upstream.generated.operations import GET_SANCTION_EXPOSURE
from polixis_mcp.upstream.generated.operations import GET_SMART_GRAPH
from polixis_mcp.upstream.generated.operations import GET_SUBGRAPH
from polixis_mcp.upstream.generated.operations import GET_TOP_DOWN_OWNERSHIP
from polixis_mcp.upstream.generated.operations import GET_ULTIMATE_BENEFICIAL_OWNERS
from polixis_mcp.upstream.generated.operations import RESOLVE_PERMANENT_ID
from polixis_mcp.upstream.generated.operations import SEARCH_ENTITIES
from polixis_mcp.upstream.rejections import is_rejection


def answer_check(spec: dict[str, object], *, base_path: str) -> AnswerCheck:
    """A body fits when it validates against the model of the operation whose route the request
    matches, and is not a rejection. A request no operation matches has no answer to keep.
    `base_path` is the API URL's path, which the spec's routes leave out.
    """
    models = {operation.operation_id: operation.adapter for operation in _OPERATIONS}
    routes = [
        _Route(method=route.method, path=_path_pattern(route.path), accepts=_accepts(model))
        for route in parse_openapi_to_http_routes(spec)
        if (model := models.get(route.operation_id or "")) is not None
    ]

    def usable(request: httpx2.Request, body: bytes) -> bool:
        path = request.url.path.removeprefix(base_path)
        route = next(
            (r for r in routes if r.method == request.method and r.path.fullmatch(path)), None
        )
        return route is not None and route.accepts(body)

    return usable


class _Parses(Protocol):
    def validate_json(self, data: bytes, /) -> object: ...


class _Route(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    method: str
    path: re.Pattern[str]
    accepts: Callable[[bytes], bool]


def _accepts(model: _Parses) -> Callable[[bytes], bool]:
    def accepts(body: bytes) -> bool:
        try:
            answer = model.validate_json(body)
        except ValidationError:
            return False
        return not is_rejection(answer)

    return accepts


def _path_pattern(template: str) -> re.Pattern[str]:
    """`/api/graph/pid/{pid}` matches `/api/graph/pid/` and one segment."""
    return re.compile("[^/]+".join(re.escape(part) for part in re.split(r"\{[^}]+\}", template)))


# Every operation the generated code holds, which `test_upstream` checks against it.
_OPERATIONS = (
    SEARCH_ENTITIES,
    GET_CORPORATE_PROFILE,
    GET_SMART_GRAPH,
    GET_SUBGRAPH,
    GET_TOP_DOWN_OWNERSHIP,
    GET_ULTIMATE_BENEFICIAL_OWNERS,
    GET_PROFILE_FIELDS,
    RESOLVE_PERMANENT_ID,
    GET_SANCTION_EXPOSURE,
    FIND_PATHS,
    GET_JUDICIAL_RECORDS,
)
