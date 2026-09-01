from datetime import UTC, datetime, timedelta
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, SecretStr

# The vendor documents 1 hour; renewing early costs one request and avoids a 401 mid-call.
ACCESS_TOKEN_LIFETIME = timedelta(hours=1)
_EARLY_RENEWAL = timedelta(minutes=1)


class VendorSession(BaseModel):
    """What `/v3/auth/sign-in` and `/v3/auth/refresh` return, plus when we got it.

    The vendor sends no expiry, so `issued_at` is ours and `is_fresh` is inferred from the
    documented lifetime rather than read off the token.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    access_token: SecretStr
    refresh_token: SecretStr
    issued_at: datetime

    @property
    def is_fresh(self) -> bool:
        age = datetime.now(UTC) - self.issued_at
        return age < ACCESS_TOKEN_LIFETIME - _EARLY_RENEWAL
