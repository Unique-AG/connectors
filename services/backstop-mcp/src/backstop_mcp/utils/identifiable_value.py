"""Identifying diagnostic data: hashed in logs, disclosed only when configured.

Use for logins, emails, names — values we need to correlate across lines without
writing the original. Secrets (tokens, passwords) must never be wrapped in this:
do not log them. For values that only need a hint of the original, not a stable
identity, smear — that is a different wrapper.
"""

import hashlib
import os
from enum import StrEnum
from typing import override

__all__ = [
    "LogsDiagnosticDataPolicy",
    "IdentifiableValue",
    "identifiable_value",
    "is_disclosure_active",
]


class LogsDiagnosticDataPolicy(StrEnum):
    CONCEAL = "conceal"
    DISCLOSE = "disclose"


class IdentifiableValue:
    """A string that logs as `sha256:<hex>` unless disclosure is on.

    `.value` is always the original. Interpolation, `repr`, and pino-json extras
    (`json.dumps(..., default=str)`) all go through `__str__`.

    Construct with an explicit `conceal` in tests; production call sites use
    `identifiable_value()`, which reads `LOGS_DIAGNOSTICS_DATA_POLICY`.
    """

    def __init__(self, value: str, *, conceal: bool) -> None:
        self.value: str = value
        self.conceal: bool = conceal

    @override
    def __str__(self) -> str:
        if not self.conceal:
            return self.value
        digest = hashlib.sha256(self.value.encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

    @override
    def __repr__(self) -> str:
        return self.__str__()


def is_disclosure_active() -> bool:
    return os.environ.get("LOGS_DIAGNOSTICS_DATA_POLICY") == LogsDiagnosticDataPolicy.DISCLOSE


def identifiable_value(value: str) -> IdentifiableValue:
    return IdentifiableValue(value, conceal=not is_disclosure_active())
