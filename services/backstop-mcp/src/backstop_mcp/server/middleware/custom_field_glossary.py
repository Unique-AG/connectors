from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import ClassVar, override

import mcp.types as mt
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import Tool

from backstop_mcp.backstop_client.client import BackstopClient
from backstop_mcp.features.custom_fields.glossary import format_glossaries
from backstop_mcp.features.custom_fields.service import CustomFieldsService
from backstop_mcp.logging import get_logger

logger = get_logger(__name__)

# Resolves a client authenticated as the in-flight MCP caller — in practice
# `BackstopClientFactory.for_current_caller`. Injected as a callable rather than taking the
# factory itself, matching how `BackstopClient` receives its own collaborators
# (`HttpClientProvider`, `AuthFailureHook`).
type CallerClientProvider = Callable[[], Awaitable[BackstopClient]]


class CustomFieldGlossaryMiddleware(Middleware):
    """Append per-entity custom-field glossaries to tool descriptions on tools/list.

    Collaborators are injected by `create_app()`, not reached through `server.runtime`: unlike a
    tool function (whose signature FastMCP owns), middleware is constructed by us, so there is
    no reason for it to consult a process-wide global. That also keeps this module free of any
    `server.tools` import — `glossary_entities` is a snapshot of the tool registry's scopes,
    passed in rather than looked up.
    """

    # How long to stop attempting a schema warm after one fails. Without it, a Backstop outage
    # makes every tools/list wait out a full upstream timeout for a glossary that is advisory.
    WARM_FAILURE_COOLDOWN: ClassVar[timedelta] = timedelta(minutes=5)

    def __init__(
        self,
        service: CustomFieldsService,
        *,
        client_for_caller: CallerClientProvider,
        glossary_entities: Mapping[str, tuple[str, ...]],
    ) -> None:
        super().__init__()
        self._service: CustomFieldsService = service
        self._client_for_caller: CallerClientProvider = client_for_caller
        # A snapshot, not a callable: the scopes derive from `TOOL_SPECS`, a module constant, so
        # there is nothing to re-read per request. `Mapping` keeps it read-only here.
        self._glossary_entities: Mapping[str, tuple[str, ...]] = glossary_entities
        self._warm_failed_at: datetime | None = None

    @override
    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        tools = await call_next(context)
        service = self._service

        # Cheap path first: a DB read needs no credential and no Backstop round trip.
        await service.load_cached()
        if not service.is_fresh:
            await self._warm()

        enriched: list[Tool] = []
        for tool in tools:
            entity_types = self._glossary_entities.get(tool.name)
            if not entity_types:
                enriched.append(tool)
                continue
            glossary = format_glossaries(
                [(entity, service.definitions_for(entity)) for entity in entity_types]
            )
            if not glossary:
                enriched.append(tool)
                continue
            enriched.append(
                tool.model_copy(update={"description": (tool.description or "") + glossary})
            )
        return enriched

    async def _warm(self) -> None:
        """Fetch the schema using the listing caller's own credential.

        `tools/list` is authenticated (the whole MCP endpoint is), so a real client is available
        here — but only callers who find the snapshot missing or past its TTL pay for it, since it
        is shared across every user of one Backstop instance. Configure a service account
        (`BACKSTOP_SERVICE_USERNAME`) to move that cost to startup instead.

        Any failure is swallowed: the glossary is advisory, and no listing should break because
        schema enrichment couldn't run. That deliberately includes `NotConnectedError` from an
        unauthenticated listing. Callers fall back to `resolve_custom_field`, which is what its
        docstring already tells them to do when the glossary is missing.
        """
        if self._in_failure_cooldown():
            return
        try:
            client = await self._client_for_caller()
            await self._service.ensure_fresh(client)
        except Exception:
            self._warm_failed_at = datetime.now(UTC)
            logger.warning("custom_fields.glossary.warm_failed", exc_info=True)

    def _in_failure_cooldown(self) -> bool:
        if self._warm_failed_at is None:
            return False
        if datetime.now(UTC) - self._warm_failed_at < self.WARM_FAILURE_COOLDOWN:
            return True
        self._warm_failed_at = None
        return False
