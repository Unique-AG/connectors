"""Event handlers for Edgar MCP."""

from edgar_mcp.logging import get_logger
from edgar_mcp.queue.events import EdgarEvent

logger = get_logger(__name__)


async def handle_event(event: EdgarEvent) -> None:
    """Process incoming events from queue."""
    logger.info("Processing event", event_type=event.type)
