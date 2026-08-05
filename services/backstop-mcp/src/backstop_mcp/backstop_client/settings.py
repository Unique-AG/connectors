"""What the Backstop transport needs to know, as its own types.

`config.BackstopConfig` is the env-parsing shape; these are the domain types `create_app`
translates it into, so nothing under `backstop_client/` imports `config`. Same rule and same
reason as `features.custom_fields.FieldOverride` vs `config.CustomFieldOverrideConfig`: a
config shape becomes a domain one at the composition root, and the layer downstream depends
only on the fields it actually reads.

Frozen, so "the factory owns the one set of settings" is enforced rather than asserted.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class BackstopTransportSettings:
    """Where to reach Backstop, and the per-request knobs `BackstopClient` applies."""

    base_url: str

    # Ordinary CRUD calls vs the /reports and /{entity}/{id}/analytics endpoints Backstop
    # documents as legitimately slow. See `client.is_extended_profile_path`.
    default_timeout_seconds: float
    reports_timeout_seconds: float

    # Backstop hard-limits each user token to 5 concurrent connections; the gate registry in
    # `factory.py` enforces it.
    max_concurrent_requests_per_user: int

    # Default page sizes for `.paginate()`, split the same way as the timeouts.
    default_page_size: int
    report_page_size: int

    # JSON:API pagination parameter names. Configurable because getting them wrong is silent —
    # Backstop ignores an unknown query param and picks its own page size.
    page_limit_param: str
    page_offset_param: str


@dataclass(frozen=True)
class RetrySettings:
    """The two numbers the 429-retry policy is derived from. See `retry.build_retry_policy`."""

    max_attempts: int
    max_wait_ms: int
