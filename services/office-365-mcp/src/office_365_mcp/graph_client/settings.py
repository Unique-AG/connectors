"""Graph transport configuration, injected rather than read from the environment.

`graph_client/` cannot import `office_365_mcp.config`, so `create_app` translates app config into
this.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GraphSettings:
    """Both timeouts are cut down from the SDK's defaults of 100 s read and 30 s connect, which are
    sized for batch clients. Four attempts at 100 s each, plus Retry-After sleeps, add up to 15
    minutes per tool call. `max_retries` keeps the SDK's 3, because waiting out Retry-After is part
    of Graph's contract.

    TRAP: these are the values the service ships with, not the values it runs with. `create_app`
    passes all three from the matching `AppConfig` fields. This class repeats the values so a
    `GraphSettings()` in a test matches the deployed shape.
    """

    request_timeout_seconds: float = 30.0
    connect_timeout_seconds: float = 10.0
    max_retries: int = 3
