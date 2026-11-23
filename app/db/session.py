from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

_SYNC_POSTGRES_DRIVERS = {"postgres", "postgresql", "postgresql+psycopg2", "postgresql+psycopg"}
_ASYNCPG_SSLMODES = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}


def normalize_database_url(url: str) -> tuple[str, dict[str, Any]]:
    """Make hosted-Postgres URLs work with asyncpg.

    Providers hand out `postgres://...?sslmode=require` URLs. asyncpg needs the
    `postgresql+asyncpg` driver and takes SSL as a connect argument, not a query parameter.
    """
    parsed = make_url(url)
    if parsed.drivername in _SYNC_POSTGRES_DRIVERS:
        parsed = parsed.set(drivername="postgresql+asyncpg")

    connect_args: dict[str, Any] = {}
    if parsed.drivername == "postgresql+asyncpg":
        query = dict(parsed.query)
        sslmode = query.pop("sslmode", None)
        query.pop("channel_binding", None)  # libpq-only option
        if isinstance(sslmode, str) and sslmode in _ASYNCPG_SSLMODES:
            connect_args["ssl"] = sslmode
        parsed = parsed.set(query=query)
    return parsed.render_as_string(hide_password=False), connect_args


def create_engine(database_url: str, *, pool_size: int = 10, max_overflow: int = 10) -> AsyncEngine:
    url, connect_args = normalize_database_url(database_url)
    kwargs: dict[str, Any] = {"pool_pre_ping": True, "connect_args": connect_args}
    if not url.startswith("sqlite"):
        kwargs |= {"pool_size": pool_size, "max_overflow": max_overflow, "pool_recycle": 1800}
    engine = create_async_engine(url, **kwargs)

    if engine.dialect.name == "sqlite":  # used by the fast local test suite

        @event.listens_for(engine.sync_engine, "connect")
        def _enable_sqlite_fks(dbapi_connection, _record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
