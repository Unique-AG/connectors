from aio_pika import connect_robust
from aio_pika.abc import AbstractChannel, AbstractRobustConnection

from edgar_mcp.config import RabbitMqConfig
from edgar_mcp.logging import get_logger

logger = get_logger("queue")


async def create_connection(config: RabbitMqConfig) -> AbstractRobustConnection:
    """Create robust RabbitMQ connection with auto-reconnect."""
    connection = await connect_robust(config.connection_url)
    logger.info("Connected to RabbitMQ")
    return connection


async def create_channel(connection: AbstractRobustConnection) -> AbstractChannel:
    """Create channel with prefetch=1 for sequential processing."""
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=1)
    return channel
