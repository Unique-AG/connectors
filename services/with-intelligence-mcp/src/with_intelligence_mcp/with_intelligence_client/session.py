from datetime import UTC, datetime, timedelta
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, SecretStr

# With Intelligence documents 1 hour; renewing early costs one request and avoids a 401 mid-call.
ACCESS_TOKEN_LIFETIME = timedelta(hours=1)
_EARLY_RENEWAL = timedelta(minutes=1)


class WiSession(BaseModel):
    """WI access and refresh tokens."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="ignore", frozen=True, validate_by_name=True
    )

    access_token: SecretStr = Field(validation_alias="accessToken")
    refresh_token: SecretStr = Field(validation_alias="refreshToken")
    issued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_fresh(self) -> bool:
        age = datetime.now(UTC) - self.issued_at
        return age < ACCESS_TOKEN_LIFETIME - _EARLY_RENEWAL
