"""What the activity-history feature needs to know, as its own type.

`config.ActivityHistoryConfig` is the env-parsing shape; this is the domain type
`get_activity_history_settings` translates it into, so the feature takes a domain
type rather than the env-parsing shape.

Frozen, so a tool can't accidentally end up tuning its own page size or gist budget mid-request.
"""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class ActivityHistorySettings(BaseModel):
    """Per-stream page size and gist truncation budget for activity history."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    page_size: int = Field(gt=0)
    gist_max_chars: int = Field(gt=0)
