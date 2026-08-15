from dotenv import load_dotenv

load_dotenv()

import uvicorn  # noqa: E402

from office_mcp.app import create_app  # noqa: E402
from office_mcp.config import AppConfig  # noqa: E402

_config = AppConfig()
app = create_app(config=_config)


def main() -> None:
    # Pass the app object, not a string target. String targets cause uvicorn to re-import this
    # module, creating a duplicate app instance with an undisposed lifespan.
    uvicorn.run(app, host="0.0.0.0", port=_config.port)


if __name__ == "__main__":
    main()
