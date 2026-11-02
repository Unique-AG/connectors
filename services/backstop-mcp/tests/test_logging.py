import hashlib
import hmac

from mcp_configs import LoggingSettings, LogLevel
from mcp_observability import identifiable_value

from backstop_mcp.logging import configure_logging

_ENCRYPTION_KEY = b"encryption-key-material"
_LOGIN = "jdoe"


def _keyed(value: str, key: bytes) -> str:
    return f"hmac-sha256:{hmac.new(key, value.encode(), hashlib.sha256).hexdigest()}"


class TestPseudonymSecret:
    def test_keys_pseudonyms_with_a_secret_derived_from_the_encryption_key(self) -> None:
        derived = hmac.new(
            _ENCRYPTION_KEY, b"backstop-mcp/log-pseudonyms/v1", hashlib.sha256
        ).digest()

        configure_logging(LoggingSettings(log_level=LogLevel.INFO), encryption_key=_ENCRYPTION_KEY)

        assert str(identifiable_value(_LOGIN)) == _keyed(_LOGIN, derived)

    def test_never_keys_pseudonyms_with_the_encryption_key_itself(self) -> None:
        configure_logging(LoggingSettings(log_level=LogLevel.INFO), encryption_key=_ENCRYPTION_KEY)

        assert str(identifiable_value(_LOGIN)) != _keyed(_LOGIN, _ENCRYPTION_KEY)
