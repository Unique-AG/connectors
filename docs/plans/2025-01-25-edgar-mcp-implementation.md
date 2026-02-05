# Edgar MCP Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Python-based MCP service using FastMCP 3.0.0-beta.1 with PostgreSQL, RabbitMQ, structured logging, and Prometheus metrics.

**Architecture:** FastAPI serves HTTP endpoints (probes, webhooks) and mounts FastMCP for MCP protocol. SQLAlchemy async handles database, aio-pika handles message queuing. All components initialize via combined lifespan context manager.

**Tech Stack:** FastMCP 3.0.0b1, FastAPI, SQLAlchemy 2.0 + asyncpg, aio-pika, structlog, OpenTelemetry, ruff

**Design Document:** `docs/plans/2025-01-25-edgar-mcp-design.md`

---

## Task 1: Project Scaffolding

**Files:**
- Create: `services/edgar-mcp/pyproject.toml`
- Create: `services/edgar-mcp/src/edgar_mcp/__init__.py`
- Create: `services/edgar-mcp/src/edgar_mcp/py.typed`
- Create: `services/edgar-mcp/tests/__init__.py`

**Step 1: Create pyproject.toml**

```toml
[project]
name = "edgar-mcp"
version = "0.1.0"
description = "Edgar MCP service with FastMCP"
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

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "httpx>=0.27.0",
    "testcontainers[postgres,rabbitmq]>=4.0.0",
    "ruff>=0.9.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]

[tool.hatch.build.targets.wheel]
packages = ["src/edgar_mcp"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]
```

**Step 2: Create directory structure**

```bash
mkdir -p services/edgar-mcp/src/edgar_mcp/db
mkdir -p services/edgar-mcp/src/edgar_mcp/queue
mkdir -p services/edgar-mcp/src/edgar_mcp/mcp
mkdir -p services/edgar-mcp/src/edgar_mcp/api
mkdir -p services/edgar-mcp/tests
touch services/edgar-mcp/src/edgar_mcp/__init__.py
touch services/edgar-mcp/src/edgar_mcp/py.typed
touch services/edgar-mcp/src/edgar_mcp/db/__init__.py
touch services/edgar-mcp/src/edgar_mcp/queue/__init__.py
touch services/edgar-mcp/src/edgar_mcp/mcp/__init__.py
touch services/edgar-mcp/src/edgar_mcp/api/__init__.py
touch services/edgar-mcp/tests/__init__.py
```

**Step 3: Install dependencies**

Run: `cd services/edgar-mcp && uv sync --all-extras`

**Step 4: Verify pytest runs**

Run: `cd services/edgar-mcp && pytest --collect-only`
Expected: "no tests ran" (empty collection, no errors)

**Step 5: Commit**

```bash
git add services/edgar-mcp/
git commit -m "feat(edgar-mcp): scaffold project structure"
```

---

## Task 2: Configuration - Database URL Building

**Files:**
- Create: `services/edgar-mcp/src/edgar_mcp/config.py`
- Create: `services/edgar-mcp/tests/test_config.py`

**Step 1: Write failing test for database config URL building**

```python
# tests/test_config.py
import pytest


class TestDatabaseConfig:
    """Test database configuration URL building behavior."""

    def test_builds_url_from_individual_parts(self, monkeypatch):
        """When individual DB settings are provided, builds asyncpg URL."""
        monkeypatch.setenv("DB_HOST", "dbhost")
        monkeypatch.setenv("DB_PORT", "5433")
        monkeypatch.setenv("DB_NAME", "testdb")
        monkeypatch.setenv("DB_USER", "testuser")
        monkeypatch.setenv("DB_PASSWORD", "testpass")

        from edgar_mcp.config import DatabaseConfig

        config = DatabaseConfig()

        assert config.url == "postgresql+asyncpg://testuser:testpass@dbhost:5433/testdb"

    def test_uses_provided_url_directly(self, monkeypatch):
        """When DB_URL is provided, uses it directly."""
        monkeypatch.setenv("DB_URL", "postgresql+asyncpg://user:pass@host:5432/db")

        from edgar_mcp.config import DatabaseConfig

        config = DatabaseConfig()

        assert config.url == "postgresql+asyncpg://user:pass@host:5432/db"

    def test_adds_asyncpg_driver_if_missing(self, monkeypatch):
        """When URL uses postgresql:// without driver, adds +asyncpg."""
        monkeypatch.setenv("DB_URL", "postgresql://user:pass@host:5432/db")

        from edgar_mcp.config import DatabaseConfig

        config = DatabaseConfig()

        assert config.url == "postgresql+asyncpg://user:pass@host:5432/db"

    def test_raises_when_no_url_and_no_password(self, monkeypatch):
        """When neither URL nor password provided, raises error."""
        monkeypatch.delenv("DB_URL", raising=False)
        monkeypatch.delenv("DB_PASSWORD", raising=False)
        monkeypatch.delenv("DB_HOST", raising=False)
        monkeypatch.delenv("DB_NAME", raising=False)
        monkeypatch.delenv("DB_USER", raising=False)

        from edgar_mcp.config import DatabaseConfig

        with pytest.raises(ValueError, match="DB_URL not set; missing required fields:"):
            DatabaseConfig()

    def test_raises_when_partial_config(self, monkeypatch):
        """When only some individual parts provided, raises error."""
        monkeypatch.delenv("DB_URL", raising=False)
        monkeypatch.setenv("DB_HOST", "localhost")
        monkeypatch.setenv("DB_USER", "user")
        monkeypatch.delenv("DB_PASSWORD", raising=False)
        monkeypatch.delenv("DB_NAME", raising=False)

        from edgar_mcp.config import DatabaseConfig

        with pytest.raises(ValueError, match="DB_URL not set; missing required fields:"):
            DatabaseConfig()

    def test_url_encodes_special_characters(self, monkeypatch):
        """URL encoding handles special characters in password."""
        monkeypatch.setenv("DB_HOST", "localhost")
        monkeypatch.setenv("DB_USER", "user@domain")
        monkeypatch.setenv("DB_PASSWORD", "p@ss:w/rd")
        monkeypatch.setenv("DB_NAME", "testdb")

        from edgar_mcp.config import DatabaseConfig

        config = DatabaseConfig()
        assert "user%40domain" in config.url
        assert "p%40ss%3Aw%2Frd" in config.url
```

**Step 2: Run test to verify it fails**

