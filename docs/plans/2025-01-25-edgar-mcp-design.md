# Edgar MCP Service Design

Python-based MCP service using FastMCP 3.0.0-beta.1, matching patterns from existing NestJS services.

## Library Stack

| Requirement | Library | Notes |
|-------------|---------|-------|
| MCP Server | fastmcp 3.0.0b1 | FastMCP 3.0 beta |
| Schema validation | pydantic 2.x | Built into FastMCP |
| HTTP Framework | fastapi | For probes, webhooks |
| Database | sqlalchemy[asyncio] + asyncpg | PostgreSQL async |
| Migrations | alembic | Database migrations |
| Queue | aio-pika | RabbitMQ async client |
| Logging | structlog | NDJSON output (pino-compatible) |
| Metrics | opentelemetry-exporter-prometheus | Separate port, like nestjs-otel |
| Instrumentation | opentelemetry-instrumentation-* | FastAPI, SQLAlchemy, aio-pika |

## Project Structure

```
services/edgar-mcp/
├── src/
│   └── edgar_mcp/
│       ├── __init__.py
│       ├── py.typed
│       ├── main.py                    # Entry point, FastMCP + FastAPI setup
│       ├── config.py                  # Pydantic settings (env vars)
│       ├── logging.py                 # structlog configuration
│       ├── metrics.py                 # OpenTelemetry/Prometheus setup
│       │
│       ├── db/
│       │   ├── __init__.py
│       │   ├── engine.py              # AsyncEngine setup
│       │   ├── models.py              # SQLAlchemy models (Subscription, etc.)
│       │   └── migrations/            # Alembic migrations
│       │
│       ├── queue/
│       │   ├── __init__.py
│       │   ├── connection.py          # aio-pika connection management
│       │   ├── consumer.py            # Message consumer
│       │   └── publisher.py           # Message publisher
│       │
│       ├── mcp/
│       │   ├── __init__.py
│       │   ├── server.py              # FastMCP server definition
│       │   ├── tools/                 # MCP tools
│       │   └── resources/             # MCP resources
│       │
│       └── api/
│           ├── __init__.py
│           └── probes.py              # /probe, /health endpoints
│
├── tests/
├── pyproject.toml
├── Dockerfile
└── deploy/
    └── helm-charts/
```

## Configuration

Environment variables with Pydantic Settings, supporting both full URL and individual parts for database:

```python
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_")

    log_level: str = "info"
    version: str = "0.0.0"
    environment: str = "production"

class DatabaseConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DB_")

    url: str | None = None
    host: str = "localhost"
    port: int = 5432
    name: str = "edgar_mcp"
    user: str = "postgres"
    password: str | None = None

    @model_validator(mode="after")
    def build_url(self) -> "DatabaseConfig":
        if self.url is not None:
            # Ensure asyncpg driver is specified
            if self.url.startswith("postgresql://"):
                self.url = self.url.replace("postgresql://", "postgresql+asyncpg://", 1)
        else:
            if self.password is None:
                raise ValueError("Either DB_URL or DB_PASSWORD must be set")
            self.url = f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"
        return self

class RabbitConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RABBITMQ_")

    url: str | None = None
    host: str = "localhost"
    port: int = 5672
    user: str = "guest"
    password: str = "guest"
    vhost: str = "/"

    @model_validator(mode="after")
    def build_url(self) -> "RabbitConfig":
        if self.url is None:
            vhost = self.vhost if self.vhost == "/" else self.vhost.lstrip("/")
            self.url = f"amqp://{self.user}:{self.password}@{self.host}:{self.port}/{vhost}"
        return self

class MetricsConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OTEL_EXPORTER_PROMETHEUS_")

    host: str = "0.0.0.0"
    port: int = 9464
```

## Logging

structlog configured to output pino-compatible NDJSON:

```python
import logging
import structlog
from structlog.typing import Processor

def configure_logging(config: AppConfig) -> None:
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", key="time"),
    ]

    if config.environment == "development":
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    level_name = config.log_level.upper()
    level = logging.getLevelName(level_name)
    if isinstance(level, str):
        raise ValueError(f"Invalid log level: {config.log_level}")

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    logger = structlog.get_logger()
    if name:
        logger = logger.bind(logger=name)
    return logger
```

Output formats:
- **Development**: `2025-01-22T14:30:00.000Z [info     ] Processing message         message_id=abc-123`
- **Production**: `{"time": "2025-01-22T14:30:00.000Z", "level": "info", "event": "Processing message", "message_id": "abc-123"}`

### Trace Context Middleware

Binds OpenTelemetry trace ID to structlog for request correlation:

```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
import structlog
from opentelemetry import trace

class TraceContextMiddleware(BaseHTTPMiddleware):
    EXCLUDED_PATHS = {"/probe", "/health"}

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.EXCLUDED_PATHS:
            return await call_next(request)

        structlog.contextvars.clear_contextvars()

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx.is_valid:
            structlog.contextvars.bind_contextvars(
                trace_id=format(ctx.trace_id, "032x")
            )

        return await call_next(request)
```

## Database

SQLAlchemy 2.0 async with asyncpg:

