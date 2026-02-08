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

        meter = get_meter("test")
        counter = meter.create_counter("test_requests", description="Test counter")
        counter.add(1, {"endpoint": "/test"})

        client = TestClient(app)
        response = client.get("/metrics")

        assert "test_requests_total" in response.text
