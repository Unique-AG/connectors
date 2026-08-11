"""What the activity-history feature needs to know, as its own type.

`config.ActivityHistoryConfig` is the env-parsing shape; this is the domain type `create_app`
translates it into, so nothing under `features/activity_history/` imports `config` (same rule,
same reason as `backstop_client.settings.BackstopTransportSettings` vs
`config.BackstopConfig` — see that module's docstring).

Frozen, so a tool can't accidentally end up tuning its own page size or gist budget mid-request.
"""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class ActivityHistorySettings(BaseModel):
    """Per-stream page size and gist truncation budget for activity history."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    page_size: int = Field(gt=0)
    gist_max_chars: int = Field(gt=0)
