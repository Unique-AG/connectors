"""FastAPI application factory."""

from fastapi import FastAPI
from fastmcp import FastMCP

from edgar_mcp.config import AppConfig, DatabaseConfig, RabbitMqConfig
from edgar_mcp.lifespan import combined_lifespan
from edgar_mcp.logging import configure_logging
from edgar_mcp.metrics import create_metrics_app
from edgar_mcp.middleware import TraceContextMiddleware


def create_app(
    app_config: AppConfig | None = None,
    db_config: DatabaseConfig | None = None,
    rabbit_mq_config: RabbitMqConfig | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        app_config: Application configuration. Defaults to AppConfig().
        db_config: Database configuration. Defaults to DatabaseConfig().
        rabbit_mq_config: RabbitMQ configuration. Defaults to RabbitMqConfig().

    Returns:
        Configured FastAPI application with configs stored in app.state.
    """
    # Use defaults if not provided
    app_config = app_config or AppConfig()
    db_config = db_config or DatabaseConfig()
    rabbit_mq_config = rabbit_mq_config or RabbitMqConfig()

    # Configure logging
    configure_logging(app_config)

    # Create FastMCP instance
    mcp = FastMCP(
        "Edgar MCP",
        version=app_config.version,
    )
    mcp_app = mcp.http_app(path="/")

    # Create FastAPI app with combined lifespan
    app = FastAPI(
        title="Edgar MCP",
        version=app_config.version,
        lifespan=lambda app_: combined_lifespan(
            app_, app_config, db_config, rabbit_mq_config, mcp_app
        ),
    )

    # Store configs in app state for access elsewhere
    app.state.app_config = app_config
    app.state.db_config = db_config
    app.state.rabbit_mq_config = rabbit_mq_config

    # Add middleware
    app.add_middleware(TraceContextMiddleware)

    # Mount sub-applications
    app.mount("/mcp", mcp_app)
    app.mount("/metrics", create_metrics_app())

    return app
