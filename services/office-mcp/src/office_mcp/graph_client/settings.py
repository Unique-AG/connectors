"""Configuration for the Graph transport, injected not read from environment.

graph_client/ cannot import office_mcp.config. A transport that reads the environment can
diverge from the app's config. create_app will translate app config into this type and
inject it.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GraphSettings:
    """Request timeout, connect timeout, and retry count for Graph calls.

    The SDK defaults are 100 s read, 30 s connect, 3 retries. Those suit batch clients: four
    attempts at 100 s each, plus Retry-After sleeps, equals 15 minutes per tool call. MCP
    clients give up much sooner. These values are sized for interactive calls.

    max_retries keeps the SDK's 3 by design. Waiting out Retry-After and retrying is Graph's
    documented throttling contract. A client giving up on the first 429 accrues quota without
    getting an answer.
    """

    request_timeout_seconds: float = 30.0
    connect_timeout_seconds: float = 10.0
    max_retries: int = 3