Run: `cd services/edgar-mcp && pytest tests/test_config.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'edgar_mcp.config'"

**Step 3: Write minimal implementation**

```python
# edgar_mcp/config.py
from urllib.parse import quote_plus
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DB_")

    url: str | None = None
    host: str | None = None
    port: int = 5432
    name: str | None = None
    user: str | None = None
    password: str | None = None

    @model_validator(mode="after")
    def build_url(self) -> "DatabaseConfig":
        if self.url is not None:
            if self.url.startswith("postgresql://"):
                self.url = self.url.replace("postgresql://", "postgresql+asyncpg://", 1)
        else:
            missing = [
                name for name, val in [
                    ("DB_HOST", self.host),
                    ("DB_NAME", self.name),
                    ("DB_USER", self.user),
                    ("DB_PASSWORD", self.password),
                ]
                if val is None
            ]
            if missing:
                raise ValueError(
                    f"DB_URL not set; missing required fields: {', '.join(missing)}"
                )
            self.url = (
                f"postgresql+asyncpg://{quote_plus(self.user)}:{quote_plus(self.password)}"
                f"@{self.host}:{self.port}/{self.name}"
            )
        return self

    @property
    def connection_url(self) -> str:
        """Get the connection URL (guaranteed non-None after validation)."""
        assert self.url is not None, "URL should be set after validation"
        return self.url
```

**Step 4: Run test to verify it passes**

Run: `cd services/edgar-mcp && pytest tests/test_config.py::TestDatabaseConfig -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add services/edgar-mcp/src/edgar_mcp/config.py services/edgar-mcp/tests/test_config.py
git commit -m "feat(edgar-mcp): add database config with URL building"
```

---

## Task 3: Configuration - RabbitMQ URL Building

**Files:**
- Modify: `services/edgar-mcp/src/edgar_mcp/config.py`
- Modify: `services/edgar-mcp/tests/test_config.py`

**Step 1: Write failing test for RabbitMQ config**

```python
# tests/test_config.py (append to file)

class TestRabbitConfig:
    """Test RabbitMQ configuration URL building behavior."""

    def test_builds_url_from_individual_parts(self, monkeypatch):
        """When individual RabbitMQ settings are provided, builds AMQP URL."""
        monkeypatch.setenv("RABBITMQ_HOST", "rabbithost")
        monkeypatch.setenv("RABBITMQ_PORT", "5673")
        monkeypatch.setenv("RABBITMQ_USER", "rabbituser")
        monkeypatch.setenv("RABBITMQ_PASSWORD", "rabbitpass")
        monkeypatch.setenv("RABBITMQ_VHOST", "myvhost")

        from edgar_mcp.config import RabbitConfig

        config = RabbitConfig()

        assert config.url == "amqp://rabbituser:rabbitpass@rabbithost:5673/myvhost"

    def test_uses_provided_url_directly(self, monkeypatch):
        """When RABBITMQ_URL is provided, uses it directly."""
        monkeypatch.setenv("RABBITMQ_URL", "amqp://custom:url@host:5672/")

        from edgar_mcp.config import RabbitConfig

        config = RabbitConfig()

        assert config.url == "amqp://custom:url@host:5672/"

    def test_raises_when_no_url_and_missing_parts(self, monkeypatch):
        """When neither URL nor all required parts provided, raises error."""
        monkeypatch.delenv("RABBITMQ_URL", raising=False)
        monkeypatch.delenv("RABBITMQ_HOST", raising=False)
        monkeypatch.delenv("RABBITMQ_USER", raising=False)
        monkeypatch.delenv("RABBITMQ_PASSWORD", raising=False)

        from edgar_mcp.config import RabbitConfig

        with pytest.raises(ValueError, match="RABBITMQ_URL not set; missing required fields:"):
            RabbitConfig()

    def test_raises_when_partial_config(self, monkeypatch):
        """When only some individual parts provided, raises error."""
        monkeypatch.delenv("RABBITMQ_URL", raising=False)
        monkeypatch.setenv("RABBITMQ_HOST", "localhost")
        monkeypatch.delenv("RABBITMQ_USER", raising=False)
        monkeypatch.delenv("RABBITMQ_PASSWORD", raising=False)

        from edgar_mcp.config import RabbitConfig

        with pytest.raises(ValueError, match="RABBITMQ_URL not set; missing required fields:"):
            RabbitConfig()

    def test_url_encodes_special_characters(self, monkeypatch):
        """URL encoding handles special characters in password."""
        monkeypatch.setenv("RABBITMQ_HOST", "localhost")
        monkeypatch.setenv("RABBITMQ_USER", "user@domain")
        monkeypatch.setenv("RABBITMQ_PASSWORD", "p@ss:w/rd")

        from edgar_mcp.config import RabbitConfig

        config = RabbitConfig()
        assert "user%40domain" in config.url
        assert "p%40ss%3Aw%2Frd" in config.url

    def test_handles_root_vhost(self, monkeypatch):
        """Root vhost '/' is handled correctly in URL."""
        monkeypatch.setenv("RABBITMQ_VHOST", "/")

        from edgar_mcp.config import RabbitConfig

        config = RabbitConfig()

        assert config.url.endswith("/")
```

**Step 2: Run test to verify it fails**

Run: `cd services/edgar-mcp && pytest tests/test_config.py::TestRabbitConfig -v`
Expected: FAIL with "cannot import name 'RabbitConfig'"

**Step 3: Add RabbitConfig implementation**

```python
# edgar_mcp/config.py (append after DatabaseConfig)

class RabbitConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RABBITMQ_")

    url: str | None = None
    host: str | None = None
    port: int = 5672
    user: str | None = None
    password: str | None = None
    vhost: str = "/"

    @model_validator(mode="after")
    def build_url(self) -> "RabbitConfig":
        if self.url is None:
            missing = [
                name for name, val in [
                    ("RABBITMQ_HOST", self.host),
                    ("RABBITMQ_USER", self.user),
                    ("RABBITMQ_PASSWORD", self.password),
                ]
                if val is None
            ]
            if missing:
                raise ValueError(
                    f"RABBITMQ_URL not set; missing required fields: {', '.join(missing)}"
                )
            vhost = self.vhost if self.vhost == "/" else self.vhost.lstrip("/")
            self.url = (
                f"amqp://{quote_plus(self.user)}:{quote_plus(self.password)}"
                f"@{self.host}:{self.port}/{vhost}"
            )
        return self

    @property
    def connection_url(self) -> str:
        """Get the connection URL (guaranteed non-None after validation)."""
        assert self.url is not None, "URL should be set after validation"
        return self.url
