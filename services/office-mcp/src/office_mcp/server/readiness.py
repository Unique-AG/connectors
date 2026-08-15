"""Readiness via the one Postgres connection this service depends on.

The OAuth state store owns this connection. Every token is a reference token re-validated
against the store on each request, so an unreachable database means no one can sign in.

The store builds its own asyncpg pool from driver_dsn with no connect args; TLS settings ride
the DSN. A separate connection would negotiate TLS differently and could report ready while
every sign-in fails—the exact failure a readiness probe prevents. So the probe asks the store
itself through the same wrapper chain.
"""

import logging

from key_value.aio.protocols import AsyncKeyValue
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Trap: a key nothing ever writes. get on a missing key is one SELECT returning None—it does
# not disturb OAuth state. On first call it forces the store's lazy setup, so an unreachable
# database or missing CREATE grant surfaces here, not at the first user's login.
_PROBE_COLLECTION = "readiness"
_PROBE_KEY = "probe"


async def ready_response(oauth_storage: AsyncKeyValue) -> JSONResponse:
    """Readiness response reporting checks run.

    Postgres is a hard dependency, so an unreachable database means not ready.
    """
    database_ok = True
    try:
        _ = await oauth_storage.get(_PROBE_KEY, collection=_PROBE_COLLECTION)
    except Exception:
        database_ok = False
        logger.warning("ready.database_unreachable", exc_info=True)

    checks = {"database": database_ok}
    return JSONResponse(
        {"status": "healthy" if database_ok else "unhealthy", "checks": checks},
        status_code=200 if database_ok else 503,
    )
