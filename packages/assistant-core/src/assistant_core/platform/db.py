"""Owns the async database engine and the session factory that every layer uses."""

from collections.abc import AsyncGenerator, Callable

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from assistant_core.platform.config import get_runtime_settings

DBSessionFactory = Callable[[], AsyncSession]

_engine: AsyncEngine | None = None
_session_factory_instance: async_sessionmaker[AsyncSession] | None = None


def _get_engine() -> AsyncEngine:
    """Return the async engine, and create it on first access."""
    global _engine  # noqa: PLW0603
    if _engine is not None:
        return _engine

    settings = get_runtime_settings()
    db_url = make_url(settings.database_url)

    if not db_url.drivername.startswith("postgresql"):
        msg = (
            "SQLite is no longer supported. Set DATABASE_URL to a PostgreSQL URL, e.g. "
            "'postgresql+asyncpg://postgres:postgres@localhost:5432/pathfinder'."
        )
        raise ValueError(msg)

    engine = create_async_engine(
        settings.database_url,
        echo=settings.api_debug,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )
    _engine = engine
    return engine


def get_engine() -> AsyncEngine:
    """Return the async engine."""
    return _get_engine()


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the session factory, and create it on first access."""
    global _session_factory_instance  # noqa: PLW0603
    if _session_factory_instance is not None:
        return _session_factory_instance

    factory = async_sessionmaker(
        _get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    _session_factory_instance = factory
    return factory


def async_session_factory() -> AsyncSession:
    """Create a new async session."""
    return _get_session_factory()()


async def get_db_session() -> AsyncGenerator[AsyncSession]:
    """Yield a request-scoped session, and commit it when the request succeeds."""
    async with _get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def close_db() -> None:
    """Dispose the engine and clear the cached factory."""
    global _engine, _session_factory_instance  # noqa: PLW0603
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory_instance = None
