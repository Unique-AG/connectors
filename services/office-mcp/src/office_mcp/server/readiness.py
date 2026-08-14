"""Readiness, answered by the one Postgres connection this service actually depends on.

That connection belongs to the OAuth state store (`auth.build_oauth_storage`): every token
FastMCP issues is a reference token re-validated against that store on every request, so a
store that cannot reach Postgres is a server nobody can sign in to.

The store builds its own asyncpg pool from `DatabaseConfig.driver_dsn` and accepts no connect
args, so its TLS settings ride the DSN. A probe that opened a connection of its own — one
configured by any other route, as this one once was — would negotiate TLS by a different route
and could answer 200 while every sign-in failed: the pod reports ready and no one can log in,
which is the exact failure a readiness probe exists to prevent.

So the probe asks the store itself, through the same wrapper chain the auth provider holds.
"""

import logging

from key_value.aio.protocols import AsyncKeyValue
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# A key nothing ever writes. `get` on a missing key is one SELECT that returns `None` — it
# cannot disturb the OAuth state around it, and on the first call it also forces the store's
# lazy setup, so an unreachable database or a missing `CREATE` grant surfaces here rather than
# at the first user's login.
_PROBE_COLLECTION = "readiness"
_PROBE_KEY = "probe"


async def ready_response(oauth_storage: AsyncKeyValue) -> JSONResponse:
    """Readiness, reporting the checks it actually ran.

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
