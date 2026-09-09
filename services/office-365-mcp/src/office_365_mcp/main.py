from dotenv import find_dotenv, load_dotenv

# `usecwd=True` or the search starts at this file and walks up, which finds the checkout's own
# `.env` whatever directory the process was started in. The tests boot this module from an
# empty directory to keep a developer's `.env` out of their configuration, and that only works
# if the working directory is what is searched.
load_dotenv(find_dotenv(usecwd=True))

import uvicorn  # noqa: E402

from office_365_mcp.app import create_app  # noqa: E402
from office_365_mcp.config import AppConfig  # noqa: E402

_config = AppConfig()
app = create_app(config=_config)


def main() -> None:
    # Pass the app object, not a string target. A string target makes uvicorn re-import this
    # module and build a second app: a second OAuth store that nothing shuts down, and a second
    # pool under it.
    #
    # `log_config=None`: uvicorn's default `dictConfig` runs after `create_app` configured
    # logging. It puts `uvicorn`, `uvicorn.error` and `uvicorn.access` on handlers of its own
    # with `propagate = False`. Those handlers write plain text and send access lines to
    # **stdout**. The chart advertises `logging.unique.app/format: pino-json` on stderr instead.
    #
    # Trap: `None`, not an empty dict. uvicorn logs access lines only when
    # `access_logger.hasHandlers()` finds one, and it finds the root handler `create_app` installed.
    uvicorn.run(app, host="0.0.0.0", port=_config.port, log_config=None)


if __name__ == "__main__":
    main()
