from typing import Annotated, ClassVar

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcp_configs.config import shared_config


class ElicitationSettings(BaseSettings):
    """How long a tool waits for a person to answer, and how a question survives a replica change.

    A tool that gets no answer within `timeout_before_cancel_seconds` gives up on the question:
    a choice returns the options to the model instead, and a confirmation does nothing.

    `request_state_keys` seals the `request_state` a question hands the client, so the call that
    brings the answer back opens on any replica and after a restart. The first key seals, every
    key opens, which lets a key rotate. Without one, each process seals under a key of its own.
    """

    model_config: ClassVar[SettingsConfigDict] = shared_config("ELICITATION_")

    timeout_before_cancel_seconds: float = Field(default=120, gt=0)
    request_state_keys: list[Annotated[SecretStr, Field(min_length=32)]] = Field(
        default_factory=list
    )
