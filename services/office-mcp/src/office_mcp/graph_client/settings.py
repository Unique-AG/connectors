"""Graph transport configuration, injected rather than read from the environment.

`graph_client/` cannot import `office_mcp.config`. A transport that read the environment could
diverge from the app's config, so `create_app` translates app config into this type.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GraphSettings:
    """Request timeout, connect timeout, and retry count for Graph calls.

    The SDK defaults are 100 s read, 30 s connect, 3 retries, sized for batch clients: four
    attempts at 100 s each, plus Retry-After sleeps, is 15 minutes per tool call. An MCP client
    gives up long before that. `max_retries` still keeps the SDK's 3, because waiting out
    Retry-After is Graph's documented throttling contract and giving up on the first 429 accrues
    quota without getting an answer.

    These defaults are what the service ships with, not what it runs with. `create_app` passes all
    three from the matching `AppConfig` fields, and they are repeated here so a `GraphSettings()`
    in a test is the deployed shape.
    """

    request_timeout_seconds: float = 30.0
    connect_timeout_seconds: float = 10.0
    max_retries: int = 3
