from dotenv import load_dotenv

load_dotenv()

import uvicorn  # noqa: E402

from office_mcp.app import create_app  # noqa: E402
from office_mcp.config import AppConfig  # noqa: E402

_config = AppConfig()
app = create_app(config=_config)


def main() -> None:
    # Pass the app object rather than the "office_mcp.main:app" string target: a string target
    # makes uvicorn re-import this module under its own name when run as `python -m` or as a
    # script, re-running `create_app()` with a duplicate app instance whose lifespan context
    # would never be disposed. Passing the object keeps `app` importable at module level for
    # deployments that reference `office_mcp.main:app` while only ever building it once.
    uvicorn.run(app, host="0.0.0.0", port=_config.port)


if __name__ == "__main__":
    main()
