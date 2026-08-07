"""What the Backstop transport needs to know, as its own types.

`config.BackstopConfig` is the env-parsing shape; these are the domain types `create_app`
translates it into, so nothing under `backstop_client/` imports `config`. Same rule and same
reason as `features.custom_fields.FieldOverride` vs `config.CustomFieldOverrideConfig`: a
config shape becomes a domain one at the composition root, and the layer downstream depends
only on the fields it actually reads.

Frozen, so "the factory owns the one set of settings" is enforced rather than asserted.
"""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class BackstopTransportSettings(BaseModel):
    """Where to reach Backstop, and the per-request knobs `BackstopClient` applies."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    base_url: str

    # Ordinary CRUD calls vs the /reports and /{entity}/{id}/analytics endpoints Backstop
    # documents as legitimately slow. See `utils.is_slow_endpoint`.
    default_timeout_seconds: float = Field(gt=0)
    reports_timeout_seconds: float = Field(gt=0)

    # Backstop hard-limits each user token to 5 concurrent connections; the gate registry in
    # `factory.py` enforces it.
    max_concurrent_requests_per_user: int = Field(ge=1)

    # Default page sizes for `.paginate()`, split the same way as the timeouts.
    default_page_size: int = Field(ge=1)
    report_page_size: int = Field(ge=1, le=500)

    # JSON:API pagination parameter names. Configurable because getting them wrong is silent —
    # Backstop ignores an unknown query param and picks its own page size.
    page_limit_param: str = Field(min_length=1)
    page_offset_param: str = Field(min_length=1)


class RetrySettings(BaseModel):
    """The two numbers the 429-retry policy is derived from. See `retry.build_retry_policy`."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    max_attempts: int = Field(ge=1)
    max_wait_ms: int = Field(ge=0)
