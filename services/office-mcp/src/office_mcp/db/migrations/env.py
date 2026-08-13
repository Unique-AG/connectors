import asyncio
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from office_mcp.config import DatabaseConfig
from office_mcp.db.models import Base

load_dotenv()

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _configparser_escape(value: str) -> str:
    """Double any literal `%` so `ConfigParser`'s `BasicInterpolation` doesn't choke on it.

    `Config.set_main_option`/`get_main_option` go through a `configparser.ConfigParser`, whose
    default interpolation treats `%` as the start of a `%(name)s` reference and raises on any
    other use — including the `%40`-style percent-encoding SQLAlchemy's `render_as_string` puts
    in a DSN's credentials. Doubling here is undone by the interpolation on read, so
    `get_main_option`/`get_section` hand back the original (still percent-encoded) URL.
    """
    return value.replace("%", "%%")


# Office-mcp reads its DB connection from env vars (DB_URL or DB_HOST/DB_NAME/...),
# same as the running app — not from the static `sqlalchemy.url` in alembic.ini.
_db_config = DatabaseConfig()
config.set_main_option("sqlalchemy.url", _configparser_escape(_db_config.connection_url))

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=_db_config.connect_args,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
