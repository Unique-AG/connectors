from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from backstop_mcp.auth.crypto import BackstopCredentialSecret
from backstop_mcp.backstop_client.client import create_backstop_client
from backstop_mcp.config import BackstopConfig
from backstop_mcp.custom_fields.service import CustomFieldsService
from backstop_mcp.logging import get_logger

logger = get_logger(__name__)


async def warm_custom_field_schema(service: CustomFieldsService, config: BackstopConfig) -> None:
    """Fetch the custom-field schema once using the configured service account.

    Errors are logged and swallowed: a Backstop outage at boot must not stop this service
    from serving, and the schema will be fetched lazily by the first authenticated caller
    instead. No service account configured is the normal case, not a failure.
    """
    if config.service_username is None or config.service_api_token is None:
        logger.info("custom_fields.warmup.skipped", reason="no_service_account")
        return

    credential = BackstopCredentialSecret(
        username=config.service_username, api_token=config.service_api_token
    )
    try:
        async with create_backstop_client(config.base_url, credential) as client:
            await service.ensure_fresh(client)
    except Exception:
        logger.exception("custom_fields.warmup.failed")
        return
    logger.info("custom_fields.warmup.completed")


@asynccontextmanager
async def warmup_lifespan(
    service: CustomFieldsService, config: BackstopConfig
) -> AsyncGenerator[None, None]:
    """Run schema warming in the background for the lifetime of the app.

    Detached rather than awaited so `/probe` and `/health` come up immediately — a full
    `/custom-field-definitions` pagination can take seconds, and readiness shouldn't wait on
    an optional cache fill. Cancelled on shutdown if still in flight.
    """
    task = asyncio.create_task(warm_custom_field_schema(service, config))
    try:
        yield
    finally:
        if not task.done():
            _ = task.cancel()
        # Await so a cancelled or failed task can't outlive the app or go unretrieved.
        _ = await asyncio.gather(task, return_exceptions=True)
