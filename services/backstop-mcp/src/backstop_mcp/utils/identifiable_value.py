"""Identifying diagnostic data: a pseudonym in logs, disclosed only when configured.

Use for logins, emails, names — values we need to correlate across lines without writing the
original. Secrets (tokens, passwords) must never be wrapped in this: do not log them.

What `identifiable_value(...)` prints depends on the process, configured once at startup:

- `LOG_LEVEL` info or above: `hmac-sha256:<hex>`, keyed with a secret derived from
  `BACKSTOP_MCP_ENCRYPTION_KEY`. Not reversible by guessing likely emails.
- `LOG_LEVEL=debug`: plain `sha256:<hex>`, so a developer can compute `sha256(<suspected value>)`
  locally and grep for it without getting the secret out.
- `LOGS_DIAGNOSTICS_DATA_POLICY=disclose`: the original value (local debugging only).

`LOG_LEVEL` is process-wide, so switching a pod to debug switches its pseudonyms from keyed to
plain. Lines from before and after the switch do not correlate with each other. Rotating
`BACKSTOP_MCP_ENCRYPTION_KEY` changes every keyed pseudonym.

Before `configure_identifiable_values` runs (unit tests, scripts) the mode is plain `sha256`,
which is the historical default.
"""

import hashlib
import hmac
from enum import StrEnum
from typing import override

__all__ = [
    "IdentifiableValue",
    "LogsDiagnosticDataPolicy",
    "PseudonymMode",
    "configure_identifiable_values",
    "identifiable_value",
    "is_disclosure_active",
    "reset_identifiable_values",
]

_PSEUDONYM_LABEL = b"backstop-mcp/log-pseudonyms/v1"


class LogsDiagnosticDataPolicy(StrEnum):
    CONCEAL = "conceal"
    DISCLOSE = "disclose"


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


_mode: PseudonymMode = PseudonymMode.PLAIN
_key: bytes | None = None


def configure_identifiable_values(
    *, policy: LogsDiagnosticDataPolicy, log_level: str, encryption_key: bytes
) -> None:
    """Pick the process-wide pseudonym mode. Disclosure wins over debug, which wins over keyed."""
    global _mode, _key
    if policy is LogsDiagnosticDataPolicy.DISCLOSE:
        _mode = PseudonymMode.DISCLOSE
        _key = None
        return
    if log_level.lower() == "debug":
        _mode = PseudonymMode.PLAIN
        _key = None
        return
    _mode = PseudonymMode.KEYED
    _key = _pseudonym_key(encryption_key)


def reset_identifiable_values() -> None:
    """Restore the pre-configuration default. Tests call this so modes do not leak."""
    global _mode, _key
    _mode = PseudonymMode.PLAIN
    _key = None


def is_disclosure_active() -> bool:
    return _mode is PseudonymMode.DISCLOSE


def identifiable_value(value: str) -> IdentifiableValue:
    return IdentifiableValue(value, mode=_mode, key=_key)


def _pseudonym_key(encryption_key: bytes) -> bytes:
    """A purpose-specific key, not the encryption key itself. The `v1` label lets us rotate it."""
    return hmac.new(encryption_key, _PSEUDONYM_LABEL, hashlib.sha256).digest()
