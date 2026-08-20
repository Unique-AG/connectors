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
    #
    # `log_config=None` is what keeps every line inside the pod's declared log contract. Left to
    # its default, uvicorn applies its own `dictConfig` here — after `create_app` above has already
    # configured logging — and that config puts `uvicorn`, `uvicorn.error` and `uvicorn.access` on
    # handlers of its own with `propagate = False`, writing plain text: the access lines to
    # **stdout**, the rest to stderr. The chart advertises `logging.unique.app/format: pino-json`
    # on stderr, so every access line would be a line the log pipeline cannot parse on a stream it
    # is not reading. `None` skips that config entirely, leaving uvicorn's loggers propagating to
    # the root handler `configure_logging` installed — pino-json on stderr, through this service's
    # redaction and correlation filters.
    #
    # Trap: uvicorn decides whether to log access lines at all with `access_logger.hasHandlers()`,
    # which walks up to the root. It is true here because `create_app` ran first, and it is why
    # this is `None` rather than an empty dict: uvicorn's own logger config must not be replaced
    # with one that has no handler.
    uvicorn.run(app, host="0.0.0.0", port=_config.port, log_config=None)


if __name__ == "__main__":
    main()
