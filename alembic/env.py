import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

from app import models as _models  # noqa: F401  (register models on the metadata)
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import create_engine, normalize_database_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# The database URL always comes from the app settings (SENTINEL_DATABASE_URL), never alembic.ini.
DATABASE_URL = get_settings().database_url
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=normalize_database_url(DATABASE_URL)[0],
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    # Same engine factory as the app, so hosted-Postgres URL/SSL handling is identical.
    engine = create_engine(DATABASE_URL, pool_size=1, max_overflow=0)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
