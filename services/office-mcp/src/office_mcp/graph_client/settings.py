"""What the Graph transport is told, as opposed to what it reads.

`graph_client/` cannot import `office_mcp.config` — a transport that reads the environment can
end up configured differently from the app it runs inside. `create_app` translates the app
config into this type and injects it.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GraphSettings:
    """How long one Graph request may take, and how many times it may be retried.

    The official SDK's defaults are a 100 s read timeout, a 30 s connect timeout
    (`kiota_http.kiota_client_factory`) and 3 retries
    (`kiota_http.middleware.options.RetryHandlerOption`). Those suit a batch client: four
    attempts at 100 s each, plus the `Retry-After` sleeps between them, is a quarter of an hour
    spent inside a single tool call, and an MCP client gives up long before that. The timeouts
    here are sized for an interactive call instead, which is the whole reason this type exists.

    `max_retries` deliberately keeps the SDK's 3. Waiting out `Retry-After` and retrying *is*
    Graph's documented throttling contract (https://learn.microsoft.com/en-us/graph/throttling),
    and a client that gives up on the first 429 accrues against the same tenant quota without
    ever getting an answer.
    """

    request_timeout_seconds: float = 30.0
    connect_timeout_seconds: float = 10.0
    max_retries: int = 3
