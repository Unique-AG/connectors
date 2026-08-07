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
    """Fetch the custom-field schema once using the configured service account.

    `credential` is assembled by `create_app` (see `_service_account_credential`) rather than
    read back off the client factory: whether a service account exists is a configuration
    question, and this module has no business holding a config object to answer it. `None` is
    the normal case, not a failure.

    Errors are logged and swallowed: a Backstop outage at boot must not stop this service from
    serving, and the schema will be fetched lazily by the first authenticated caller instead.
    """
    if credential is None:
        logger.info("custom_fields.warmup.skipped", extra={"reason": "no_service_account"})
        return

    try:
        await service.ensure_fresh(
            clients.for_credential(credential),
            subject=credential.username,
        )
    except Exception:
        logger.exception("custom_fields.warmup.failed")
        return
    logger.info("custom_fields.warmup.completed")


@asynccontextmanager
async def warmup_lifespan(
    service: CustomFieldsService,
    clients: BackstopClientFactory,
    credential: BackstopCredentialSecret | None,
) -> AsyncGenerator[None, None]:
    """Run schema warming in the background for the lifetime of the app.

    Detached rather than awaited so `/ready` and `/health` come up immediately — a full
    `/custom-field-definitions` pagination can take seconds, and readiness shouldn't wait on
    an optional cache fill. Cancelled on shutdown if still in flight.
    """
    task = asyncio.create_task(warm_custom_field_schema(service, clients, credential))
    try:
        yield
    finally:
        if not task.done():
            _ = task.cancel()
        # Await so a cancelled or failed task can't outlive the app or go unretrieved.
        _ = await asyncio.gather(task, return_exceptions=True)
