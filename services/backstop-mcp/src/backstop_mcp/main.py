from dotenv import load_dotenv

load_dotenv()

import uvicorn  # noqa: E402

from backstop_mcp.app import create_app  # noqa: E402
from backstop_mcp.config import AppConfig  # noqa: E402

app = create_app()


def main() -> None:
    config = AppConfig()
    # `log_config=None`: uvicorn's default `dictConfig` runs after `create_app` configured
    # logging and puts `uvicorn` / `uvicorn.access` on plain-text handlers with
    # `propagate=False`. `None` keeps access lines on the root pino handler. An empty dict
    # does not: uvicorn only emits them when `access_logger` already has a handler.
    uvicorn.run("backstop_mcp.main:app", host="0.0.0.0", port=config.port, log_config=None)


if __name__ == "__main__":
    main()
