"""Application entry point."""

from typing import cast

from dotenv import load_dotenv

from edgar_mcp.app import create_app
from edgar_mcp.config import AppConfig

load_dotenv()

app = create_app()


def main() -> None:
    """Entry point for running the application."""
    import uvicorn

    app_config = cast(AppConfig, app.state.app_config)
    uvicorn.run(
        "edgar_mcp.main:app",
        host="0.0.0.0",
        port=app_config.port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
