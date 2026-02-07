import asyncio

import pytest
from aio_pika import Message, connect_robust
from pydantic import ValidationError

from edgar_mcp.queue.connection import create_channel
from edgar_mcp.queue.consumer import Consumer
from edgar_mcp.queue.events import (
    EVENT_SOURCE,
    PING_EVENT_TYPE,
    PingData,
    PingEvent,
    create_event,
    parse_event_data,
)
from edgar_mcp.queue.publisher import Publisher


class TestEvents:
    """Unit tests for events.py."""

    def test_create_event_wraps_in_cloud_event(self):
        ping = PingEvent(data=PingData(message="hello"))
        cloud_event = create_event(ping)

        assert cloud_event["type"] == PING_EVENT_TYPE
        assert cloud_event["source"] == EVENT_SOURCE
        assert cloud_event.data == {"message": "hello"}

    def test_parse_event_data_roundtrips(self):
        original = PingEvent(data=PingData(message="roundtrip"))
        cloud_event = create_event(original)

        parsed = parse_event_data(cloud_event)

        assert isinstance(parsed, PingEvent)
        assert parsed.type == original.type
        assert parsed.data.message == "roundtrip"

    def test_parse_event_data_rejects_unknown_type(self):
        from cloudevents.pydantic import CloudEvent

        cloud_event = CloudEvent(
            type="com.unknown.event",
            source="/test",
            data={"key": "value"},
        )

        with pytest.raises(ValidationError):
            parse_event_data(cloud_event)


@pytest.fixture(scope="module")
def rabbitmq_container():
    from testcontainers.rabbitmq import RabbitMqContainer

    with RabbitMqContainer("rabbitmq:3-alpine") as rabbitmq:
        yield rabbitmq


def _amqp_url(container) -> str:
    host = container.get_container_host_ip()
    port = container.get_exposed_port(container.port)
    return f"amqp://{container.username}:{container.password}@{host}:{port}/{container.vhost}"


class TestQueueMessageFlow:
    """Integration tests using testcontainers RabbitMQ."""

    @pytest.mark.asyncio
    async def test_publish_and_consume_cloud_event(self, rabbitmq_container):
        connection = await connect_robust(_amqp_url(rabbitmq_container))
        try:
            pub_channel = await create_channel(connection)
            publisher = Publisher(pub_channel, "test-publish-consume")
            await publisher.setup()

            con_channel = await create_channel(connection)
            consumer = Consumer(con_channel, "test-publish-consume")
            await consumer.setup()

            received: asyncio.Future[PingEvent] = asyncio.get_running_loop().create_future()

            async def handler(event):
                received.set_result(event)

            await consumer.start(handler)

            ping = PingEvent(data=PingData(message="integration"))
            await publisher.publish(ping)

            result = await asyncio.wait_for(received, timeout=5.0)

            assert isinstance(result, PingEvent)
            assert result.data.message == "integration"
        finally:
            await consumer.stop()
            await connection.close()

    @pytest.mark.asyncio
    async def test_consumer_nacks_invalid_cloud_event(self, rabbitmq_container):
        connection = await connect_robust(_amqp_url(rabbitmq_container))
        try:
            queue_name = "test-nack-invalid"

            con_channel = await create_channel(connection)
            consumer = Consumer(con_channel, queue_name)
            await consumer.setup()

            handler_called = asyncio.Event()

            async def handler(event):
                handler_called.set()

            await consumer.start(handler)

            pub_channel = await create_channel(connection)
            await pub_channel.declare_queue(queue_name, durable=True)
            await pub_channel.default_exchange.publish(
                Message(b"not a valid cloud event"),
                routing_key=queue_name,
            )

            await asyncio.sleep(1.0)

            assert not handler_called.is_set(), "Handler should not be called for invalid messages"

            queue_state = await pub_channel.declare_queue(queue_name, passive=True)
            assert queue_state.declaration_result.message_count == 0
        finally:
            await consumer.stop()
            await connection.close()

    @pytest.mark.asyncio
    async def test_consumer_processes_events_sequentially(self, rabbitmq_container):
        connection = await connect_robust(_amqp_url(rabbitmq_container))
        try:
            queue_name = "test-sequential"

            pub_channel = await create_channel(connection)
            publisher = Publisher(pub_channel, queue_name)
            await publisher.setup()

            for i in range(3):
                await publisher.publish(PingEvent(data=PingData(message=str(i))))

            con_channel = await create_channel(connection)
            consumer = Consumer(con_channel, queue_name)
            await consumer.setup()

            events: list[tuple[int, str]] = []
            done = asyncio.Event()

            async def handler(event):
                idx = int(event.data.message)
                events.append((idx, "start"))
                await asyncio.sleep(0.1)
                events.append((idx, "end"))
                if idx == 2:
                    done.set()

            await consumer.start(handler)

            await asyncio.wait_for(done.wait(), timeout=5.0)

            assert events == [
                (0, "start"), (0, "end"),
                (1, "start"), (1, "end"),
                (2, "start"), (2, "end"),
            ]
        finally:
            await consumer.stop()
            await connection.close()
