from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastmcp import FastMCP
from opentelemetry.instrumentation.aio_pika import AioPikaInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

from edgar_mcp.api.probes import create_probe_router
from edgar_mcp.config import AppConfig, DatabaseConfig, RabbitConfig
from edgar_mcp.db.engine import create_engine, create_session_factory
from edgar_mcp.logging import configure_logging, get_logger
from edgar_mcp.metrics import configure_metrics, create_metrics_app
from edgar_mcp.middleware import TraceContextMiddleware
from edgar_mcp.queue.connection import create_channel, create_connection
from edgar_mcp.queue.consumer import Consumer
from edgar_mcp.queue.events import EdgarEvent

load_dotenv()

app_config = AppConfig()
db_config = DatabaseConfig()
rabbit_config = RabbitConfig()

configure_logging(app_config)

logger = get_logger("main")


async def handle_event(event: EdgarEvent) -> None:
    """Process incoming events from queue."""
    logger.info("Processing event", event_type=event.type)


@asynccontextmanager
async def app_lifespan(app: FastAPI):
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
    app.state.rabbitmq_connection = await create_connection(rabbit_config)
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


async def _safe_shutdown(name: str, fn) -> None:
    try:
        await fn()
    except Exception as e:
        logger.error("Shutdown error", component=name, error=str(e))


mcp = FastMCP(
    "Edgar MCP",
    version=app_config.version,
)

mcp_app = mcp.http_app(path="/")


@asynccontextmanager
async def combined_lifespan(app: FastAPI):
    """Combine app lifespan with FastMCP lifespan."""
    async with app_lifespan(app), mcp_app.lifespan(app):
        yield


app = FastAPI(
    title="Edgar MCP",
    version=app_config.version,
    lifespan=combined_lifespan,
)

app.add_middleware(TraceContextMiddleware)

app.mount("/mcp", mcp_app)
app.mount("/metrics", create_metrics_app())


def main():
    """Entry point for running the application."""
    import uvicorn

    uvicorn.run(
        "edgar_mcp.main:app",
        host="0.0.0.0",
        port=app_config.port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
