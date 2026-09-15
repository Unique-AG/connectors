"""WI transport settings."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TransportSettings:
    base_url: str
    default_timeout_seconds: float
    default_page_size: int
    max_concurrent_requests_per_user: int
    asset_class_groups: tuple[str, ...]


@dataclass(frozen=True)
class RetrySettings:
    max_attempts: int
    max_wait_ms: int
