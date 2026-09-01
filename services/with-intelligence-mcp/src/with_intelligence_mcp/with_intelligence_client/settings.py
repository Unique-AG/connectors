"""What the transport is told, translated from config by `dependencies`.

Frozen and its own types on purpose: the transport must not read `config` (rule 3 in
`tests/test_layering.py`), so a knob it has no business seeing cannot reach it.
"""

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
