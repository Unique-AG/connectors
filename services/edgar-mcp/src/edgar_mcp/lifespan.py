"""Application lifespan management."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastmcp.server.http import StarletteWithLifespan
from opentelemetry.instrumentation.aio_pika import AioPikaInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

from edgar_mcp.api.probes import create_probe_router
from edgar_mcp.config import AppConfig, DatabaseConfig, RabbitMqConfig
from edgar_mcp.db.engine import create_engine, create_session_factory
from edgar_mcp.handlers import handle_event
from edgar_mcp.logging import get_logger
from edgar_mcp.metrics import configure_metrics
from edgar_mcp.queue.connection import create_channel, create_connection
from edgar_mcp.queue.consumer import Consumer

logger = get_logger(__name__)


async def _safe_shutdown(name: str, fn: Callable[[], Awaitable[None]]) -> None:
    """Safely shutdown a component, logging any errors."""
    try:
        await fn()
    except Exception as e:
        logger.error("Shutdown error", component=name, error=str(e))


@asynccontextmanager
async def app_lifespan(
    app: FastAPI,
    app_config: AppConfig,
    db_config: DatabaseConfig,
    rabbit_mq_config: RabbitMqConfig,
) -> AsyncIterator[None]:
    """Application lifespan: startup and shutdown."""
    logger.info("Starting application", version=app_config.version)

    # Initialize metrics
    app.state.meter_provider = configure_metrics(app_config)
    logger.info("Metrics configured")

    # Initialize database
    app.state.db_engine = create_engine(db_config)
    app.state.session_factory = create_session_factory(app.state.db_engine)
    logger.info("Database connected")

    # Setup OpenTelemetry instrumentation
    FastAPIInstrumentor.instrument_app(app, excluded_urls="/probe,/health,/metrics")
    SQLAlchemyInstrumentor().instrument(engine=app.state.db_engine.sync_engine)
    AioPikaInstrumentor().instrument()

    # Initialize RabbitMQ
    app.state.rabbitmq_connection = await create_connection(rabbit_mq_config)
    app.state.rabbitmq_channel = await create_channel(app.state.rabbitmq_connection)
    logger.info("RabbitMQ connected")

    # Start message consumer
    app.state.consumer = Consumer(app.state.rabbitmq_channel, "edgar-notifications")
    await app.state.consumer.setup()
    await app.state.consumer.start(handle_event)
    logger.info("Consumer started")

    # Register probe routes with dependencies
    app.include_router(
        create_probe_router(
            app_config,
            app.state.session_factory,
            app.state.rabbitmq_connection,
        )
    )

    yield

    logger.info("Shutting down")
    await _safe_shutdown("consumer", app.state.consumer.stop)
    await _safe_shutdown("rabbitmq_channel", app.state.rabbitmq_channel.close)
    await _safe_shutdown("rabbitmq_connection", app.state.rabbitmq_connection.close)
    await _safe_shutdown("db_engine", app.state.db_engine.dispose)
    logger.info("Shutdown complete")


@asynccontextmanager
async def combined_lifespan(
    app: FastAPI,
    app_config: AppConfig,
    db_config: DatabaseConfig,
    rabbit_mq_config: RabbitMqConfig,
    mcp_app: StarletteWithLifespan,
) -> AsyncIterator[None]:
    """Combine app lifespan with FastMCP lifespan.

    Args:
        app: FastAPI application instance.
        app_config: Application configuration.
        db_config: Database configuration.
        rabbit_mq_config: RabbitMQ configuration.
        mcp_app: FastMCP HTTP app instance (StarletteWithLifespan).
    """
    async with app_lifespan(
        app, app_config, db_config, rabbit_mq_config
    ), mcp_app.lifespan(app):
        yield