```

**Step 4: Run test to verify it passes**

Run: `cd services/edgar-mcp && pytest tests/test_config.py::TestRabbitConfig -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add services/edgar-mcp/src/edgar_mcp/config.py services/edgar-mcp/tests/test_config.py
git commit -m "feat(edgar-mcp): add RabbitMQ config with URL building"
```

---

## Task 4: Configuration - App Config

**Files:**
- Modify: `services/edgar-mcp/src/edgar_mcp/config.py`
- Modify: `services/edgar-mcp/tests/test_config.py`

**Note:** MetricsConfig is removed since metrics are served via ASGI middleware on the main app port (see Task 11).

**Step 1: Write failing test for AppConfig**

```python
# tests/test_config.py (append to file)

class TestAppConfig:
    """Test application configuration behavior."""

    def test_loads_from_env_vars(self, monkeypatch):
        """Loads settings from APP_ prefixed env vars."""
        monkeypatch.setenv("APP_LOG_LEVEL", "debug")
        monkeypatch.setenv("APP_VERSION", "1.2.3")
        monkeypatch.setenv("APP_ENVIRONMENT", "development")

        from edgar_mcp.config import AppConfig

        config = AppConfig()

        assert config.log_level == "debug"
        assert config.version == "1.2.3"
        assert config.environment == "development"

    def test_uses_defaults(self, monkeypatch):
        """Uses sensible defaults when env vars not set."""
        monkeypatch.delenv("APP_LOG_LEVEL", raising=False)
        monkeypatch.delenv("APP_VERSION", raising=False)
        monkeypatch.delenv("APP_ENVIRONMENT", raising=False)

        from edgar_mcp.config import AppConfig

        config = AppConfig()

        assert config.log_level == "info"
        assert config.version == "0.0.0"
        assert config.environment == "production"
```

**Step 2: Run test to verify it fails**

Run: `cd services/edgar-mcp && pytest tests/test_config.py::TestAppConfig -v`
Expected: FAIL with "cannot import name 'AppConfig'"

**Step 3: Add AppConfig**

```python
# edgar_mcp/config.py (add at the top, after imports)

class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_")

    log_level: str = "info"
    version: str = "0.0.0"
    environment: str = "production"
```

**Step 4: Run test to verify it passes**

Run: `cd services/edgar-mcp && pytest tests/test_config.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add services/edgar-mcp/src/edgar_mcp/config.py services/edgar-mcp/tests/test_config.py
git commit -m "feat(edgar-mcp): add app config"
```

---

## Task 5: Logging - JSON Output in Production

**Files:**
- Create: `services/edgar-mcp/src/edgar_mcp/logging.py`
- Create: `services/edgar-mcp/tests/test_logging.py`

**Step 1: Write failing test for production JSON logging**

```python
# tests/test_logging.py
import json
import io
import sys
import pytest


class TestLogging:
    """Test logging output format behavior."""

    def test_outputs_json_in_production(self, monkeypatch):
        """In production environment, logs output as NDJSON."""
        monkeypatch.setenv("APP_ENVIRONMENT", "production")
        monkeypatch.setenv("APP_LOG_LEVEL", "info")

        # Capture stdout
        captured = io.StringIO()
        monkeypatch.setattr(sys, "stdout", captured)

        # Import fresh to pick up env vars
        from edgar_mcp.config import AppConfig
        from edgar_mcp.logging import configure_logging, get_logger

        configure_logging(AppConfig())
        logger = get_logger("test")
        logger.info("test message", extra_field="value")

        output = captured.getvalue()
        log_entry = json.loads(output.strip())

        assert log_entry["level"] == "info"
        assert log_entry["event"] == "test message"
        assert log_entry["extra_field"] == "value"
        assert "time" in log_entry

    def test_outputs_readable_in_development(self, monkeypatch):
        """In development environment, logs are human-readable."""
        monkeypatch.setenv("APP_ENVIRONMENT", "development")
        monkeypatch.setenv("APP_LOG_LEVEL", "info")

        captured = io.StringIO()
        monkeypatch.setattr(sys, "stdout", captured)

        from edgar_mcp.config import AppConfig
        from edgar_mcp.logging import configure_logging, get_logger

        configure_logging(AppConfig())
        logger = get_logger("test")
        logger.info("test message")

        output = captured.getvalue()

        # Should NOT be valid JSON (human readable format)
        with pytest.raises(json.JSONDecodeError):
            json.loads(output.strip())

        # Should contain the message
        assert "test message" in output

    def test_logger_binds_name(self, monkeypatch):
        """get_logger with name binds it to all log entries."""
        monkeypatch.setenv("APP_ENVIRONMENT", "production")
        monkeypatch.setenv("APP_LOG_LEVEL", "info")

        captured = io.StringIO()
        monkeypatch.setattr(sys, "stdout", captured)

        from edgar_mcp.config import AppConfig
        from edgar_mcp.logging import configure_logging, get_logger

        configure_logging(AppConfig())
        logger = get_logger("my_component")
        logger.info("test")

        output = captured.getvalue()
        log_entry = json.loads(output.strip())

        assert log_entry["logger"] == "my_component"
```

**Step 2: Run test to verify it fails**

Run: `cd services/edgar-mcp && pytest tests/test_logging.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'edgar_mcp.logging'"

**Step 3: Write logging implementation**

```python
# edgar_mcp/logging.py
import logging
import structlog
from structlog.typing import Processor

from edgar_mcp.config import AppConfig


def configure_logging(config: AppConfig) -> None:
    """Configure structlog for JSON (production) or console (development) output."""
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", key="time"),
    ]

    if config.environment == "development":
        renderer = structlog.dev.ConsoleRenderer(colors=True, pad_level=False)
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
        cache_logger_on_first_use=False,  # False for testing
    )

# Module-level logger is safe: structlog uses lazy proxy that defers configuration until first log
# call, so configure_logging() in main.py takes effect even when we call it on top of the module:
# 
# logger = get_logger("ModuleX")
# 
# def test() -> None:
#     logger.log("Test")
def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Get a logger instance, optionally with a bound name."""
    logger = structlog.get_logger()
    if name:
        logger = logger.bind(logger=name)
    return logger
```

**Step 4: Run test to verify it passes**

Run: `cd services/edgar-mcp && pytest tests/test_logging.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add services/edgar-mcp/src/edgar_mcp/logging.py services/edgar-mcp/tests/test_logging.py
git commit -m "feat(edgar-mcp): add structlog configuration"
```

