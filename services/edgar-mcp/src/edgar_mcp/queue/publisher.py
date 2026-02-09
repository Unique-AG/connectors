from aio_pika import DeliveryMode, Message
from aio_pika.abc import AbstractChannel

# Sccording to Opus cloudevents have incomplete type stubs, resulting in pyright error
from cloudevents.conversion import to_json  # pyright: ignore[reportUnknownVariableType]

from edgar_mcp.logging import get_logger
from edgar_mcp.queue.events import EdgarEvent, create_event

logger = get_logger("publisher")


class Publisher:
    """RabbitMQ message publisher using CloudEvents."""

    def __init__(self, channel: AbstractChannel, queue_name: str):
        self.channel: AbstractChannel = channel
        self.queue_name: str = queue_name

    async def setup(self) -> None:
        """Declare the queue."""
        await self.channel.declare_queue(self.queue_name, durable=True)

    async def publish(self, event: EdgarEvent) -> None:
        """Serialize a CloudEvent and publish it to the queue."""
        cloud_event = create_event(event)
        body = to_json(cloud_event)
        message = Message(
            body,
            content_type="application/cloudevents+json",
            message_id=cloud_event.id,
            delivery_mode=DeliveryMode.PERSISTENT,
        )
        await self.channel.default_exchange.publish(
            message,
            routing_key=self.queue_name,
        )
        logger.info(
            "Message published",
            queue=self.queue_name,
            event_type=cloud_event.type,
            event_id=cloud_event.id,
        )
