"""Readiness via the one Postgres connection this service depends on.

The OAuth state store owns this connection. Every token is a reference token re-validated against
the store on each request, so an unreachable database means no one can sign in.

The store builds its own asyncpg pool from `driver_dsn` with no connect args, and TLS settings ride
the DSN. An earlier version of this probe opened its own connection, which negotiated TLS
differently and could report ready while every sign-in failed. That is the exact failure a readiness
probe exists to prevent, so the probe now asks the store itself, through the same wrapper chain.
"""

import asyncio
import logging

from key_value.aio.protocols import AsyncKeyValue
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Trap: a key nothing ever writes. A get on a missing key is one SELECT returning None, so it does
# not disturb OAuth state. On the first call it forces the store's lazy setup, so an unreachable
# database or a missing CREATE grant surfaces here rather than at the first user's login.
_PROBE_COLLECTION = "readiness"
_PROBE_KEY = "probe"

# Trap: nothing below this call has a deadline. The store hands asyncpg a bare DSN, so there is no
# command_timeout, and pool acquisition with timeout=None waits on the queue forever. uvicorn does
# not cancel the handler when kubelet stops waiting, so an unbounded probe would park a waiter for
# the process's lifetime—and, worse, hold BaseStore.setup's lock, queueing every later probe and
# every per-request token validation behind it. Cancelling here leaves that lock released and
# setup incomplete, so the next probe retries.
#
# Kept below the chart's readiness timeoutSeconds (3) so this deadline is the one that fires: the
# handler answers 503 itself instead of kubelet abandoning a request nothing ends.
_PROBE_TIMEOUT_SECONDS = 2.0


async def ready_response(oauth_storage: AsyncKeyValue) -> JSONResponse:
    """Readiness response reporting the checks that ran.

    Postgres is a hard dependency, so an unreachable database means not ready. A database too slow
    to answer within `_PROBE_TIMEOUT_SECONDS` is reported the same way—not ready is the honest
    answer when no sign-in would complete either.
    """
    database_ok = True
    try:
        async with asyncio.timeout(_PROBE_TIMEOUT_SECONDS):
            _ = await oauth_storage.get(_PROBE_KEY, collection=_PROBE_COLLECTION)
    except TimeoutError:
        database_ok = False
        logger.warning("ready.database_timeout", extra={"timeout_seconds": _PROBE_TIMEOUT_SECONDS})
    except Exception:
        database_ok = False
        logger.warning("ready.database_unreachable", exc_info=True)

    checks = {"database": database_ok}
    return JSONResponse(
        {"status": "healthy" if database_ok else "unhealthy", "checks": checks},
        status_code=200 if database_ok else 503,
    )