---

## Task 5.5: Trace Context Middleware

**Files:**
- Create: `services/edgar-mcp/src/edgar_mcp/middleware.py`

**Step 1: Create trace context middleware**

```python
# edgar_mcp/middleware.py
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
import structlog
from opentelemetry import trace


class TraceContextMiddleware(BaseHTTPMiddleware):
    EXCLUDED_PATHS = {"/probe", "/health", "/metrics"}

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

**Step 2: Commit**

```bash
git add services/edgar-mcp/src/edgar_mcp/middleware.py
git commit -m "feat(edgar-mcp): add trace context middleware"
```

---

## Task 6: Probes - HTTP Endpoints

**Files:**
- Create: `services/edgar-mcp/src/edgar_mcp/api/probes.py`
- Create: `services/edgar-mcp/tests/test_probes.py`

**Step 1: Write failing test for probe endpoint**

```python
# tests/test_probes.py
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class TestProbeEndpoint:
    """Test /probe endpoint behavior."""

    def test_returns_version(self):
        """GET /probe returns configured version."""
        from edgar_mcp.api.probes import create_probe_router
        from edgar_mcp.config import AppConfig

        app = FastAPI()
        config = AppConfig(version="1.2.3")
        app.include_router(create_probe_router(config))

        client = TestClient(app)
        response = client.get("/probe")

        assert response.status_code == 200
        assert response.json() == {"version": "1.2.3"}

    def test_probe_not_in_openapi_schema(self):
        """Probe endpoint is excluded from OpenAPI schema."""
        from edgar_mcp.api.probes import create_probe_router
        from edgar_mcp.config import AppConfig

        app = FastAPI()
        config = AppConfig()
        app.include_router(create_probe_router(config))

        client = TestClient(app)
        response = client.get("/openapi.json")

        schema = response.json()
        assert "/probe" not in schema.get("paths", {})
```

**Step 2: Run test to verify it fails**

Run: `cd services/edgar-mcp && pytest tests/test_probes.py::TestProbeEndpoint -v`
Expected: FAIL with "cannot import name 'create_probe_router'"

**Step 3: Write probe endpoint implementation**

```python
# edgar_mcp/api/probes.py
from fastapi import APIRouter

from edgar_mcp.config import AppConfig


def create_probe_router(config: AppConfig) -> APIRouter:
    """Create router with probe endpoints."""
    router = APIRouter(tags=["Monitoring"])

    @router.get("/probe", include_in_schema=False)
    async def probe() -> dict:
        """Liveness probe - returns version."""
        return {"version": config.version}

    return router
```

**Step 4: Run test to verify it passes**

Run: `cd services/edgar-mcp && pytest tests/test_probes.py::TestProbeEndpoint -v`
Expected: All 2 tests PASS

**Step 5: Commit**

```bash
git add services/edgar-mcp/src/edgar_mcp/api/probes.py services/edgar-mcp/tests/test_probes.py
git commit -m "feat(edgar-mcp): add /probe endpoint"
```

---

## Task 7: Health Endpoint - Database Check

**Files:**
- Modify: `services/edgar-mcp/src/edgar_mcp/api/probes.py`
- Modify: `services/edgar-mcp/tests/test_probes.py`

**Step 1: Write failing test for health endpoint with database**

```python
# tests/test_probes.py (append to file)
from unittest.mock import AsyncMock, MagicMock


class TestHealthEndpoint:
    """Test /health endpoint behavior."""

    def test_returns_healthy_when_db_ok(self):
        """GET /health returns healthy when database responds."""
        from edgar_mcp.api.probes import create_probe_router
        from edgar_mcp.config import AppConfig

        app = FastAPI()
        config = AppConfig()

        # Mock session factory that succeeds
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_session.execute = AsyncMock()

        mock_factory = MagicMock(return_value=mock_session)

        app.include_router(create_probe_router(config, session_factory=mock_factory))

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["checks"]["postgres"] == "ok"

    def test_returns_unhealthy_when_db_fails(self):
        """GET /health returns 503 when database check fails."""
        from edgar_mcp.api.probes import create_probe_router
        from edgar_mcp.config import AppConfig

        app = FastAPI()
        config = AppConfig()

        # Mock session factory that fails
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_session.execute = AsyncMock(side_effect=Exception("Connection refused"))

        mock_factory = MagicMock(return_value=mock_session)

        app.include_router(create_probe_router(config, session_factory=mock_factory))

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["checks"]["postgres"] == "error"
```

**Step 2: Run test to verify it fails**

Run: `cd services/edgar-mcp && pytest tests/test_probes.py::TestHealthEndpoint -v`
Expected: FAIL (signature mismatch or missing /health endpoint)

**Step 3: Update probes implementation with health endpoint**

```python
# edgar_mcp/api/probes.py
from fastapi import APIRouter, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from edgar_mcp.config import AppConfig


