"""Correlation-id helper for tool logging.

``user_id``/``company_id`` are typed ``SecretStr`` with accessors named
``get_confidential_user_id()``/``get_confidential_company_id()`` in
``unique_toolkit.app.unique_settings.UniqueSettings`` — the codebase's own
convention treats them as confidential, and logging them raw would land
them in Loki in plaintext. Log a truncated hash instead: enough to
correlate lines from the same caller across a request, without exposing
who. FastMCP does the same thing with JTIs (``jti[:16]``).
"""

import hashlib


def correlation_id(*identity_parts: str) -> str:
    digest = hashlib.sha256("|".join(identity_parts).encode()).hexdigest()
    return digest[:16]
