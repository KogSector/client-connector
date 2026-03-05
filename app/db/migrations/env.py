"""Alembic environment for async SQLAlchemy migrations.

This env.py is configured for the asyncpg driver used by the Client Connector
service. It reads DATABASE_URL dynamically from the application settings rather
than from alembic.ini, so the ini file has sqlalchemy.url commented out.

Both offline (SQL script) and online (direct live migration) modes are supported.
The online path uses an AsyncEngine and asyncio.run() so Alembic's synchronous
entry point can drive the async migration runner.
"""
import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, async_engine_from_config

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so app.* imports resolve
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

# ---------------------------------------------------------------------------
# Alembic Config object — provides access to values in alembic.ini
# ---------------------------------------------------------------------------
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# Import Base and settings *after* sys.path is set
# ---------------------------------------------------------------------------
from app.db.models import Base                  # noqa: E402
from app.config import get_settings             # noqa: E402

# Inject the live DATABASE_URL into the Alembic config at runtime so that
# alembic.ini does not need to contain credentials.
_settings = get_settings()
config.set_main_option("sqlalchemy.url", _settings.database_url)

# The metadata object that Alembic uses for --autogenerate comparison.
target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Offline migration runner
# ---------------------------------------------------------------------------

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    In this mode Alembic emits SQL to stdout/file without connecting to the
    database.  Useful for generating migration scripts to review or apply
    manually.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Async online migration helpers
# ---------------------------------------------------------------------------

def do_run_migrations(connection: Connection) -> None:
    """Execute migrations using an already-established synchronous *connection*.

    Called inside ``run_sync()`` so Alembic's synchronous API works against the
    async engine.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and drive migrations through it.

    The engine is disposed immediately after migration completes to avoid
    leaving dangling connection-pool threads.
    """
    connectable: AsyncEngine = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,       # no pooling during migrations
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online migrations.

    Delegates to the async runner via ``asyncio.run()`` so that Alembic's
    synchronous ``env.py`` contract is satisfied while still using asyncpg.
    """
    asyncio.run(run_async_migrations())


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
