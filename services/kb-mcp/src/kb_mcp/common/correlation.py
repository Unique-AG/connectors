"""Correlation-id helper for tool logging.

user_id/company_id are confidential (unique_toolkit's own UniqueSettings
types them SecretStr) — hash and truncate instead of logging them raw, the
same pattern FastMCP uses for JTIs (jti[:16]).
"""

import hashlib


def correlation_id(*identity_parts: str) -> str:
    digest = hashlib.sha256("|".join(identity_parts).encode()).hexdigest()
    return digest[:16]
