"""A client wired to a fake session, for tests that drive HTTP through respx."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast

import httpx
import respx

from with_intelligence_mcp.with_intelligence_client import (
    RetryPolicy,
    TransportSettings,
    WithIntelligenceClient,
)

BASE_URL = "https://api.withintelligence.test"


def transport_settings(**overrides: object) -> TransportSettings:
    defaults: dict[str, object] = {
        "base_url": BASE_URL,
        "default_timeout_seconds": 5.0,
        "default_page_size": 50,
        "max_concurrent_requests_per_user": 5,
        "asset_class_groups": ("hfm",),
    }
    return TransportSettings(**{**defaults, **overrides})  # pyright: ignore[reportArgumentType]


class FakeSession:
    """Hands out a token and counts renewals, so a 401 path is observable."""

    def __init__(self, token: str = "token-1") -> None:
        self.token: str = token
        self.renewals: int = 0

    async def access_token(self) -> str:
        return self.token

    async def renewed_access_token(self) -> str:
        self.renewals += 1
        self.token = f"token-{self.renewals + 1}"
        return self.token

    def subject(self) -> str:
        return "test-subject"


def build_client(
    session: FakeSession | None = None,
    *,
    settings: TransportSettings | None = None,
    max_attempts: int = 3,
) -> tuple[WithIntelligenceClient, FakeSession]:
    caller = session or FakeSession()
    resolved = settings or transport_settings()

    @asynccontextmanager
    async def http_client() -> AsyncGenerator[httpx.AsyncClient]:
        async with httpx.AsyncClient(base_url=resolved.base_url) as client:
            yield client

    @asynccontextmanager
    async def gate(_subject: str) -> AsyncGenerator[None]:
        yield

    client = WithIntelligenceClient(
        resolved,
        http_client=http_client,
        gate=gate,
        retry_policy=RetryPolicy(max_attempts=max_attempts, max_wait_seconds=0.0),
        session=caller,
    )
    return client, caller


def page_body(
    results: list[dict[str, object]], *, total: int, page: int = 1, size: int = 50
) -> dict[str, object]:
    return {
        "pagination": {"page": page, "page_size": size, "count": len(results), "total": total},
        "results": results,
    }


def sent_request(route: respx.Route, index: int = 0) -> httpx.Request:
    """One recorded request, narrowed — respx's call records are untyped."""
    return cast("httpx.Request", route.calls[index].request)


def sent_query(route: respx.Route, index: int = 0) -> str:
    return sent_request(route, index).url.query.decode()


def sent_header(route: respx.Route, name: str, index: int = 0) -> str:
    value = cast("object", sent_request(route, index).headers.get(name))
    return value if isinstance(value, str) else ""