def create_probe_router(
    config: AppConfig,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> APIRouter:
    """Create router with probe and health endpoints."""
    router = APIRouter(tags=["Monitoring"])

    @router.get("/probe", include_in_schema=False)
    async def probe() -> dict:
        """Liveness probe - returns version."""
        return {"version": config.version}

    @router.get("/health", include_in_schema=False)
    async def health(response: Response) -> dict:
        """Readiness probe - checks dependencies."""
        checks: dict[str, str] = {}
        healthy = True

        # Check PostgreSQL
        if session_factory is not None:
            try:
                async with session_factory() as session:
                    await session.execute(text("SELECT 1"))
                checks["postgres"] = "ok"
            except Exception as e:
                checks["postgres"] = f"error: {e}"
                healthy = False

        if not healthy:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

        return {"status": "healthy" if healthy else "unhealthy", "checks": checks}

    return router
```

**Step 4: Run test to verify it passes**

Run: `cd services/edgar-mcp && pytest tests/test_probes.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add services/edgar-mcp/src/edgar_mcp/api/probes.py services/edgar-mcp/tests/test_probes.py
git commit -m "feat(edgar-mcp): add /health endpoint with database check"
```

---

## Task 8: Health Endpoint - RabbitMQ Check

**Files:**
- Modify: `services/edgar-mcp/src/edgar_mcp/api/probes.py`
- Modify: `services/edgar-mcp/tests/test_probes.py`

**Step 1: Write failing test for RabbitMQ health check**

```python
# tests/test_probes.py (append to TestHealthEndpoint class)

    def test_checks_rabbitmq_connection(self):
        """GET /health checks RabbitMQ connection status."""
        from edgar_mcp.api.probes import create_probe_router
        from edgar_mcp.config import AppConfig

        app = FastAPI()
        config = AppConfig()

        # Mock RabbitMQ connection
        mock_connection = MagicMock()
        mock_connection.is_closed = False

        app.include_router(
            create_probe_router(config, rabbitmq_connection=mock_connection)
        )

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["checks"]["rabbitmq"] == "ok"

    def test_unhealthy_when_rabbitmq_closed(self):
        """GET /health returns 503 when RabbitMQ connection is closed."""
        from edgar_mcp.api.probes import create_probe_router
        from edgar_mcp.config import AppConfig

        app = FastAPI()
        config = AppConfig()

        mock_connection = MagicMock()
        mock_connection.is_closed = True

        app.include_router(
            create_probe_router(config, rabbitmq_connection=mock_connection)
        )

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["checks"]["rabbitmq"] == "error"
```

**Step 2: Run test to verify it fails**

Run: `cd services/edgar-mcp && pytest tests/test_probes.py::TestHealthEndpoint::test_checks_rabbitmq_connection -v`
Expected: FAIL (no rabbitmq in checks)

**Step 3: Add RabbitMQ check to health endpoint**

```python
# edgar_mcp/api/probes.py
from fastapi import APIRouter, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from aio_pika.abc import AbstractRobustConnection

from edgar_mcp.config import AppConfig
from edgar_mcp.logging import get_logger

logger = get_logger("probes")


def create_probe_router(
    config: AppConfig,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    rabbitmq_connection: AbstractRobustConnection | None = None,
) -> APIRouter:
    """Create router with probe and health endpoints."""
    router = APIRouter(tags=["Monitoring"])

    @router.get("/probe", include_in_schema=False)
    async def probe() -> dict:
        """Liveness probe - returns version."""
        return {"version": config.version}

    @router.get("/health", include_in_schema=False)
    async def health(response: Response) -> dict:
        """Readiness probe - checks dependencies."""
        checks: dict[str, str] = {}
        healthy = True

        # Check PostgreSQL
        if session_factory is not None:
            try:
                async with session_factory() as session:
                    await session.execute(text("SELECT 1"))
                checks["postgres"] = "ok"
            except Exception as e:
                logger.error("Postgres health check failed", error=str(e))
                checks["postgres"] = "error"
                healthy = False

        # Check RabbitMQ
        if rabbitmq_connection is not None:
            try:
                if rabbitmq_connection.is_closed:
                    raise ConnectionError("Connection closed")
                checks["rabbitmq"] = "ok"
            except Exception as e:
                logger.error("RabbitMQ health check failed", error=str(e))
                checks["rabbitmq"] = "error"
                healthy = False

        if not healthy:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

        return {"status": "healthy" if healthy else "unhealthy", "checks": checks}

    return router
```

**Step 4: Run test to verify it passes**

Run: `cd services/edgar-mcp && pytest tests/test_probes.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add services/edgar-mcp/src/edgar_mcp/api/probes.py services/edgar-mcp/tests/test_probes.py
git commit -m "feat(edgar-mcp): add RabbitMQ check to /health endpoint"
```

---

## Task 9: Database Engine Setup

**Files:**
- Create: `services/edgar-mcp/src/edgar_mcp/db/engine.py`
- Create: `services/edgar-mcp/tests/test_database.py`

**Step 1: Write failing test for database connection**

This test uses testcontainers for a real PostgreSQL instance:

```python
# tests/test_database.py
import pytest
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="module")
def postgres_container():
    """Start a PostgreSQL container for testing."""
    with PostgresContainer("postgres:16-alpine") as postgres:
        yield postgres


class TestDatabaseConnection:
    """Test database connection behavior."""

    @pytest.mark.asyncio
    async def test_can_connect_and_query(self, postgres_container):
        """Engine can connect to PostgreSQL and execute queries."""
        from edgar_mcp.config import DatabaseConfig
        from edgar_mcp.db.engine import create_engine, create_session_factory

        # DatabaseConfig handles the URL transformation automatically
        config = DatabaseConfig(url=postgres_container.get_connection_url())

        engine = create_engine(config)
        factory = create_session_factory(engine)

        async with factory() as session:
            from sqlalchemy import text

            result = await session.execute(text("SELECT 1 as value"))
            row = result.fetchone()

        assert row[0] == 1

        await engine.dispose()

    @pytest.mark.asyncio
    async def test_session_commits_on_success(self, postgres_container):
        """Session commits changes when context exits normally."""
        from edgar_mcp.config import DatabaseConfig
        from edgar_mcp.db.engine import create_engine, create_session_factory, get_session

        config = DatabaseConfig(url=postgres_container.get_connection_url())

        engine = create_engine(config)
        factory = create_session_factory(engine)

        # Create a table and insert data
        async with factory() as session:
            from sqlalchemy import text

            await session.execute(text("CREATE TABLE IF NOT EXISTS test_commit (id INT)"))
            await session.commit()

        async with get_session(factory) as session:
            from sqlalchemy import text

            await session.execute(text("INSERT INTO test_commit VALUES (42)"))

        # Verify it was committed
        async with factory() as session:
            from sqlalchemy import text

            result = await session.execute(text("SELECT id FROM test_commit"))
            row = result.fetchone()

        assert row[0] == 42

        # Cleanup
        async with factory() as session:
            from sqlalchemy import text
            await session.execute(text("DROP TABLE IF EXISTS test_commit"))
            await session.commit()

        await engine.dispose()

    @pytest.mark.asyncio
    async def test_session_rolls_back_on_error(self, postgres_container):
        """Session rolls back changes when an exception occurs."""
        from edgar_mcp.config import DatabaseConfig
        from edgar_mcp.db.engine import create_engine, create_session_factory, get_session

        config = DatabaseConfig(url=postgres_container.get_connection_url())

        engine = create_engine(config)
        factory = create_session_factory(engine)

        # Create a table
        async with factory() as session:
            from sqlalchemy import text

            await session.execute(text("CREATE TABLE IF NOT EXISTS test_rollback (id INT)"))
            await session.commit()

        # Try to insert but raise an error
        with pytest.raises(ValueError, match="Simulated error"):
            async with get_session(factory) as session:
                from sqlalchemy import text

                await session.execute(text("INSERT INTO test_rollback VALUES (99)"))
                raise ValueError("Simulated error")

        # Verify nothing was committed
        async with factory() as session:
            from sqlalchemy import text

            result = await session.execute(text("SELECT COUNT(*) FROM test_rollback"))
            count = result.scalar()

        assert count == 0

        # Cleanup
        async with factory() as session:
            from sqlalchemy import text
            await session.execute(text("DROP TABLE IF EXISTS test_rollback"))
            await session.commit()

        await engine.dispose()
