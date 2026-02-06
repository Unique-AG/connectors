from aio_pika.abc import AbstractRobustConnection
from fastapi import APIRouter, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
