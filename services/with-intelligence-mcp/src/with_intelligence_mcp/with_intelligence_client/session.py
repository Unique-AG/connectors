from datetime import UTC, datetime, timedelta
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, SecretStr

# With Intelligence documents 1 hour; renewing early costs one request and avoids a 401 mid-call.
ACCESS_TOKEN_LIFETIME = timedelta(hours=1)
_EARLY_RENEWAL = timedelta(minutes=1)


class WiSession(BaseModel):
    """WI access and refresh tokens."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    access_token: SecretStr
    refresh_token: SecretStr
    issued_at: datetime

    @property
    def is_fresh(self) -> bool:
        age = datetime.now(UTC) - self.issued_at
        return age < ACCESS_TOKEN_LIFETIME - _EARLY_RENEWAL

    def has_different_access_token(self, other: "WiSession | None") -> bool:
        return other is None or (
            self.access_token.get_secret_value() != other.access_token.get_secret_value()
        )
