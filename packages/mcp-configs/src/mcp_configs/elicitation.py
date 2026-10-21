from enum import StrEnum
from typing import ClassVar

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcp_configs.config import shared_config


class Toggle(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class ElicitationSettings(BaseSettings):
    """When a tool stops to ask the user, and how long it waits for an answer.

    - `for_disambiguation`: pick one when a name matches several records.
    - `for_data_modification`: confirm before creating or changing data.
    - `for_data_removal`: confirm before deleting data.

    A tool that gets no answer within `timeout_before_cancel_seconds` gives up on the question:
    a disambiguation returns the candidates instead, and a confirmation does nothing.
    """

    model_config: ClassVar[SettingsConfigDict] = shared_config("ELICITATION_")

    for_disambiguation: Toggle = Toggle.ENABLED
    for_data_modification: Toggle = Toggle.ENABLED
    for_data_removal: Toggle = Toggle.ENABLED
    timeout_before_cancel_seconds: float = Field(default=120, gt=0)

    @field_validator(
        "for_disambiguation", "for_data_modification", "for_data_removal", mode="before"
    )
    @classmethod
    def _lowercase(cls, value: object) -> object:
        return value.lower() if isinstance(value, str) else value