```

**Step 2: Run test to verify it fails**

Run: `cd services/edgar-mcp && pytest tests/test_database.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'edgar_mcp.db.engine'"

**Step 3: Write database engine implementation**

```python
# edgar_mcp/db/engine.py
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from edgar_mcp.config import DatabaseConfig


def create_engine(config: DatabaseConfig) -> AsyncEngine:
    """Create async database engine."""
    return create_async_engine(
        config.url,
        echo=False,
        pool_size=5,
        max_overflow=10,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create session factory for the engine."""
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@asynccontextmanager
async def get_session(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Get a session with automatic commit/rollback."""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

**Step 4: Run test to verify it passes**

Run: `cd services/edgar-mcp && pytest tests/test_database.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add services/edgar-mcp/src/edgar_mcp/db/engine.py services/edgar-mcp/tests/test_database.py
git commit -m "feat(edgar-mcp): add database engine setup"
```

---

## Task 10: Queue Connection, Consumer, and Publisher

**Files:**
- Create: `services/edgar-mcp/src/edgar_mcp/queue/connection.py`
- Create: `services/edgar-mcp/src/edgar_mcp/queue/consumer.py`
- Create: `services/edgar-mcp/src/edgar_mcp/queue/publisher.py`
- Create: `services/edgar-mcp/tests/test_queue.py`

**Step 1: Write failing test for queue message flow**

```python
# tests/test_queue.py
import asyncio
import json
import pytest
from testcontainers.rabbitmq import RabbitMqContainer


@pytest.fixture(scope="module")
def rabbitmq_container():
    """Start a RabbitMQ container for testing."""
    with RabbitMqContainer("rabbitmq:3-alpine") as rabbitmq:
        yield rabbitmq


class TestQueueMessageFlow:
    """Test message publishing and consuming behavior."""

    @pytest.mark.asyncio
    async def test_publisher_message_received_by_consumer(self, rabbitmq_container):
        """Messages published via Publisher are received by Consumer."""
        from edgar_mcp.config import RabbitConfig
        from edgar_mcp.queue.connection import create_connection, create_channel
        from edgar_mcp.queue.consumer import Consumer
        from edgar_mcp.queue.publisher import Publisher

        # Get connection URL from container
        host = rabbitmq_container.get_container_host_ip()
        port = rabbitmq_container.get_exposed_port(5672)
        config = RabbitConfig(url=f"amqp://guest:guest@{host}:{port}/")

        connection = await create_connection(config)
        channel = await create_channel(connection)

        # Track received messages
        received_messages: list[bytes] = []
        received = asyncio.Event()

        async def handler(body: bytes) -> None:
            received_messages.append(body)
            received.set()

        # Set up publisher and consumer on same queue
        queue_name = "test-publisher-consumer"

        publisher = Publisher(channel, queue_name)
        await publisher.setup()

        consumer = Consumer(channel, queue_name)
        await consumer.setup()
        await consumer.start(handler)

        # Publish a message via Publisher
        test_payload = json.dumps({"test": "data"}).encode()
        await publisher.publish(test_payload, correlation_id="test-123")

        # Wait with timeout instead of sleep
        await asyncio.wait_for(received.wait(), timeout=5.0)

        assert len(received_messages) == 1
        assert received_messages[0] == test_payload

        await consumer.stop()
        await connection.close()

    @pytest.mark.asyncio
    async def test_consumer_processes_messages_sequentially(self, rabbitmq_container):
        """Consumer processes messages one at a time (prefetch=1)."""
        from edgar_mcp.config import RabbitConfig
        from edgar_mcp.queue.connection import create_connection, create_channel
        from edgar_mcp.queue.consumer import Consumer

        host = rabbitmq_container.get_container_host_ip()
        port = rabbitmq_container.get_exposed_port(5672)
        config = RabbitConfig(url=f"amqp://guest:guest@{host}:{port}/")

        connection = await create_connection(config)
        channel = await create_channel(connection)

        events: list[tuple[int, str]] = []
        all_done = asyncio.Event()

        async def slow_handler(body: bytes) -> None:
            data = json.loads(body)
            events.append((data["order"], "start"))
            await asyncio.sleep(0.1)
            events.append((data["order"], "end"))
            if data["order"] == 2:
                all_done.set()

        consumer = Consumer(channel, "test-queue-sequential")
        await consumer.setup()
        await consumer.start(slow_handler)

        # Publish multiple messages directly
        from aio_pika import Message

        for i in range(3):
            await channel.default_exchange.publish(
                Message(body=json.dumps({"order": i}).encode()),
                routing_key="test-queue-sequential",
            )

        # Wait for all messages to be processed
        await asyncio.wait_for(all_done.wait(), timeout=5.0)

        # Sequential: each message completes before next starts
        # Expected: [(0,"start"), (0,"end"), (1,"start"), (1,"end"), (2,"start"), (2,"end")]
        assert events == [
            (0, "start"), (0, "end"),
            (1, "start"), (1, "end"),
            (2, "start"), (2, "end"),
        ]

        await consumer.stop()
        await connection.close()
```

**Step 2: Run test to verify it fails**

Run: `cd services/edgar-mcp && pytest tests/test_queue.py -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 3: Write queue connection, consumer, and publisher**

```python
# edgar_mcp/queue/connection.py
from aio_pika import connect_robust
from aio_pika.abc import AbstractRobustConnection, AbstractRobustChannel

from edgar_mcp.config import RabbitConfig
from edgar_mcp.logging import get_logger

logger = get_logger("queue")


async def create_connection(config: RabbitConfig) -> AbstractRobustConnection:
    """Create robust RabbitMQ connection with auto-reconnect."""
    connection = await connect_robust(config.url)
    logger.info("Connected to RabbitMQ")
    return connection


async def create_channel(connection: AbstractRobustConnection) -> AbstractRobustChannel:
    """Create channel with prefetch=1 for sequential processing."""
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=1)
    return channel
```