```python
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

def create_engine(config: DatabaseConfig) -> AsyncEngine:
    return create_async_engine(
        config.url,
        echo=False,
        pool_size=5,
        max_overflow=10,
    )

def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

@asynccontextmanager
async def get_session(factory: async_sessionmaker[AsyncSession]) -> AsyncGenerator[AsyncSession, None]:
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

## Queue (RabbitMQ)

aio-pika with auto-reconnect and single-message processing:

```python
from aio_pika import connect_robust, IncomingMessage
from aio_pika.abc import AbstractRobustConnection, AbstractRobustChannel

async def create_connection(config: RabbitConfig) -> AbstractRobustConnection:
    return await connect_robust(config.url)

async def create_channel(connection: AbstractRobustConnection) -> AbstractRobustChannel:
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=1)  # Process one at a time
    return channel
```

Consumer binds structlog context per message:

```python
async def process(message: IncomingMessage) -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        message_id=message.message_id,
        correlation_id=message.correlation_id,
    )
    # Process message...
```

## Metrics

OpenTelemetry with Prometheus exporter on separate port (matching nestjs-otel pattern):

```python
from opentelemetry import metrics
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from prometheus_client import start_http_server

def configure_metrics(config: AppConfig, metrics_config: MetricsConfig) -> MeterProvider:
    resource = Resource.create({
        SERVICE_NAME: "edgar-mcp",
        SERVICE_VERSION: config.version,
    })

    reader = PrometheusMetricReader()
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)

    start_http_server(port=metrics_config.port, addr=metrics_config.host)

    return provider
```

Auto-instrumentation:

```python
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.aio_pika import AioPikaInstrumentor

def setup_instrumentation(app, engine):
    FastAPIInstrumentor.instrument_app(app, excluded_urls="/probe,/health")
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
    AioPikaInstrumentor().instrument()
```

Environment variables (matching NestJS pattern):
```bash
OTEL_EXPORTER_PROMETHEUS_HOST=0.0.0.0
OTEL_EXPORTER_PROMETHEUS_PORT=51346
```

## Probes

Matching `@unique-ag/probe` pattern with added health checks:

```python
from fastapi import APIRouter, Response, status

router = APIRouter(tags=["Monitoring"])

def create_probe_router(config, session_factory, rabbitmq_connection) -> APIRouter:

    @router.get("/probe", include_in_schema=False)
    async def probe() -> dict:
        return {"version": config.version}

    @router.get("/health", include_in_schema=False)
    async def health(response: Response) -> dict:
        checks = {}
        healthy = True

        # Check PostgreSQL
        try:
            async with session_factory() as session:
                await session.execute(text("SELECT 1"))
            checks["postgres"] = "ok"
        except Exception as e:
            checks["postgres"] = f"error: {e}"
            healthy = False

        # Check RabbitMQ
        try:
            if rabbitmq_connection.is_closed:
                raise ConnectionError("Connection closed")
            checks["rabbitmq"] = "ok"
        except Exception as e:
            checks["rabbitmq"] = f"error: {e}"
            healthy = False

        if not healthy:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

        return {"status": "healthy" if healthy else "unhealthy", "checks": checks}

    return router
```

## Main Application

Combined lifespan for FastAPI and FastMCP:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastmcp import FastMCP

mcp = FastMCP("Edgar MCP", version=app_config.version)
mcp_app = mcp.http_app(path="/")

@asynccontextmanager
async def app_lifespan(app: FastAPI):
    # Initialize: metrics, database, RabbitMQ, consumer
    yield
    # Shutdown: consumer, RabbitMQ, database

@asynccontextmanager
async def combined_lifespan(app: FastAPI):
    async with app_lifespan(app):
        async with mcp_app.lifespan(app):
            yield

app = FastAPI(
    title="Edgar MCP",
    version=app_config.version,
    lifespan=combined_lifespan,
)

app.mount("/mcp", mcp_app)
```

## Dependencies (pyproject.toml)

```toml
[project]
name = "edgar-mcp"
requires-python = ">=3.12"
dependencies = [
    "fastmcp==3.0.0b1",
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.34.0",
    "pydantic>=2.10.0",
    "pydantic-settings>=2.7.0",
    "python-dotenv>=1.0.0",
    "sqlalchemy[asyncio]>=2.0.0",
    "asyncpg>=0.30.0",
    "alembic>=1.14.0",
    "aio-pika>=9.5.0",
    "structlog>=25.0.0",
    "opentelemetry-api>=1.29.0",
    "opentelemetry-sdk>=1.29.0",
    "opentelemetry-exporter-prometheus>=0.50b0",
    "opentelemetry-instrumentation-fastapi>=0.50b0",
    "opentelemetry-instrumentation-sqlalchemy>=0.50b0",
    "opentelemetry-instrumentation-aio-pika>=0.50b0",
]
```

## Deployment

Ports:
- Application: `8000` (or as configured)
- Metrics: `51346` (via `OTEL_EXPORTER_PROMETHEUS_PORT`)

Kubernetes probes:
```yaml
livenessProbe:
  httpGet:
    path: /probe
    port: 8000
readinessProbe:
  httpGet:
    path: /health
    port: 8000
```
