"""Pseudonyms for identifying values (logins, emails, search terms) in logs and on spans, never
secrets. Keyed at INFO and above, so a leaked log cannot be matched against a list of guesses."""

import hashlib
import hmac
from enum import StrEnum
from typing import override

from mcp_configs import LoggingSettings
from mcp_configs import LogLevel


class PseudonymMode(StrEnum):
    KEYED = "keyed"
    PLAIN = "plain"
    DISCLOSE = "disclose"


class IdentifiableValue:
    """A string that logs as a pseudonym unless disclosure is on.

    `.value` is always the original. Interpolation, `repr`, and pino-json extras
    (`json.dumps(..., default=str)`) all go through `__str__`.
    """

    def __init__(self, value: str, *, mode: PseudonymMode, key: bytes | None = None) -> None:
        assert mode is not PseudonymMode.KEYED or key is not None, "KEYED needs a key"
        self.value: str = value
        self.mode: PseudonymMode = mode
        self.key: bytes | None = key

    @override
    def __str__(self) -> str:
        match self.mode:
            case PseudonymMode.DISCLOSE:
                return self.value
            case PseudonymMode.PLAIN:
                return f"sha256:{hashlib.sha256(self.value.encode()).hexdigest()}"
            case PseudonymMode.KEYED:
                assert self.key is not None, "KEYED needs a key"
                digest = hmac.new(self.key, self.value.encode(), hashlib.sha256).hexdigest()
                return f"hmac-sha256:{digest}"

    @override
    def __repr__(self) -> str:
        return self.__str__()


# Until `configure_identifiable_values` runs (unit tests, scripts).
_mode: PseudonymMode = PseudonymMode.PLAIN
_key: bytes | None = None


def configure_identifiable_values(settings: LoggingSettings, *, secret: bytes) -> None:
    """Pick the process-wide pseudonym mode. Disclosure wins over DEBUG, which wins over keyed.

    `secret` keys the pseudonyms. Derive it for this purpose from a key the MCP already holds;
    never pass that key itself.
    """
    global _mode, _key
    if settings.discloses_diagnostics:
        _mode, _key = PseudonymMode.DISCLOSE, None
    elif settings.log_level is LogLevel.DEBUG:
        _mode, _key = PseudonymMode.PLAIN, None
    else:
        _mode, _key = PseudonymMode.KEYED, secret


def reset_identifiable_values() -> None:
    """Restore the unconfigured default, so a test does not leak its mode into the next."""
    global _mode, _key
    _mode, _key = PseudonymMode.PLAIN, None


def identifiable_value(value: str) -> IdentifiableValue:
    return IdentifiableValue(value, mode=_mode, key=_key)
