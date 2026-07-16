"""Async engine construction, session factories, and transaction scopes."""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings


def build_engine(settings: Settings | None = None) -> AsyncEngine:
    """Create an async engine from validated settings; no connection is opened yet."""
    resolved = settings or get_settings()
    return create_async_engine(resolved.database_url, pool_pre_ping=True)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create a session factory bound to the given engine."""
    return async_sessionmaker(engine, expire_on_commit=False)


@lru_cache
def get_engine() -> AsyncEngine:
    """Return the process-wide engine for the configured database."""
    return build_engine()


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory."""
    return build_session_factory(get_engine())


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession] | None = None,
) -> AsyncIterator[AsyncSession]:
    """Yield a session inside one transaction: commit on success, roll back on error."""
    resolved = factory or get_session_factory()
    async with resolved() as session, session.begin():
        yield session


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding one transactional session per request."""
    async with session_scope() as session:
        yield session