```python
# edgar_mcp/queue/consumer.py
import structlog
from collections.abc import Awaitable, Callable

from aio_pika import IncomingMessage
from aio_pika.abc import AbstractRobustChannel, AbstractQueue

from edgar_mcp.logging import get_logger

logger = get_logger("consumer")

MessageHandler = Callable[[bytes], Awaitable[None]]


class Consumer:
    """RabbitMQ message consumer."""

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

    async def start(self, handler: MessageHandler) -> None:
        """Start consuming messages."""
        if self._queue is None:
            raise RuntimeError("Must call setup() before start()")

        async def process(message: IncomingMessage) -> None:
            structlog.contextvars.clear_contextvars()
            structlog.contextvars.bind_contextvars(
                message_id=message.message_id,
                correlation_id=message.correlation_id,
            )

            logger.info("Processing message")
            try:
                await handler(message.body)
                await message.ack()
                logger.info("Message processed")
            except Exception as e:
                logger.error("Message processing failed", error=str(e))
                await message.nack(requeue=False)

        self._consumer_tag = await self._queue.consume(process)
        logger.info("Consumer started", queue=self.queue_name)

    async def stop(self) -> None:
        """Stop consuming messages."""
        if self._queue is not None and self._consumer_tag is not None:
            await self._queue.cancel(self._consumer_tag)
            self._consumer_tag = None
            logger.info("Consumer stopped")
```

```python
# edgar_mcp/queue/publisher.py
from aio_pika import Message
from aio_pika.abc import AbstractRobustChannel

from edgar_mcp.logging import get_logger

logger = get_logger("publisher")


class Publisher:
    """RabbitMQ message publisher."""

    def __init__(self, channel: AbstractRobustChannel, queue_name: str):
        self.channel = channel
        self.queue_name = queue_name

    async def setup(self) -> None:
        """Declare the queue."""
        await self.channel.declare_queue(self.queue_name, durable=True)

    async def publish(self, body: bytes, correlation_id: str | None = None) -> None:
        """Publish a message to the queue."""
        message = Message(
            body,
            content_type="application/json",
            correlation_id=correlation_id,
            delivery_mode=2,  # Persistent
        )
        await self.channel.default_exchange.publish(
            message,
            routing_key=self.queue_name,
        )
        logger.info("Message published", queue=self.queue_name, correlation_id=correlation_id)
```

**Step 4: Run test to verify it passes**

Run: `cd services/edgar-mcp && pytest tests/test_queue.py -v`
Expected: All 2 tests PASS

**Step 5: Commit**

```bash
git add services/edgar-mcp/src/edgar_mcp/queue/connection.py services/edgar-mcp/src/edgar_mcp/queue/consumer.py services/edgar-mcp/src/edgar_mcp/queue/publisher.py services/edgar-mcp/tests/test_queue.py
git commit -m "feat(edgar-mcp): add RabbitMQ connection, consumer, and publisher"
```

---

## Task 11: Metrics Setup (ASGI Middleware)

**Files:**
- Create: `services/edgar-mcp/src/edgar_mcp/metrics.py`
- Create: `services/edgar-mcp/tests/test_metrics.py`

**Note:** Metrics are served via ASGI middleware on the main app port (`/metrics`), not a separate HTTP server. This provides clean shutdown and better testability.

**Step 1: Write failing test for metrics endpoint**

```python
# tests/test_metrics.py
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class TestMetricsEndpoint:
    """Test Prometheus metrics exposure via ASGI middleware."""

    def test_exposes_metrics_endpoint(self):
        """GET /metrics returns Prometheus format metrics."""
        from edgar_mcp.config import AppConfig
        from edgar_mcp.metrics import configure_metrics, create_metrics_app

        app = FastAPI()
        app_config = AppConfig(version="1.0.0")
        
        configure_metrics(app_config)
        app.mount("/metrics", create_metrics_app())

        client = TestClient(app)
        response = client.get("/metrics")

        assert response.status_code == 200
        assert "# HELP" in response.text
        assert "# TYPE" in response.text

    def test_includes_custom_metrics(self):
        """Custom metrics appear in /metrics output."""
        from edgar_mcp.config import AppConfig
        from edgar_mcp.metrics import configure_metrics, create_metrics_app, get_meter

        app = FastAPI()
        app_config = AppConfig(version="2.0.0")
        
        configure_metrics(app_config)
        app.mount("/metrics", create_metrics_app())

        # Create and increment a test counter
        meter = get_meter("test")
        counter = meter.create_counter("test_requests_total", description="Test counter")
        counter.add(1, {"endpoint": "/test"})

        client = TestClient(app)
        response = client.get("/metrics")

        assert "test_requests_total" in response.text
```

**Step 2: Run test to verify it fails**

Run: `cd services/edgar-mcp && pytest tests/test_metrics.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'edgar_mcp.metrics'"

**Step 3: Write metrics implementation**

```python
# edgar_mcp/metrics.py
from opentelemetry import metrics
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from prometheus_client import REGISTRY, generate_latest, CONTENT_TYPE_LATEST
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route

from edgar_mcp.config import AppConfig


def configure_metrics(app_config: AppConfig) -> MeterProvider:
    """Configure OpenTelemetry metrics with Prometheus exporter."""
    resource = Resource.create({
        SERVICE_NAME: "edgar-mcp",
        SERVICE_VERSION: app_config.version,
    })

    reader = PrometheusMetricReader()
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(provider)

    return provider


def create_metrics_app() -> Starlette:
    """Create ASGI app that serves Prometheus metrics."""
    async def metrics_endpoint(request):
        data = generate_latest(REGISTRY)
        return Response(data, media_type=CONTENT_TYPE_LATEST)

    return Starlette(routes=[Route("/", metrics_endpoint)])


def get_meter(name: str) -> metrics.Meter:
    """Get a meter for creating metrics."""
    return metrics.get_meter(name)
```

**Step 4: Run test to verify it passes**

Run: `cd services/edgar-mcp && pytest tests/test_metrics.py -v`
Expected: All 2 tests PASS

**Step 5: Commit**

```bash
git add services/edgar-mcp/src/edgar_mcp/metrics.py services/edgar-mcp/tests/test_metrics.py
git commit -m "feat(edgar-mcp): add OpenTelemetry metrics with ASGI middleware"
```

---

## Task 12: Main Application

**Files:**
- Create: `services/edgar-mcp/src/edgar_mcp/main.py`

**Step 1: Write main application**

```python
# edgar_mcp/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastmcp import FastMCP
from dotenv import load_dotenv

