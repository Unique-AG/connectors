from dotenv import load_dotenv

load_dotenv()

import uvicorn  # noqa: E402

from backstop_mcp.app import create_app  # noqa: E402
from backstop_mcp.config import AppConfig  # noqa: E402

app = create_app()


def main() -> None:
    config = AppConfig()
    uvicorn.run("backstop_mcp.main:app", host="0.0.0.0", port=config.port)


if __name__ == "__main__":
    main()
