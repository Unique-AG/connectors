import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from backstop_mcp.backstop_client import BackstopClientFactory, BackstopCredentialSecret
from backstop_mcp.features.custom_fields.service import CustomFieldsService

logger = logging.getLogger(__name__)


async def warm_custom_field_schema(
    service: CustomFieldsService,
    clients: BackstopClientFactory,
    credential: BackstopCredentialSecret | None,
) -> None:
    """Probe Backstop with the configured service account at boot.

    Schema snapshots are keyed by MCP OAuth `subject`, so a service-account fill cannot seed
    end-user catalogs without breaking caller isolation. This warmup only verifies the account
    can reach Backstop; each caller's first authenticated `tools/list` or `list_custom_fields`
    fills their own cache via `ensure_fresh`.

    `credential` is assembled by `create_app` (see `_service_account_credential`) rather than
    read back off the client factory. `None` is the normal case, not a failure. Errors are
    logged and swallowed: a Backstop outage at boot must not stop this service from serving.
    """
    del service  # retained for call-site compatibility with `create_app` wiring
    if credential is None:
        logger.info("custom_fields.warmup.skipped", extra={"reason": "no_service_account"})
        return

    try:
        await clients.for_credential(credential).raw_request("GET", "/system-info")
    except Exception:
        logger.exception("custom_fields.warmup.failed")
        return
    logger.info("custom_fields.warmup.completed", extra={"mode": "connectivity_probe"})


@asynccontextmanager
async def warmup_lifespan(
    service: CustomFieldsService,
    clients: BackstopClientFactory,
    credential: BackstopCredentialSecret | None,
) -> AsyncGenerator[None, None]:
    """Run the service-account connectivity probe in the background for the app lifetime.

    Detached rather than awaited so `/ready` and `/health` come up immediately. Cancelled on
    shutdown if still in flight.
    """
    task = asyncio.create_task(warm_custom_field_schema(service, clients, credential))
    try:
        yield
    finally:
        if not task.done():
            _ = task.cancel()
        # Await so a cancelled or failed task can't outlive the app or go unretrieved.
        _ = await asyncio.gather(task, return_exceptions=True)
