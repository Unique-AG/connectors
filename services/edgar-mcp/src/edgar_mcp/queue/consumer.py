from collections.abc import Awaitable, Callable

import structlog
from aio_pika import IncomingMessage
from aio_pika.abc import AbstractQueue, AbstractRobustChannel
from cloudevents.conversion import from_json
from cloudevents.pydantic import CloudEvent

from edgar_mcp.logging import get_logger
from edgar_mcp.queue.events import EdgarEvent, parse_event_data

logger = get_logger("consumer")

EventHandler = Callable[[EdgarEvent], Awaitable[None]]


class Consumer:
    """RabbitMQ message consumer using CloudEvents."""

    def __init__(self, channel: AbstractRobustChannel, queue_name: str):
        self.channel = channel
        self.queue_name = queue_name
        self._queue: AbstractQueue | None = None
        self._consumer_tag: str | None = None

    async def setup(self) -> None:
        """Declare the queue."""
        self._queue = await self.channel.declare_queue(
            self.queue_name,
            durable=True,
        )

    async def start(self, handler: EventHandler) -> None:
        """Start consuming messages, deserializing each as a CloudEvent."""
        if self._queue is None:
            raise RuntimeError("Must call setup() before start()")

        async def process(message: IncomingMessage) -> None:
            structlog.contextvars.clear_contextvars()
            structlog.contextvars.bind_contextvars(
                message_id=message.message_id,
                correlation_id=message.correlation_id,
            )

            try:
                cloud_event = from_json(CloudEvent, message.body)
                event = parse_event_data(cloud_event)
            except Exception as e:
                logger.error("Invalid CloudEvent", error=str(e), exc_info=True)
                await message.nack(requeue=False)
                return

            structlog.contextvars.bind_contextvars(
                event_type=cloud_event["type"],
                event_id=cloud_event["id"],
                event_source=cloud_event["source"],
            )

            logger.info("Processing event")
            try:
                await handler(event)
                await message.ack()
                logger.info("Event processed")
            except Exception as e:
                logger.error("Event processing failed", error=str(e), exc_info=True)
                await message.nack(requeue=False)

        self._consumer_tag = await self._queue.consume(process)
        logger.info("Consumer started", queue=self.queue_name)

    async def stop(self) -> None:
        """Stop consuming messages."""
        if self._queue is not None and self._consumer_tag is not None:
            await self._queue.cancel(self._consumer_tag)
            self._consumer_tag = None
            logger.info("Consumer stopped")