from edgar_mcp.config import AppConfig, DatabaseConfig, RabbitConfig
from edgar_mcp.logging import configure_logging, get_logger
from edgar_mcp.metrics import configure_metrics, create_metrics_app
from edgar_mcp.db.engine import create_engine, create_session_factory
from edgar_mcp.queue.connection import create_connection, create_channel
from edgar_mcp.queue.consumer import Consumer
from edgar_mcp.api.probes import create_probe_router
from edgar_mcp.middleware import TraceContextMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.aio_pika import AioPikaInstrumentor

# Load .env before settings are instantiated
load_dotenv()

# Load configuration
app_config = AppConfig()
db_config = DatabaseConfig()
rabbit_config = RabbitConfig()

# Configure logging early
configure_logging(app_config)

logger = get_logger("main")


async def handle_notification(body: bytes) -> None:
    """Process incoming notifications from queue."""
    import json
    data = json.loads(body)
    logger.info("Processing notification", resource=data.get("resource"))


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    logger.info("Starting application", version=app_config.version)

    # Initialize metrics (returns MeterProvider, no separate server)
    app.state.meter_provider = configure_metrics(app_config)
    logger.info("Metrics configured")

    # Initialize database
    app.state.db_engine = create_engine(db_config)
    app.state.session_factory = create_session_factory(app.state.db_engine)
    logger.info("Database connected")

    # Setup OpenTelemetry instrumentation
    FastAPIInstrumentor.instrument_app(app, excluded_urls="/probe,/health")
    SQLAlchemyInstrumentor().instrument(engine=app.state.db_engine.sync_engine)
    AioPikaInstrumentor().instrument()

    # Initialize RabbitMQ
    app.state.rabbitmq_connection = await create_connection(rabbit_config)
    app.state.rabbitmq_channel = await create_channel(app.state.rabbitmq_connection)
    logger.info("RabbitMQ connected")

    # Start message consumer
    app.state.consumer = Consumer(app.state.rabbitmq_channel, "edgar-notifications")
    await app.state.consumer.setup()
    await app.state.consumer.start(handle_notification)
    logger.info("Consumer started")

    # Register probe routes with dependencies from app.state
    app.include_router(
        create_probe_router(
            app_config,
            app.state.session_factory,
            app.state.rabbitmq_connection
        )
    )

    yield

    # Shutdown
    logger.info("Shutting down")
    if hasattr(app.state, "consumer"):
        await app.state.consumer.stop()
    if hasattr(app.state, "rabbitmq_connection"):
        await app.state.rabbitmq_connection.close()
    if hasattr(app.state, "db_engine"):
        await app.state.db_engine.dispose()
    logger.info("Shutdown complete")


# FastMCP server
mcp = FastMCP(
    "Edgar MCP",
    version=app_config.version,
)

# Create MCP ASGI app (mount at /mcp, so MCP path stays "/")
mcp_app = mcp.http_app(path="/")


@asynccontextmanager
async def combined_lifespan(app: FastAPI):
    """Combine app lifespan with FastMCP lifespan."""
    async with app_lifespan(app):
        async with mcp_app.lifespan(app):
            yield


# FastAPI app with combined lifespan
app = FastAPI(
    title="Edgar MCP",
    version=app_config.version,
    lifespan=combined_lifespan,
)

# Add trace context middleware
app.add_middleware(TraceContextMiddleware)

# Mount MCP and metrics
app.mount("/mcp", mcp_app)
app.mount("/metrics", create_metrics_app())


def main():
    """Entry point for running the application."""
    import uvicorn
    uvicorn.run(
        "edgar_mcp.main:app",
        host="0.0.0.0",
        port=8000,
        log_config=None,
    )


if __name__ == "__main__":
    main()
```

**Step 2: Commit**

```bash
git add services/edgar-mcp/src/edgar_mcp/main.py
git commit -m "feat(edgar-mcp): add main application with combined lifespan"
```

---

## Task 13: Add .env.example

**Files:**
- Create: `services/edgar-mcp/.env.example`

**Step 1: Create example environment file**

```bash
# services/edgar-mcp/.env.example

# Application
APP_LOG_LEVEL=info
APP_VERSION=0.1.0
APP_ENVIRONMENT=development

# Database - REQUIRED: either DB_URL or all individual settings
# DB_URL=postgresql+asyncpg://user:password@localhost:5432/edgar_mcp

# Database (option 2: individual settings - all but port required)
DB_HOST=localhost
DB_PORT=5432
DB_NAME=edgar_mcp
DB_USER=postgres
DB_PASSWORD=postgres

# RabbitMQ - REQUIRED: either RABBITMQ_URL or all individual settings
# RABBITMQ_URL=amqp://guest:guest@localhost:5672/

# RabbitMQ (option 2: individual settings - all required)
RABBITMQ_HOST=localhost
RABBITMQ_PORT=5672
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest
RABBITMQ_VHOST=/

# Note: Metrics are served via /metrics on the main app port (8000)
# No separate OTEL_EXPORTER_PROMETHEUS_* config needed
```

**Step 2: Commit**

```bash
git add services/edgar-mcp/.env.example
git commit -m "docs(edgar-mcp): add .env.example"
```

---

## Task 14: Final Test Run and Cleanup

**Step 1: Run all tests**

Run: `cd services/edgar-mcp && pytest -v`
Expected: All tests PASS

**Step 2: Run linting with ruff**

Run: `cd services/edgar-mcp && ruff check src/ tests/`
Expected: No errors

**Step 3: Run ruff format**

Run: `cd services/edgar-mcp && ruff format src/ tests/`
Expected: Files formatted

**Step 4: Run type checking**

Run: `cd services/edgar-mcp && pyright src/`
Expected: No errors

**Step 5: Final commit if any fixes needed**

```bash
git add -A
git commit -m "chore(edgar-mcp): fix linting and type issues"
```

---

## Summary

| Task | Component | Tests |
|------|-----------|-------|
| 1 | Project scaffolding | - |
| 2 | Database config | 4 tests |
| 3 | RabbitMQ config | 4 tests |
| 4 | App/Metrics config | 4 tests |
| 5 | Logging | 3 tests |
| 6-8 | Probes | 6 tests |
| 9 | Database engine | 3 tests |
| 10 | Queue consumer/publisher | 2 tests |
| 11 | Metrics | 2 tests |
| 12 | Main application | - |
| 13-14 | Docs and cleanup | - |

**Total: ~28 behavioral tests**
