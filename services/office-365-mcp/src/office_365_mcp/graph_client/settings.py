"""Graph transport configuration, injected rather than read from the environment.

`graph_client/` cannot import `office_365_mcp.config`, so `create_app` translates app config into
this.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GraphSettings:
    """Both timeouts are cut from the SDK's defaults of 100 s read and 30 s connect, which are sized
    for batch clients: four attempts at 100 s each, plus Retry-After sleeps, is 15 minutes per tool
    call. `max_retries` keeps the SDK's 3, because waiting out Retry-After is Graph's contract.

    TRAP: these are what the service ships with, not what it runs with — `create_app` passes all
    three from the matching `AppConfig` fields. They are repeated here so a `GraphSettings()` in a
    test is the deployed shape.
    """

    request_timeout_seconds: float = 30.0
    connect_timeout_seconds: float = 10.0
    max_retries: int = 3
